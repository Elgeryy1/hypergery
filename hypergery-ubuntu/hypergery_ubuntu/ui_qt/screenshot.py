from __future__ import annotations

"""Captura de pantalla real de una VM para la previsualización.

Usa ``virsh screenshot`` (mismo canal que el resto del backend, ``qemu:///system``)
para obtener un fotograma del framebuffer del invitado. Es **de solo lectura**:
no enciende, apaga ni modifica la máquina. Solo funciona con la VM encendida y
con un dispositivo gráfico activo; en cualquier otro caso devuelve ``None`` y la
interfaz muestra el marcador de posición (pantalla negra con el nombre).
"""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

LIBVIRT_URI = os.environ.get("HYPERGERY_LIBVIRT_URI", "qemu:///system")

# HG-BUG-0019: los fotogramas del invitado se escriben bajo XDG_RUNTIME_DIR
# (tmpfs por usuario, 0700) en vez de /tmp, y al arrancar se barren los restos
# de un proceso anterior muerto por SIGKILL.
_PREVIEW_PREFIX = "hg-preview-"


def _preview_dir() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    base = Path(runtime) if runtime and Path(runtime).is_dir() else Path(tempfile.gettempdir())
    target = base / "hypergery-previews"
    try:
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
        target.chmod(0o700)
        return target
    except OSError:
        return Path(tempfile.gettempdir())


def cleanup_stale_previews() -> int:
    """Borra capturas dejadas por procesos muertos. Devuelve cuántas quitó."""
    removed = 0
    for leftover in _preview_dir().glob(f"{_PREVIEW_PREFIX}*"):
        try:
            leftover.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def capture_vm_screenshot(
    name: str,
    *,
    uri: str = LIBVIRT_URI,
    timeout: float = 8.0,
    runner=subprocess.run,
) -> bytes | None:
    """Devuelve los bytes de imagen de la pantalla de ``name`` o ``None``.

    El fichero que escribe ``virsh`` suele ser PPM (Qt lo carga sin extensión
    concreta porque detecta el formato por el contenido). Nunca lanza: ante
    cualquier fallo (VM apagada, sin gráficos, virsh ausente) devuelve ``None``.
    """
    if not name or shutil.which("virsh") is None:
        return None
    handle = tempfile.NamedTemporaryFile(
        prefix=_PREVIEW_PREFIX, suffix=".ppm", dir=str(_preview_dir()), delete=False
    )
    tmp_path = handle.name
    handle.close()
    try:
        result = runner(
            ["virsh", "--connect", uri, "screenshot", name, tmp_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if getattr(result, "returncode", 1) != 0:
            return None
        with open(tmp_path, "rb") as fh:
            data = fh.read()
        return data or None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
