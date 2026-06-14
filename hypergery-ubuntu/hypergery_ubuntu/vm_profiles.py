"""Perfiles de creación de VM y preflight de firmware (v1.5 blockers B1/B2).

Lógica pura (sin Qt, sin red): qué firmware/chipset/TPM necesita cada sistema
operativo, qué dependencias del host hacen falta y dónde están los binarios
OVMF/swtpm. La generación del XML vive en ``backend.domain_xml`` y consume
estos perfiles; la UI ofrece los perfiles por nombre.

- **Windows 11** exige UEFI (OVMF), Secure Boot si está disponible y vTPM 2.0
  (swtpm) sobre máquina q35. Sin OVMF o sin swtpm, la creación se RECHAZA con
  un error humano y el comando para instalarlos (nunca un bypass como flujo
  principal).
- **Ubuntu/Linux** usa un perfil recomendado y fiable (virtio, UEFI opcional).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

# Rutas habituales de los firmwares OVMF en Debian/Ubuntu. Se prueban en orden;
# la primera que exista gana. (code, vars) = (binario de firmware, plantilla NVRAM)
OVMF_CODE_CANDIDATES = (
    "/usr/share/OVMF/OVMF_CODE_4M.fd",
    "/usr/share/OVMF/OVMF_CODE.fd",
    "/usr/share/qemu/OVMF_CODE.fd",
)
OVMF_VARS_CANDIDATES = (
    "/usr/share/OVMF/OVMF_VARS_4M.fd",
    "/usr/share/OVMF/OVMF_VARS.fd",
    "/usr/share/qemu/OVMF_VARS.fd",
)
# Variantes con Secure Boot preactivado (claves de Microsoft). Opcionales.
OVMF_CODE_SECBOOT_CANDIDATES = (
    "/usr/share/OVMF/OVMF_CODE_4M.secboot.fd",
    "/usr/share/OVMF/OVMF_CODE.secboot.fd",
)
OVMF_VARS_SECBOOT_CANDIDATES = (
    "/usr/share/OVMF/OVMF_VARS_4M.ms.fd",
    "/usr/share/OVMF/OVMF_VARS.ms.fd",
    "/usr/share/OVMF/OVMF_VARS_4M.secboot.fd",
)


@dataclass(frozen=True)
class VmProfile:
    """Describe cómo construir una VM para un sistema operativo concreto."""

    key: str  # identificador estable (linux, windows11, windows-legacy, other)
    label: str  # texto visible en la UI
    os_type: str  # valor histórico almacenado en metadata (Linux/Windows/Other)
    machine: str = "q35"
    firmware: str = "bios"  # bios | uefi | uefi-secure
    tpm: bool = False
    disk_bus: str = "virtio"
    net_model: str = "virtio"
    video_model: str = "qxl"
    min_ram_mib: int = 512
    min_disk_gb: int = 1
    notes: str = ""


PROFILES: dict[str, VmProfile] = {
    "linux": VmProfile(
        key="linux",
        label="Linux / Ubuntu (recomendado)",
        os_type="Linux",
        firmware="bios",  # default probado: Ubuntu instala en BIOS sin depender de OVMF
        min_ram_mib=2048,
        min_disk_gb=15,
        notes="virtio para disco y red, qxl, q35. Ubuntu 22.04/24.04 instala con esta config.",
    ),
    "linux-uefi": VmProfile(
        key="linux-uefi",
        label="Linux / Ubuntu (UEFI)",
        os_type="Linux",
        firmware="uefi",
        min_ram_mib=2048,
        min_disk_gb=15,
        notes="Igual que el recomendado pero con arranque UEFI (OVMF). Necesita ovmf.",
    ),
    "windows11": VmProfile(
        key="windows11",
        label="Windows 11 (UEFI + Secure Boot + TPM 2.0)",
        os_type="Windows",
        machine="q35",
        firmware="uefi-secure",
        tpm=True,
        # El instalador de Windows NO trae drivers virtio: disco SATA y red
        # e1000 para que vea el disco y la red sin pasos extra.
        disk_bus="sata",
        net_model="e1000",
        min_ram_mib=4096,
        min_disk_gb=64,
        notes="Requisitos de Microsoft: UEFI, Secure Boot y TPM 2.0. Necesita ovmf + swtpm. Disco SATA + red e1000 (sin virtio) para que el instalador los detecte.",
    ),
    "windows-legacy": VmProfile(
        key="windows-legacy",
        label="Windows 10 / 8 (UEFI, sin TPM)",
        os_type="Windows",
        firmware="uefi",
        disk_bus="sata",
        net_model="e1000",
        min_ram_mib=2048,
        min_disk_gb=40,
        notes="Windows 10 y anteriores: UEFI sin el requisito de TPM de Windows 11. Disco SATA + red e1000.",
    ),
    "other": VmProfile(
        key="other",
        label="Otro sistema",
        os_type="Other",
        firmware="bios",
        notes="Perfil genérico BIOS para sistemas no listados.",
    ),
}

DEFAULT_PROFILE = "linux"


def profile_for(key_or_os: str) -> VmProfile:
    """Resuelve un perfil por su clave (linux/windows11/…) o por os_type
    histórico (Linux/Windows/Other). Cae al perfil por defecto si no encaja."""
    value = (key_or_os or "").strip().lower()
    if value in PROFILES:
        return PROFILES[value]
    by_os = {
        "linux": "linux",
        "windows": "windows-legacy",  # por compatibilidad; Win11 se pide explícito
        "otro": "other",
        "other": "other",
    }
    return PROFILES.get(by_os.get(value, ""), PROFILES[DEFAULT_PROFILE])


# --------------------------------------------------------------------------- #
# Resolución de firmware en el host                                            #
# --------------------------------------------------------------------------- #


def _first_existing(candidates: tuple[str, ...]) -> str:
    for path in candidates:
        if Path(path).is_file():
            return path
    return ""


def resolve_ovmf(secure_boot: bool = False) -> dict[str, str]:
    """Devuelve {code, vars, secure_boot} con las rutas OVMF encontradas.

    Para Secure Boot intenta primero las variantes ``.secboot``/``.ms``; si no
    están, cae al OVMF normal con secure_boot=False (la VM sigue siendo UEFI).
    """
    if secure_boot:
        code = _first_existing(OVMF_CODE_SECBOOT_CANDIDATES)
        nvram = _first_existing(OVMF_VARS_SECBOOT_CANDIDATES)
        if code and nvram:
            return {"code": code, "vars": nvram, "secure_boot": "yes"}
    code = _first_existing(OVMF_CODE_CANDIDATES)
    nvram = _first_existing(OVMF_VARS_CANDIDATES)
    return {"code": code, "vars": nvram, "secure_boot": "no"}


def swtpm_available() -> bool:
    return shutil.which("swtpm") is not None


# --------------------------------------------------------------------------- #
# Preflight de dependencias                                                     #
# --------------------------------------------------------------------------- #


@dataclass
class ProfilePreflight:
    ok: bool
    profile_key: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggested_commands: list[str] = field(default_factory=list)
    firmware: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "profile_key": self.profile_key,
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "suggested_commands": list(self.suggested_commands),
            "firmware": dict(self.firmware),
        }


def preflight_profile(profile: VmProfile) -> ProfilePreflight:
    """Comprueba que el host puede crear una VM con este perfil. NUNCA cambia
    nada del sistema: solo mira binarios/ficheros y, si falta algo, devuelve el
    error humano y el comando ``apt install`` sugerido."""
    errors: list[str] = []
    warnings: list[str] = []
    commands: list[str] = []
    firmware: dict[str, str] = {}

    if profile.firmware in {"uefi", "uefi-secure"}:
        want_secure = profile.firmware == "uefi-secure"
        ovmf = resolve_ovmf(secure_boot=want_secure)
        firmware = ovmf
        if not ovmf["code"] or not ovmf["vars"]:
            errors.append(
                f"El perfil «{profile.label}» necesita firmware UEFI (OVMF), que no está "
                "instalado. Las VMs Windows 11 y el arranque UEFI no funcionan sin él."
            )
            commands.append("sudo apt install ovmf")
        elif want_secure and ovmf["secure_boot"] != "yes":
            warnings.append(
                "No se encontró el OVMF con Secure Boot preactivado: la VM será UEFI pero "
                "sin Secure Boot. Para el requisito completo de Windows 11 instala el paquete "
                "ovmf con las variables .ms (Secure Boot)."
            )

    if profile.tpm and not swtpm_available():
        errors.append(
            f"El perfil «{profile.label}» necesita un TPM 2.0 virtual (swtpm), que no está "
            "instalado. Windows 11 no instala sin TPM 2.0."
        )
        commands.append("sudo apt install swtpm swtpm-tools")

    return ProfilePreflight(
        ok=not errors,
        profile_key=profile.key,
        errors=errors,
        warnings=warnings,
        suggested_commands=commands,
        firmware=firmware,
    )


# --------------------------------------------------------------------------- #
# Validación de ISO (B2)                                                        #
# --------------------------------------------------------------------------- #


def validate_iso(iso_path: str) -> dict:
    """Comprobaciones baratas sobre la ISO antes de crear la VM (B2: instalar
    Ubuntu desde la UI debe ser fiable o explicar por qué). Solo lectura."""
    path = Path(iso_path).expanduser()
    result: dict = {"ok": False, "path": str(path), "errors": [], "warnings": []}
    if not path.exists():
        result["errors"].append(f"La ISO no existe: {path}")
        return result
    if not path.is_file():
        result["errors"].append(f"La ruta de la ISO no es un fichero: {path}")
        return result
    try:
        size = path.stat().st_size
    except OSError as exc:
        result["errors"].append(f"No se puede leer la ISO: {exc}")
        return result
    if size < 16 * 1024 * 1024:
        result["warnings"].append(
            f"La ISO es muy pequeña ({size // (1024 * 1024)} MiB); ¿seguro que es una imagen "
            "de instalación arrancable y no un archivo de prueba?"
        )
    if path.suffix.lower() not in {".iso", ".img"}:
        result["warnings"].append(
            f"La extensión «{path.suffix}» no es la típica de una imagen de instalación (.iso)."
        )
    # Firma "CD001" del formato ISO 9660 (offset 0x8001), barata de comprobar.
    try:
        with path.open("rb") as handle:
            handle.seek(0x8001)
            magic = handle.read(5)
        if magic != b"CD001":
            result["warnings"].append(
                "El fichero no tiene la firma ISO 9660 (CD001): podría no ser una ISO arrancable."
            )
    except OSError:
        pass
    result["ok"] = not result["errors"]
    return result
