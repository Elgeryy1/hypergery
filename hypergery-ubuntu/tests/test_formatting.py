import unittest

from hypergery_ubuntu.ui_qt.formatting import format_mib, format_size, os_icon_key


class FormatSizeTests(unittest.TestCase):
    def test_none_returns_zero_bytes(self):
        self.assertEqual(format_size(None), "0 B")

    def test_zero_returns_zero_bytes(self):
        self.assertEqual(format_size(0), "0 B")

    def test_bytes_below_one_kib(self):
        self.assertEqual(format_size(512), "512 B")
        self.assertEqual(format_size(1023), "1023 B")

    def test_kib_boundary(self):
        self.assertEqual(format_size(1024), "1.0 KiB")
        self.assertEqual(format_size(4096), "4.0 KiB")
        self.assertEqual(format_size(1536), "1.5 KiB")

    def test_mib_boundary(self):
        self.assertEqual(format_size(1024 * 1024), "1.0 MiB")
        self.assertEqual(format_size(int(2.5 * 1024 * 1024)), "2.5 MiB")

    def test_gib_boundary(self):
        self.assertEqual(format_size(1024 ** 3), "1.0 GiB")
        self.assertEqual(format_size(40 * 1024 ** 3), "40.0 GiB")

    def test_tib_boundary(self):
        self.assertEqual(format_size(1024 ** 4), "1.0 TiB")
        # Very large values stay in TiB rather than overflowing the units.
        self.assertEqual(format_size(5 * 1024 ** 4), "5.0 TiB")

    def test_float_input(self):
        self.assertEqual(format_size(4096.0), "4.0 KiB")


class FormatMibTests(unittest.TestCase):
    def test_none_is_unknown(self):
        self.assertEqual(format_mib(None), "desconocido")

    def test_zero_is_unknown(self):
        self.assertEqual(format_mib(0), "desconocido")

    def test_value(self):
        self.assertEqual(format_mib(2048), "2048 MiB")
        self.assertEqual(format_mib(512), "512 MiB")


class OsIconKeyTests(unittest.TestCase):
    def test_ubuntu(self):
        self.assertEqual(os_icon_key("ubuntu-srv"), "ubuntu")
        self.assertEqual(os_icon_key("My Ubuntu Box"), "ubuntu")

    def test_debian(self):
        self.assertEqual(os_icon_key("debian-12"), "debian")
        self.assertEqual(os_icon_key("box", "Debian GNU/Linux"), "debian")

    def test_fedora(self):
        self.assertEqual(os_icon_key("fedora-workstation"), "fedora")

    def test_centos(self):
        self.assertEqual(os_icon_key("centos-stream"), "centos")
        self.assertEqual(os_icon_key("rhel9"), "centos")
        self.assertEqual(os_icon_key("rocky-linux"), "centos")

    def test_arch(self):
        self.assertEqual(os_icon_key("archlinux"), "arch")
        self.assertEqual(os_icon_key("manjaro-kde"), "arch")

    def test_windows(self):
        self.assertEqual(os_icon_key("win11"), "windows")
        self.assertEqual(os_icon_key("Windows Server 2022"), "windows")

    def test_linux_generic_distro(self):
        self.assertEqual(os_icon_key("box", "Generic Linux 6.1"), "linux")

    def test_generic_unknown(self):
        self.assertEqual(os_icon_key("mystery-box"), "generic")
        self.assertEqual(os_icon_key(None), "generic")
        self.assertEqual(os_icon_key(""), "generic")
        self.assertEqual(os_icon_key(None, None), "generic")

    def test_case_insensitive(self):
        self.assertEqual(os_icon_key("UBUNTU-SERVER"), "ubuntu")
        self.assertEqual(os_icon_key("WiN10"), "windows")

    def test_os_hint_combined_with_name(self):
        # Name is generic but the OS hint disambiguates.
        self.assertEqual(os_icon_key("vm-001", "Fedora 39"), "fedora")


if __name__ == "__main__":
    unittest.main()
