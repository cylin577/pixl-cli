import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pixl_cli import consts as C  # noqa: E402
from pixl_cli.amiibolink import (  # noqa: E402
    AmiiboLinkClient,
    AmiLoopClient,
    _aes_decrypt,
    _aes_key,
)
from pixl_cli.proto import PixlError  # noqa: E402


def make_link_data(key1, key2, plaintext):
    encrypted = _aes_encrypt_stub(key1, key2, plaintext)
    return struct.pack("<BBBB", key1, key2, len(encrypted), len(plaintext)) + encrypted


def _aes_encrypt_stub(key1, key2, plaintext):
    from pixl_cli.amiibolink import _aes_encrypt

    return _aes_encrypt(_aes_key(key1, key2), plaintext)


class TestAmiiboLinkV2(unittest.TestCase):
    def test_key_prefix_matches_firmware(self):
        self.assertEqual(
            _aes_key(0x11, 0x22),
            bytes([0x4B, 0x47, 0x46, 0x5F, 0x41, 0x4D, 0x49, 0x4C, 0x07, 0xE7, 0x04, 0x06, 0x0A, 0x2A, 0x11, 0x22]),
        )

    def test_write_card_sequence(self):
        seen = []

        def handler(sent):
            key1, key2, dl, ddl = struct.unpack_from("<BBBB", sent)
            plaintext = _aes_decrypt(_aes_key(key1, key2), sent[4 : 4 + dl])
            cmd = struct.unpack_from("<H", plaintext)[0]
            seen.append(cmd)
            resp_plain = {0xB1A1: 0xA1B1, 0xA0B0: 0xA0B0, 0xACAC: 0xCACA, 0xABAB: 0xBABA,
                          0xAADD: 0xDDAA, 0xBCBC: 0xCBCB, 0xDDCC: 0xCCDD}[cmd]
            return [make_link_data(key1, key2, struct.pack("<H", resp_plain))]

        class T:
            def __init__(self, h):
                self.handler = h
                self.sent = []
                self.rx = []
            def connect(self):
                pass
            def disconnect(self):
                pass
            def send(self, data):
                self.sent.append(bytes(data))
                self.rx.extend(self.handler(self.sent[-1]))
            def recv(self, timeout=None):
                return self.rx.pop(0)

        t = T(handler)
        client = AmiiboLinkClient(t, version=C.AMIIBOLINK_VER_V2)
        data = b"\x04\x51\x91\x4c" * 135  # 540 bytes
        client.write_card(data)
        self.assertEqual(seen[0], 0xB1A1)
        self.assertEqual(seen[1], 0xA0B0)
        self.assertEqual(seen[2], 0xACAC)
        self.assertEqual(seen[3], 0xABAB)
        self.assertEqual(seen.count(0xAADD), 540 // 28 + 1)
        self.assertEqual(seen[-2], 0xBCBC)
        self.assertEqual(seen[-1], 0xDDCC)

    def test_dump_too_large(self):
        class T:
            def connect(self):
                pass
            def disconnect(self):
                pass
            def send(self, data):
                pass
            def recv(self, timeout=None):
                raise AssertionError("should not be called")

        client = AmiiboLinkClient(T(), version=C.AMIIBOLINK_VER_V2)
        with self.assertRaises(PixlError):
            client.write_card(b"\x00" * 541)


class TestAmiLoop(unittest.TestCase):
    def test_frame_roundtrip(self):
        client = AmiLoopClient(None)
        frame = client._build(struct.pack("<BBB", 0x87, 1, 1) + b"DATA")
        flag, payload = client._parse(frame)
        self.assertEqual(flag, 0x87)
        self.assertEqual(payload, struct.pack("<BB", 1, 1) + b"DATA")

    def test_write_card_flow(self):
        seen = []

        def handler(sent):
            flag = sent[2]
            seen.append(flag)
            if flag == C.AMILOOP_FLAG_SET_MODE:
                return [client_frame(sent, 0x00)]
            if flag == C.AMILOOP_FLAG_WRITE_ALL:
                return [client_frame(sent, 0x00)]

        def client_frame(sent, status):
            body = struct.pack("<B", 1) + bytes([status])
            xor = 0
            for b in body:
                xor ^= b
            return b"\x02" + body + bytes([xor & 0xFF, 0x03])

        class T:
            def __init__(self, h):
                self.handler = h
                self.rx = []
            def connect(self):
                pass
            def disconnect(self):
                pass
            def send(self, data):
                self.rx.extend(self.handler(bytes(data)))
            def recv(self, timeout=None):
                return self.rx.pop(0)

        t = T(handler)
        client = AmiLoopClient(t)
        client.write_card(b"\x04\x51\x91\x4c" * 135)
        self.assertEqual(seen[0], C.AMILOOP_FLAG_SET_MODE)
        self.assertEqual(seen.count(C.AMILOOP_FLAG_WRITE_ALL), 540 // 150 + 1)


if __name__ == "__main__":
    unittest.main()
