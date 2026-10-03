import os
import struct
import sys
import unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tests.conftest import MockTransport, df_device_handler  # noqa: E402
from pixl_cli import consts as C  # noqa: E402
from pixl_cli.client import PixlClient  # noqa: E402
from pixl_cli.proto import (  # noqa: E402
    Meta,
    PixlError,
    build_frame,
    build_meta,
    parse_frame,
    parse_meta,
)


class TestProto(unittest.TestCase):
    def test_frame_roundtrip(self):
        data = build_frame(0x12, 1, 0x8001 | 0x8000, b"\x01\x02")
        frame = parse_frame(data)
        self.assertEqual(frame.cmd, 0x12)
        self.assertEqual(frame.status, 1)
        self.assertEqual(frame.chunk, 0x8001)
        self.assertEqual(frame.data, b"\x01\x02")

    def test_meta_roundtrip(self):
        meta = Meta(notes="hello", hide=True, readonly=True, head=0x04F1914C, tail=0xE2445104)
        parsed = parse_meta(build_meta(meta)[1:])
        self.assertEqual(parsed.notes, "hello")
        self.assertTrue(parsed.hide)
        self.assertTrue(parsed.readonly)
        self.assertEqual(parsed.head, 0x04F1914C)
        self.assertEqual(parsed.tail, 0xE2445104)

    def test_meta_empty(self):
        parsed = parse_meta(build_meta(Meta())[1:])
        self.assertEqual(parsed.notes, "")
        self.assertFalse(parsed.hide)
        self.assertFalse(parsed.readonly)
        self.assertEqual(parsed.head, 0)
        self.assertEqual(parsed.tail, 0)

    def test_meta_tolerates_trailing_zero(self):
        parsed = parse_meta(bytes([2, 0x05, 0x00]))
        self.assertTrue(parsed.hide)

    def test_meta_size_byte_includes_itself(self):
        data = build_meta(Meta(notes="ab"))
        self.assertEqual(data[0], len(data) - 1)

    def test_note_too_long(self):
        with self.assertRaises(PixlError):
            build_meta(Meta(notes="x" * 91))

    def test_validate_path(self):
        from pixl_cli.proto import validate_path

        validate_path("E:/amiibo/mifa.bin")
        validate_path("I:/")
        with self.assertRaises(PixlError):
            validate_path("F:/x.bin")
        with self.assertRaises(PixlError):
            validate_path("E:x.bin")


class TestClient(unittest.TestCase):
    def test_read_file_chunked(self):
        t = MockTransport(df_device_handler)
        client = PixlClient(t)
        data = client.read_file("E:/test.bin")
        self.assertEqual(data, b"A" * 243 + b"B" * 100)

    def test_read_file_sends_open_read_close(self):
        t = MockTransport(df_device_handler)
        client = PixlClient(t)
        client.read_file("E:/test.bin")
        cmds = [parse_frame(f).cmd for f in t.sent]
        self.assertEqual(cmds[0], C.CMD_VFS_FILE_OPEN)
        self.assertIn(C.CMD_VFS_FILE_READ, cmds)
        self.assertEqual(cmds[-1], C.CMD_VFS_FILE_CLOSE)
        open_frame = parse_frame(t.sent[0])
        (path_len,) = struct.unpack_from("<H", open_frame.data)
        self.assertEqual(open_frame.data[2 : 2 + path_len], b"E:/test.bin")
        flags = int.from_bytes(open_frame.data[2 + path_len :], "little")
        self.assertEqual(flags, C.VFS_MODE_READONLY)

    def test_write_file_streaming_chunks(self):
        t = MockTransport(df_device_handler)
        client = PixlClient(t)
        data = b"Z" * 500
        client.write_file("E:/test.bin", data)
        writes = [parse_frame(f) for f in t.sent if parse_frame(f).cmd == C.CMD_VFS_FILE_WRITE]
        self.assertEqual(len(writes), 3)
        self.assertTrue(writes[0].chunk & C.CHUNK_MORE)
        self.assertTrue(writes[1].chunk & C.CHUNK_MORE)
        self.assertFalse(writes[2].chunk & C.CHUNK_MORE)
        self.assertEqual(writes[0].data[1:], b"Z" * 242)
        self.assertEqual(writes[2].data[1:], b"Z" * 16)
        open_frame = parse_frame(t.sent[0])
        (path_len,) = struct.unpack_from("<H", open_frame.data)
        open_flags = int.from_bytes(open_frame.data[2 + path_len :], "little")
        self.assertEqual(open_flags, C.VFS_MODE_TRUNC | C.VFS_MODE_CREATE | C.VFS_MODE_WRITEONLY)

    def test_write_file_progress(self):
        t = MockTransport(df_device_handler)
        client = PixlClient(t)
        calls = []
        client.write_file("E:/test.bin", b"Z" * 500, progress=lambda o, n: calls.append((o, n)))
        self.assertEqual(calls[-1], (500, 500))

    def test_error_raises(self):
        t = MockTransport(lambda sent: [build_frame(C.CMD_VFS_FILE_OPEN, C.STATUS_ERR, 0)])
        client = PixlClient(t)
        with self.assertRaises(PixlError):
            client.read_file("E:/missing.bin")

    def test_unsupported_raises(self):
        t = MockTransport(lambda sent: [build_frame(0x77, C.STATUS_UNSUPPORTED, 0)])
        client = PixlClient(t)
        with self.assertRaises(PixlError):
            client._request(0x77)

    def test_drive_list(self):
        t = MockTransport(df_device_handler)
        client = PixlClient(t)
        drives = client.drive_list()
        self.assertEqual(len(drives), 1)
        self.assertEqual(drives[0].label, "E")
        self.assertEqual(drives[0].name, "External Flash")
        self.assertEqual(drives[0].total_size, 1024 * 1024)
        self.assertEqual(drives[0].free_size, 2048 * 1024)
        self.assertTrue(drives[0].available)


if __name__ == "__main__":
    unittest.main()
