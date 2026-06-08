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

LIBVIRT_URI = os.environ.get("HYPERGERY_LIBVIRT_URI", "qemu:///system")


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
    handle = tempfile.NamedTemporaryFile(prefix="hg-preview-", suffix=".ppm", delete=False)
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
