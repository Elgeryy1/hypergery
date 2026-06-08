"""Tests del validador de ISO del asistente de nueva máquina (VMWizard).

`validate_iso_path` y `humanize_bytes` son funciones puras, pero viven en
`dialogs.py`, que importa PySide6 al cargarse. Por eso el módulo se omite
entero si PySide6 no está instalado, igual que el resto de tests de Qt.
"""

import importlib.util
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

HAS_PYSIDE6 = importlib.util.find_spec("PySide6") is not None

if HAS_PYSIDE6:
    from hypergery_ubuntu.ui_qt.dialogs import (
        ISO_LARGE_BYTES,
        humanize_bytes,
        validate_iso_path,
    )


@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not installed — run inside the project venv")
class ValidateIsoPathTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make_iso(self, name: str, size: int) -> Path:
        path = self.tmp / name
        with open(path, "wb") as fh:
            if size:
                fh.seek(size - 1)
                fh.write(b"\0")
        return path

    # --- vacío / None ---------------------------------------------------- #

    def test_empty_optional_is_ok(self):
        self.assertEqual(validate_iso_path("", required=False), (True, ""))
        self.assertEqual(validate_iso_path(None, required=False), (True, ""))
        self.assertEqual(validate_iso_path("   ", required=False), (True, ""))

    def test_empty_required_is_blocked(self):
        ok, message = validate_iso_path("", required=True)
        self.assertFalse(ok)
        self.assertEqual(message, "Selecciona una imagen ISO")
        self.assertFalse(validate_iso_path(None, required=True)[0])

    # --- ruta inexistente ----------------------------------------------- #

    def test_missing_path_is_blocked(self):
        missing = self.tmp / "no-existe.iso"
        ok, message = validate_iso_path(str(missing))
        self.assertFalse(ok)
        self.assertEqual(message, f"El archivo ISO no existe: {missing}")

    # --- no es un archivo ----------------------------------------------- #

    def test_directory_is_not_a_valid_file(self):
        ok, message = validate_iso_path(str(self.tmp))
        self.assertFalse(ok)
        self.assertEqual(message, "La ruta no es un archivo válido")

    # --- archivo vacío -------------------------------------------------- #

    def test_zero_byte_file_is_blocked(self):
        empty = self._make_iso("vacia.iso", 0)
        ok, message = validate_iso_path(str(empty))
        self.assertFalse(ok)
        self.assertEqual(message, "El archivo ISO está vacío (0 bytes)")

    # --- ISO válida ----------------------------------------------------- #

    def test_small_valid_iso_is_ok_without_warning(self):
        iso = self._make_iso("ubuntu.iso", 4096)
        self.assertEqual(validate_iso_path(str(iso)), (True, ""))

    # --- extensión no .iso (aviso, pero ok) ----------------------------- #

    def test_non_iso_extension_warns_but_is_ok(self):
        other = self._make_iso("instalador.img", 4096)
        ok, message = validate_iso_path(str(other))
        self.assertTrue(ok)
        self.assertEqual(message, "Aviso: el archivo no tiene extensión .iso")

    def test_extension_check_is_case_insensitive(self):
        upper = self._make_iso("UBUNTU.ISO", 4096)
        self.assertEqual(validate_iso_path(str(upper)), (True, ""))

    # --- ISO muy grande (aviso, pero ok) -------------------------------- #

    def test_very_large_iso_warns_but_is_ok(self):
        # No se crea un archivo real de 16 GiB: se valida la rama con un
        # st_size simulado mediante una subclase de Path liviana.
        iso = self._make_iso("enorme.iso", 4096)

        real_stat = os.stat(iso)
        huge = ISO_LARGE_BYTES + 1

        class _FakeStat:
            st_size = huge

            def __getattr__(self, name):
                return getattr(real_stat, name)

        original = Path.stat
        try:
            Path.stat = lambda self, *a, **k: _FakeStat()  # type: ignore[assignment]
            ok, message = validate_iso_path(str(iso))
        finally:
            Path.stat = original  # type: ignore[assignment]

        self.assertTrue(ok)
        self.assertTrue(message.startswith("Aviso: ISO muy grande ("))
        self.assertIn("la creación puede tardar", message)

    def test_expanduser_is_applied_for_existence_check(self):
        # Una ruta con ~ que no existe tras expandir se trata como inexistente.
        # El mensaje muestra la ruta tal y como la escribió el usuario.
        ok, message = validate_iso_path("~/__hypergery_no_existe__.iso")
        self.assertFalse(ok)
        self.assertEqual(message, "El archivo ISO no existe: ~/__hypergery_no_existe__.iso")

    def test_expanduser_resolves_real_home_file(self):
        # Una ISO real bajo ~ debe validar correctamente al expandir la ruta.
        iso = self._make_iso("home-fake.iso", 4096)
        with unittest.mock.patch.object(Path, "expanduser", lambda self: iso):
            self.assertEqual(validate_iso_path("~/home-fake.iso"), (True, ""))


@unittest.skipUnless(HAS_PYSIDE6, "PySide6 not installed — run inside the project venv")
class HumanizeBytesTest(unittest.TestCase):
    def test_bytes_and_units(self):
        self.assertEqual(humanize_bytes(0), "0 bytes")
        self.assertEqual(humanize_bytes(512), "512 bytes")
        self.assertEqual(humanize_bytes(1024), "1 KiB")
        self.assertEqual(humanize_bytes(1536), "1.5 KiB")
        self.assertEqual(humanize_bytes(1024**2), "1 MiB")
        self.assertEqual(humanize_bytes(int(1.5 * 1024**3)), "1.5 GiB")

    def test_invalid_input_is_safe(self):
        self.assertEqual(humanize_bytes(-1), "tamaño desconocido")
        self.assertEqual(humanize_bytes("nope"), "tamaño desconocido")


if __name__ == "__main__":
    unittest.main()
