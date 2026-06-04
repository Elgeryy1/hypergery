import unittest

from hypergery_ubuntu.ui_qt.console_helpers import HOST_KEY_NAME, is_host_key


class ConsoleHelperTests(unittest.TestCase):
    def test_right_ctrl_host_key_helper(self):
        self.assertEqual(HOST_KEY_NAME, "Right Ctrl")
        self.assertTrue(is_host_key(0x01000021, 105))
        self.assertFalse(is_host_key(0x01000020, 105))


if __name__ == "__main__":
    unittest.main()
