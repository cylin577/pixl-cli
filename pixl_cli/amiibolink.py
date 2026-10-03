import random
import struct

from . import consts as C
from .proto import PixlError

try:
    from Cryptodome.Cipher import AES
except ImportError:
    try:
        from Crypto.Cipher import AES
    except ImportError as e:
        raise ImportError(
            "pycryptodome is required for amiibolink support: pip install pycryptodome"
        ) from e


def _aes_key(key1, key2):
    return C.AES_KEY_PREFIX + bytes([key1, key2])


def _aes_encrypt(key, plaintext):
    cipher = AES.new(key, AES.MODE_ECB)
    padded = plaintext + b"\x00" * (-len(plaintext) % 16)
    return cipher.encrypt(padded)


def _aes_decrypt(key, ciphertext):
    cipher = AES.new(key, AES.MODE_ECB)
    return cipher.decrypt(ciphertext)


class AmiiboLinkClient:
    def __init__(self, transport, version=C.AMIIBOLINK_VER_V2):
        self.transport = transport
        self.version = version
        self.key1 = 0
        self.key2 = 0

    def _send_cmd_v1(self, cmd, payload=b""):
        self.transport.send(struct.pack("<H", cmd) + payload)

    def _send_cmd_v2(self, cmd, payload=b""):
        self.key1 = random.randrange(0x00, 0xFF)
        self.key2 = random.randrange(0x00, 0xFF)
        plaintext = struct.pack("<H", cmd) + payload
        encrypted = _aes_encrypt(_aes_key(self.key1, self.key2), plaintext)
        frame = struct.pack("<BBBB", self.key1, self.key2, len(encrypted), len(plaintext))
        self.transport.send(frame + encrypted)

    def _send_cmd(self, cmd, payload=b""):
        if self.version == C.AMIIBOLINK_VER_V1:
            self._send_cmd_v1(cmd, payload)
        else:
            self._send_cmd_v2(cmd, payload)

    def _recv_v1(self):
        data = self.transport.recv()
        if len(data) < 2:
            raise PixlError(f"amiibolink v1 response too short: {len(data)} bytes")
        return struct.unpack_from("<H", data)[0]

    def _recv_v2(self):
        data = self.transport.recv()
        if len(data) < 4:
            raise PixlError(f"amiibolink v2 response too short: {len(data)} bytes")
        key1, key2, data_len, de_data_len = struct.unpack_from("<BBBB", data)
        key = _aes_key(key1, key2)
        self.key1, self.key2 = key1, key2
        decrypted = _aes_decrypt(key, data[4 : 4 + data_len])
        return struct.unpack_from("<H", decrypted)[0], decrypted[2:de_data_len]

    def _recv(self):
        if self.version == C.AMIIBOLINK_VER_V1:
            return self._recv_v1(), b""
        return self._recv_v2()

    def get_version(self):
        self._send_cmd(0xB2A2)
        cmd, payload = self._recv()
        if cmd != 0xA2B2:
            raise PixlError(f"unexpected amiibolink response {cmd:#06x}")
        (str_len,) = struct.unpack_from("<B", payload)
        ver_str = payload[1 : 1 + str_len].decode("utf-8")
        return ver_str

    def set_mode(self, mode):
        self._send_cmd(0xB1A1, struct.pack("<B", mode))
        cmd, _ = self._recv()
        if cmd != 0xA1B1:
            raise PixlError(f"set mode failed: unexpected response {cmd:#06x}")

    def _write_ntag_chunk(self, chunk, first):
        payload = b"\x00" + struct.pack("<B", len(chunk)) + chunk
        self._send_cmd(0xAADD, payload)
        cmd, _ = self._recv()
        if cmd != 0xDDAA:
            raise PixlError(f"ntag write failed at offset: unexpected response {cmd:#06x}")

    def write_card(self, data, mode=C.AMIIBOLINK_MODE_RANDOM, progress=None):
        total = len(data)
        if total > C.NTAG_215_SIZE:
            raise PixlError(f"dump too large: {total} bytes (max {C.NTAG_215_SIZE})")
        self.set_mode(mode)
        self._send_cmd(0xA0B0)
        cmd, _ = self._recv()
        if cmd != 0xA0B0:
            raise PixlError(f"write prep failed: unexpected response {cmd:#06x}")
        self._send_cmd(0xACAC, struct.pack("<BBBBHH", 0, 4, 0, 0, 0x021C, 0))
        cmd, _ = self._recv()
        if cmd != 0xCACA:
            raise PixlError(f"transfer start failed: unexpected response {cmd:#06x}")
        self._send_cmd(0xABAB, struct.pack("<H", 0x021C))
        cmd, _ = self._recv()
        if cmd != 0xBABA:
            raise PixlError(f"transfer confirm failed: unexpected response {cmd:#06x}")
        chunk_size = 150 if self.version == C.AMIIBOLINK_VER_V1 else 28
        offset = 0
        while offset < total:
            chunk = data[offset : offset + chunk_size]
            self._write_ntag_chunk(chunk, offset == 0)
            offset += len(chunk)
            if progress:
                progress(offset, total)
        self._send_cmd(0xBCBC)
        cmd, _ = self._recv()
        if cmd != 0xCBCB:
            raise PixlError(f"transfer end failed: unexpected response {cmd:#06x}")
        self._send_cmd(0xDDCC)
        cmd, _ = self._recv()
        if cmd != 0xCCDD:
            raise PixlError(f"tag activation failed: unexpected response {cmd:#06x}")


class AmiLoopClient:
    def __init__(self, transport):
        self.transport = transport

    def _build(self, payload):
        body = struct.pack("<B", len(payload)) + payload
        xor = 0
        for b in body:
            xor ^= b
        return b"\x02" + body + bytes([xor & 0xFF, 0x03])

    def _parse(self, data):
        if len(data) < 4 or data[0] != 0x02 or data[-1] != 0x03:
            raise PixlError(f"invalid amiiloop frame: {data.hex()}")
        length = data[1]
        xor = 0
        for b in data[1 : len(data) - 2]:
            xor ^= b
        if xor & 0xFF != data[-2]:
            raise PixlError("amiiloop frame xor mismatch")
        return data[2], data[3 : length + 2]

    def send(self, payload):
        self.transport.send(self._build(payload))

    def recv(self):
        return self._parse(self.transport.recv())

    def get_version(self):
        self.send(struct.pack("<B", C.AMILOOP_FLAG_GET_VERSION))
        flag, payload = self.recv()
        if flag != 0x02:
            raise PixlError("amiiloop get version failed")
        return payload.decode("utf-8").rstrip("\x00")

    def set_mode(self, mode):
        self.send(struct.pack("<BB", C.AMILOOP_FLAG_SET_MODE, mode))
        flag, _ = self.recv()
        if flag != 0x00:
            raise PixlError("amiiloop set mode failed")

    def write_card(self, data, mode=C.AMILOOP_MODE_RANDOM, progress=None):
        total = len(data)
        if total > C.NTAG_215_SIZE:
            raise PixlError(f"dump too large: {total} bytes (max {C.NTAG_215_SIZE})")
        self.set_mode(mode)
        chunk_size = 150
        offset = 0
        index = 0
        while offset < total:
            chunk = data[offset : offset + chunk_size]
            is_end = 1 if offset + len(chunk) >= total else 0
            index += 1
            payload = struct.pack("<BB", C.AMILOOP_FLAG_WRITE_ALL, is_end)
            payload += struct.pack("<B", index)
            payload += chunk
            self.send(payload)
            flag, _ = self.recv()
            if flag != 0x00:
                raise PixlError(f"amiiloop write failed at offset {offset}")
            offset += len(chunk)
            if progress:
                progress(offset, total)
