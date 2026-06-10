"""First Run Setup (v1.5): lógica pura del asistente de primera ejecución.

Sin Qt: detección de entorno (Docker, libvirt, almacenamiento), generación del
bundle Docker del Hub (exportable a un NAS), prueba de conexión al Hub y
estado de primera ejecución. La UI (`ui_qt/setup_wizard.py`) y la CLI
(`hypergery-cli setup …`) son capas finas sobre este módulo.

Garantías de seguridad:
- Aquí no se ejecuta Docker, ni sudo, ni nada que cambie el sistema: solo
  lecturas (`--version`, sysfs/grupos) y escritura de ficheros de
  configuración (0600) o del bundle.
- Los tokens nunca se loguean ni se imprimen, salvo en el .env generado
  (0600) cuando se pide explícitamente.
- Las comprobaciones de almacenamiento jamás borran nada.
"""

from __future__ import annotations

import grp
import json
import os
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .config import HyperGeryConfig, config_path

SETUP_PROFILES = {
    "solo": "Solo este PC (sin Hub)",
    "local-docker": "Este PC + Hub local en Docker",
    "nas-docker": "Este PC + Hub/Docker en otro equipo dedicado o NAS",
    "client": "Cliente ligero (conectar a un Hub existente)",
}

BUNDLE_FILES = ("docker-compose.yml", "Dockerfile", ".env.example", "README_SETUP.md", "SECURITY.md")


# --------------------------------------------------------------------------- #
# Estado de primera ejecución                                                  #
# --------------------------------------------------------------------------- #


def should_show_wizard(path: str | Path | None = None) -> bool:
    """True si no hay config inicial o first_run_completed no es "true"."""
    candidate = Path(path).expanduser() if path else config_path()
    if not candidate.exists():
        return True
    return HyperGeryConfig.load(candidate).first_run_completed != "true"


def mark_first_run_complete(
    profile: str,
    *,
    hub_url: str = "",
    hub_token: str = "",
    storage_path: str = "",
    path: str | Path | None = None,
) -> Path:
    if profile not in SETUP_PROFILES:
        raise ValueError(f"Unknown setup profile: {profile!r}. Allowed: {', '.join(sorted(SETUP_PROFILES))}")
    config = HyperGeryConfig.load(path)
    config.first_run_completed = "true"
    config.setup_profile = profile
    if hub_url:
        config.hub_url = hub_url
    if hub_token:
        config.hub_token = hub_token
    if storage_path:
        config.default_vm_storage_path = storage_path
    return config.save(path)


def reset_first_run(path: str | Path | None = None) -> Path:
    config = HyperGeryConfig.load(path)
    config.first_run_completed = ""
    return config.save(path)


def setup_status(path: str | Path | None = None) -> dict[str, Any]:
    """Resumen sin secretos: el token solo se reporta como presente/ausente."""
    config = HyperGeryConfig.load(path)
    return {
        "first_run_completed": config.first_run_completed == "true",
        "setup_profile": config.setup_profile or "(sin elegir)",
        "hub_url": config.hub_url or "(sin configurar)",
        "hub_token_present": bool(config.hub_token),
        "storage_path": config.default_vm_storage_path or "(por defecto)",
        "config_path": str(Path(path).expanduser() if path else config_path()),
    }


# --------------------------------------------------------------------------- #
# Detección de entorno (solo lectura)                                          #
# --------------------------------------------------------------------------- #


def _run_quiet(command: list[str], timeout: int = 10) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def detect_docker() -> dict[str, Any]:
    docker = shutil.which("docker")
    result: dict[str, Any] = {
        "docker_available": bool(docker),
        "docker_path": docker or "",
        "compose_available": False,
        "detail": "",
    }
    if not docker:
        result["detail"] = "docker no está en el PATH. Instálalo con: sudo apt install docker.io docker-compose-v2"
        return result
    proc = _run_quiet([docker, "compose", "version"])
    if proc is not None and proc.returncode == 0:
        result["compose_available"] = True
        result["detail"] = proc.stdout.strip().splitlines()[0] if proc.stdout.strip() else "docker compose disponible"
    else:
        result["detail"] = "docker existe pero `docker compose` no responde. Instala el plugin: sudo apt install docker-compose-v2"
    return result


def detect_libvirt() -> dict[str, Any]:
    """Diagnóstico de virsh/qemu:///system y grupos. NUNCA ejecuta sudo: las
    órdenes que falten se devuelven como texto en suggested_commands."""
    virsh = shutil.which("virsh")
    try:
        group_names = {grp.getgrgid(gid).gr_name for gid in os.getgroups()}
    except (KeyError, OSError):
        group_names = set()
    result: dict[str, Any] = {
        "virsh_available": bool(virsh),
        "system_uri_ok": False,
        "in_libvirt_group": "libvirt" in group_names,
        "in_kvm_group": "kvm" in group_names,
        "detail": "",
        "suggested_commands": [],
    }
    if not virsh:
        result["detail"] = "virsh no está instalado."
        result["suggested_commands"].append("sudo apt install qemu-kvm libvirt-daemon-system libvirt-clients")
    else:
        proc = _run_quiet([virsh, "--connect", "qemu:///system", "version"])
        if proc is not None and proc.returncode == 0:
            result["system_uri_ok"] = True
            result["detail"] = "qemu:///system responde."
        else:
            result["detail"] = "virsh existe pero qemu:///system no responde (¿servicio parado o permisos?)."
            result["suggested_commands"].append("sudo systemctl enable --now libvirtd")
    if not result["in_libvirt_group"]:
        result["suggested_commands"].append("sudo usermod -aG libvirt $USER   # cierra y reabre sesión después")
    if not result["in_kvm_group"]:
        result["suggested_commands"].append("sudo usermod -aG kvm $USER   # cierra y reabre sesión después")
    return result


def check_storage_path(path: str | Path) -> dict[str, Any]:
    """Comprueba existencia/permisos/espacio de una ruta de almacenamiento.
    Solo sondea (fichero temporal que se borra a sí mismo); NUNCA borra nada
    del usuario."""
    candidate = Path(path).expanduser()
    result: dict[str, Any] = {
        "path": str(candidate),
        "exists": candidate.exists(),
        "is_dir": candidate.is_dir(),
        "writable": False,
        "free_mib": 0,
        "detail": "",
    }
    probe_dir = candidate if candidate.is_dir() else candidate.parent
    if not probe_dir.exists():
        result["detail"] = f"No existe ni la ruta ni su carpeta padre ({probe_dir})."
        return result
    try:
        with tempfile.NamedTemporaryFile(prefix=".hypergery-setup-probe-", dir=probe_dir):
            pass
        result["writable"] = True
    except OSError as exc:
        result["detail"] = f"Sin permiso de escritura: {exc}"
        return result
    try:
        result["free_mib"] = int(shutil.disk_usage(probe_dir).free / (1024 * 1024))
    except OSError:
        pass
    if result["free_mib"] and result["free_mib"] < 10 * 1024:
        result["detail"] = "Aviso: menos de 10 GiB libres; los discos de VM crecen rápido."
    elif not result["exists"]:
        result["detail"] = "La carpeta no existe todavía; se creará al guardar la primera VM."
    else:
        result["detail"] = "Ruta utilizable."
    return result


# --------------------------------------------------------------------------- #
# Bundle Docker del Hub (exportable a NAS / equipo dedicado)                   #
# --------------------------------------------------------------------------- #


def new_hub_token() -> str:
    return secrets.token_urlsafe(32)


_BUNDLE_COMPOSE = """services:
  hypergery-hub:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: hypergery-hub
    ports:
      - "${HYPERGERY_HUB_PORT:-8765}:8765"
    volumes:
      - hypergery-hub-data:/data
      - ${HYPERGERY_NAS_ROOT:-./hypergery-data}:/hypergery
    environment:
      - HYPERGERY_HUB_DB=/data/hypergery-hub.sqlite
      - HYPERGERY_HUB_STAGING=/hypergery/staging
      - HYPERGERY_NAS_ROOT=/hypergery
      # Dentro del contenedor se escucha en 0.0.0.0 a propósito: el alcance
      # real lo decide el mapeo de puertos del host y tu LAN/VPN (ver SECURITY.md).
      - HYPERGERY_HUB_HOST=0.0.0.0
      - HYPERGERY_HUB_PORT=8765
      # v1.2: auth obligatoria. Define el token en .env; si lo dejas vacío, el
      # Hub genera uno y lo persiste en /data/hub_token (léelo con:
      # docker exec hypergery-hub cat /data/hub_token).
      - HYPERGERY_HUB_TOKEN=${HYPERGERY_HUB_TOKEN:-}
    restart: unless-stopped

volumes:
  hypergery-hub-data:
"""

_BUNDLE_DOCKERFILE = """FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY hypergery-ubuntu /app/hypergery-ubuntu

ENV PYTHONPATH=/app/hypergery-ubuntu

RUN mkdir -p /data /hypergery/migrations

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=3).read()"]

CMD ["python", "-m", "hypergery_ubuntu.cli", "hub", "serve", "--host", "0.0.0.0", "--port", "8765"]
"""

_BUNDLE_ENV_EXAMPLE = """# Copia este fichero a `.env` y rellena los valores. NO subas `.env` a git.
HYPERGERY_HUB_PORT=8765
# Carpeta del NAS/host donde el Hub guarda staging de migraciones y datos.
HYPERGERY_NAS_ROOT=./hypergery-data
# Token del Hub (SECRETO). Genera uno con:
#   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
# Si lo dejas vacío, el Hub genera uno propio (ver README_SETUP.md, paso 4).
HYPERGERY_HUB_TOKEN=
"""

_BUNDLE_README = """# HyperGery Hub — despliegue en NAS / equipo dedicado

Este bundle es autocontenido: incluye el código del Hub y todo lo necesario
para levantarlo con Docker en otro equipo (un NAS, un mini-PC…).

## Pasos

1. Copia esta carpeta completa al equipo dedicado, por ejemplo:
   `scp -r hypergery-hub-docker usuario@nas:/share/Contenedores/`
2. En el equipo dedicado: `cp .env.example .env` y edita `.env`
   (puerto, carpeta de datos y token; genera el token con el comando del
   propio fichero).
3. Arranca: `docker compose up -d` (requiere Docker + compose v2).
4. Comprueba: `curl http://127.0.0.1:8765/health` → `{"status": "ok", ...}`.
   Si dejaste el token vacío, recupéralo con:
   `docker exec hypergery-hub cat /data/hub_token`.
5. Vuelve a HyperGery en tu PC: asistente de primera ejecución (o
   `hypergery-cli setup test-hub --url http://IP-DEL-NAS:8765 --token …`),
   pega URL y token, prueba la conexión y guarda. La config queda con
   permisos 0600.

## Notas

- El Hub solo debe ser alcanzable desde tu LAN privada o tu VPN
  (WireGuard/Tailscale). Para exponerlo más allá, TLS por reverse proxy:
  lee SECURITY.md.
- Parar: `docker compose down` (los datos persisten en el volumen
  `hypergery-hub-data` y en la carpeta HYPERGERY_NAS_ROOT).
"""

_BUNDLE_SECURITY = """# Seguridad del Hub en Docker

- **Token obligatorio**: todas las peticiones (salvo GET /health) requieren
  `Authorization: Bearer <token>`. El token es un SECRETO: guárdalo solo en
  `.env` (este bundle) y en `~/.config/hypergery/config.json` (0600) del PC.
- **Alcance de red**: el contenedor escucha en 0.0.0.0 PERO el alcance real lo
  decide el host. Mantén el puerto accesible solo desde tu LAN privada o tu
  VPN (WireGuard/Tailscale). No abras el puerto en el router.
- **Internet**: nunca expongas el Hub sin TLS. Usa un reverse proxy (Caddy,
  nginx, Traefik) con certificado, o mejor: VPN y no lo expongas.
- **Sin evasión**: HyperGery no hace bypass de cortafuegos, ni DNS tunneling,
  ni camufla tráfico. Conexiones legítimas y autenticadas únicamente
  (qemu+ssh, qemu+tls, VPN, SSH autorizado, HTTPS/TLS).
- **Rate limit y auditoría**: los fallos de autenticación se limitan por IP y
  quedan auditados en la base de eventos del Hub.
- **Actualizaciones**: para actualizar el Hub, regenera el bundle desde
  HyperGery y repite `docker compose up -d --build`.
"""


def generate_docker_bundle(dest: str | Path, *, source_root: str | Path | None = None) -> list[Path]:
    """Escribe el bundle exportable del Hub en `dest` y devuelve los ficheros.

    Incluye una copia del paquete `hypergery_ubuntu` (solo .py, sin caches)
    para que el build no dependa del repo. No ejecuta Docker; solo escribe.
    """
    dest_dir = Path(dest).expanduser()
    dest_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for name, content in (
        ("docker-compose.yml", _BUNDLE_COMPOSE),
        ("Dockerfile", _BUNDLE_DOCKERFILE),
        (".env.example", _BUNDLE_ENV_EXAMPLE),
        ("README_SETUP.md", _BUNDLE_README),
        ("SECURITY.md", _BUNDLE_SECURITY),
    ):
        target = dest_dir / name
        target.write_text(content, encoding="utf-8")
        written.append(target)
    package_root = Path(source_root).expanduser() if source_root else Path(__file__).resolve().parent
    package_dest = dest_dir / "hypergery-ubuntu" / "hypergery_ubuntu"
    if package_dest.exists():
        shutil.rmtree(package_dest)
    shutil.copytree(
        package_root,
        package_dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    written.append(package_dest)
    return written


# --------------------------------------------------------------------------- #
# Prueba de conexión al Hub                                                    #
# --------------------------------------------------------------------------- #


def test_hub_connection(url: str, token: str = "", timeout: float = 5.0) -> dict[str, Any]:
    """GET /health (sin auth) + GET /vms (con auth). Estados humanizados:
    ok | auth_error | unreachable | bad_url. Nunca incluye el token en el
    resultado."""
    import urllib.error
    import urllib.request

    base = (url or "").strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        return {"status": "bad_url", "message": "La URL del Hub debe empezar por http:// o https:// (p. ej. http://192.168.1.150:8765)."}

    def _get(path: str, with_token: bool) -> int:
        request = urllib.request.Request(base + path, method="GET")
        if with_token and token:
            request.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status)

    try:
        _get("/health", with_token=False)
    except urllib.error.HTTPError as exc:
        exc.read()
        return {"status": "unreachable", "message": f"El Hub responde pero /health devolvió HTTP {exc.code}."}
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        return {"status": "unreachable", "message": f"No se pudo conectar con {base}: {reason}. ¿Está el Hub arrancado y alcanzable desde esta red?"}

    try:
        _get("/vms", with_token=True)
    except urllib.error.HTTPError as exc:
        exc.read()
        if exc.code in (401, 403):
            return {"status": "auth_error", "message": "El Hub está vivo pero rechazó el token (401/403). Revisa el token de pairing."}
        return {"status": "unreachable", "message": f"El Hub devolvió HTTP {exc.code} en /vms."}
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return {"status": "unreachable", "message": f"Conexión perdida al consultar /vms: {getattr(exc, 'reason', exc)}"}
    return {"status": "ok", "message": "Conexión correcta: el Hub responde y aceptó el token."}
