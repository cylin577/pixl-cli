import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pixl_cli.tui import is_dfu_device  # noqa: E402


class TestIsDfuDevice(unittest.TestCase):
    def test_matches_by_name(self):
        self.assertTrue(is_dfu_device("pixl dfu", "AA:BB", None))
        self.assertTrue(is_dfu_device("pixl dfu", "AA:BB", "CC:DD"))

    def test_matches_app_address_after_reboot(self):
        self.assertTrue(is_dfu_device("(unknown)", "AA:BB", "AA:BB"))
        self.assertTrue(is_dfu_device("", "aa:bb", "AA:BB"))

    def test_ignores_still_advertising_app(self):
        self.assertFalse(is_dfu_device("Pixl.js", "AA:BB", "AA:BB"))
        self.assertFalse(is_dfu_device("amiibolink", "AA:BB", "AA:BB"))
        self.assertFalse(is_dfu_device("AmiLoop", "AA:BB", "AA:BB"))

    def test_ignores_unrelated_device(self):
        self.assertFalse(is_dfu_device("SomeSpeaker", "11:22", "AA:BB"))
        self.assertFalse(is_dfu_device(None, "AA:BB", None))


if __name__ == "__main__":
    unittest.main()
