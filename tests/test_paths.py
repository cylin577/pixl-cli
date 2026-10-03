import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pixl_cli import proto  # noqa: E402
from pixl_cli.client import PixlClient  # noqa: E402
from pixl_cli.proto import parse_frame  # noqa: E402
from tests.conftest import MockTransport, df_device_handler  # noqa: E402


class TestPathPrefix(unittest.TestCase):
    def _last_payload_path(self, client, path, op):
        client.read_dir(path) if op == "dir" else None
        return None

    def test_dir_read_sends_length_prefix(self):
        t = MockTransport(df_device_handler)
        client = PixlClient(t)
        client.read_dir("E:/")
        frame = parse_frame(t.sent[0])
        (plen,) = struct.unpack_from("<H", frame.data)
        self.assertEqual(frame.data[2 : 2 + plen], b"E:/")

    def test_create_dir_sends_length_prefix(self):
        t = MockTransport(df_device_handler)
        client = PixlClient(t)
        client.create_dir("E:/dir")
        frame = parse_frame(t.sent[-1])
        (plen,) = struct.unpack_from("<H", frame.data)
        self.assertEqual(frame.data[2 : 2 + plen], b"E:/dir")

    def test_remove_sends_length_prefix(self):
        t = MockTransport(df_device_handler)
        client = PixlClient(t)
        client.remove("E:/dir")
        frame = parse_frame(t.sent[-1])
        (plen,) = struct.unpack_from("<H", frame.data)
        self.assertEqual(frame.data[2 : 2 + plen], b"E:/dir")

    def test_update_meta_sends_length_prefix(self):
        t = MockTransport(df_device_handler)
        client = PixlClient(t)
        client.update_meta("E:/a.bin", proto.Meta(notes="x"))
        frame = parse_frame(t.sent[-1])
        (plen,) = struct.unpack_from("<H", frame.data)
        self.assertEqual(frame.data[2 : 2 + plen], b"E:/a.bin")

    def test_open_file_sends_length_prefix(self):
        t = MockTransport(df_device_handler)
        client = PixlClient(t)
        client.read_file("E:/a.bin")
        frame = parse_frame(t.sent[0])
        (plen,) = struct.unpack_from("<H", frame.data)
        self.assertEqual(frame.data[2 : 2 + plen], b"E:/a.bin")

    def test_rename_sends_length_prefix(self):
        t = MockTransport(df_device_handler)
        client = PixlClient(t)
        client.rename("E:/a.bin", "E:/b.bin")
        frame = parse_frame(t.sent[-1])
        (plen,) = struct.unpack_from("<H", frame.data)
        self.assertEqual(frame.data[2 : 2 + plen], b"E:/a.bin")
