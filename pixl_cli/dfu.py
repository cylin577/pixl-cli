import struct
import zipfile
import zlib

from . import consts as C
from .proto import PixlError


def crc32(data):
    return zlib.crc32(data) & 0xFFFFFFFF


def parse_package(path):
    if path.lower().endswith(".bin"):
        with open(path, "rb") as f:
            return b"", f.read()
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        dat = next((n for n in names if n.lower().endswith(".dat")), None)
        bin_name = next((n for n in names if n.lower().endswith(".bin")), None)
        if dat is None or bin_name is None:
            raise PixlError(f"package {path!r} is missing .dat or .bin entry")
        return z.read(dat), z.read(bin_name)


class SecureDFUClient:
    def __init__(self, transport):
        self.transport = transport

    def _notify(self, op=None, timeout=15.0):
        while True:
            data = self.transport.recv(timeout)
            opcode = data[0]
            if opcode != C.DFU_OP_RESPONSE:
                continue
            if op is not None and data[1] != op:
                continue
            result = data[2]
            if result == 0x0B and len(data) > 3:
                raise PixlError(f"dfu op {op:#04x} failed: extended error {data[3]}")
            if result != C.DFU_RES_SUCCESS:
                raise PixlError(f"dfu op {op:#04x} failed: result {result:#04x}")
            return data

    def _control_write(self, payload):
        self.transport.send_with_response(bytes(payload))

    def abort(self):
        self._control_write([C.DFU_OP_ABORT])
        self._notify(C.DFU_OP_ABORT)

    def set_prn(self, target):
        self._control_write([C.DFU_OP_RECEIPT_NOTIF_SET, target & 0xFF, (target >> 8) & 0xFF])
        self._notify(C.DFU_OP_RECEIPT_NOTIF_SET)

    def select_object(self, obj_type):
        self._control_write([C.DFU_OP_OBJECT_SELECT, obj_type])
        data = self._notify(C.DFU_OP_OBJECT_SELECT)
        max_size, offset, crc = struct.unpack_from("<III", data, 3)
        return max_size, offset, crc

    def create_object(self, obj_type, size):
        self._control_write([C.DFU_OP_OBJECT_CREATE, obj_type] + list(struct.pack("<I", size)))
        self._notify(C.DFU_OP_OBJECT_CREATE)

    def write_object(self, data, progress=None):
        chunk_len = max(20, self.transport.mtu_size - 3)
        offset = 0
        total = len(data)
        while offset < total:
            chunk = data[offset : offset + chunk_len]
            self.transport.send(chunk)
            offset += len(chunk)
            if progress:
                progress(offset, total)

    def crc_check(self, offset, crc):
        self._control_write([C.DFU_OP_CRC_GET])
        data = self._notify(C.DFU_OP_CRC_GET)
        remote_offset, remote_crc = struct.unpack_from("<II", data, 3)
        if remote_offset != offset or remote_crc != crc:
            raise PixlError(
                f"crc mismatch: remote {remote_offset}/{remote_crc:#06x} != local {offset}/{crc:#06x}"
            )

    def execute_object(self):
        self._control_write([C.DFU_OP_OBJECT_EXECUTE])
        self._notify(C.DFU_OP_OBJECT_EXECUTE)

    def flash_package(self, package, progress=None):
        init_dat, fw_bin = parse_package(package)
        try:
            self.abort()
        except (PixlError, TimeoutError):
            pass
        # PRN disabled: receipt notifications arrive asynchronously while
        # write_gatt_char(response=False) already returns, so consuming them
        # against a local offset is inherently racy. Integrity is enforced by
        # crc_check() + execute_object() per object instead (same as nRF Connect).
        self.set_prn(0)
        self.select_object(C.DFU_OBJ_COMMAND)
        self.create_object(C.DFU_OBJ_COMMAND, len(init_dat))
        self.write_object(init_dat)
        self.crc_check(len(init_dat), crc32(init_dat))
        self.execute_object()

        max_size, offset, _ = self.select_object(C.DFU_OBJ_DATA)
        if offset and progress:
            progress(offset, len(fw_bin))
        pos = offset
        done = offset
        while pos < len(fw_bin):
            size = min(max_size, len(fw_bin) - pos)
            self.create_object(C.DFU_OBJ_DATA, size)
            base = done

            def obj_progress(off, total, base=base):
                if progress:
                    progress(base + off, len(fw_bin))

            self.write_object(fw_bin[pos : pos + size], obj_progress)
            done = pos + size
            self.crc_check(done, crc32(fw_bin[:done]))
            self.execute_object()
            pos += size
        if progress:
            progress(len(fw_bin), len(fw_bin))
