import os
import sys
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pixl_cli.session import Session  # noqa: E402


class FakeTransport:
    address = "AA:BB:CC:DD:EE:FF"
    _connected = True

    def connect(self):
        pass

    def disconnect(self):
        self._connected = False


class TestSession(unittest.TestCase):
    def test_reuses_single_connection(self):
        from unittest import mock

        with mock.patch("pixl_cli.session.BleakSyncTransport", return_value=FakeTransport()):
            with mock.patch("pixl_cli.session.remember_device"):
                s = Session()
                c1 = s.client(SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name="Pixl.js", timeout=1.0))
                c2 = s.client(SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name="Pixl.js", timeout=1.0))
                self.assertIs(c1, c2)
                self.assertIs(s.transport(SimpleNamespace(address=None)), s._transport)
                self.assertIs(s.transport(), s._transport)
                s.reset()
                self.assertFalse(s.is_connected())

    def test_reset_allows_reconnect(self):
        from unittest import mock

        fake = FakeTransport()
        with mock.patch("pixl_cli.session.BleakSyncTransport", return_value=fake):
            with mock.patch("pixl_cli.session.remember_device"):
                s = Session()
                s.client(SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name="Pixl.js", timeout=1.0))
                s.reset()
                c2 = s.client(SimpleNamespace(address="AA:BB:CC:DD:EE:FF", name="Pixl.js", timeout=1.0))
                self.assertIsNotNone(c2)


if __name__ == "__main__":
    unittest.main()
