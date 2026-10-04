import os
import struct
import sys
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pixl_cli import consts as C  # noqa: E402
from pixl_cli.dfu import SecureDFUClient, crc32, parse_package  # noqa: E402
from pixl_cli.proto import PixlError  # noqa: E402


class FakeDFUDevice:
    def __init__(self, init_dat, fw_bin):
        self.init_dat = init_dat
        self.fw_bin = fw_bin
        self.received = bytearray()
        self.received_cmd = bytearray()
        self.written_cp = []
        self.mtu_size = 247
        self.pending = []
        self.execute_count = 0
        self.object_size = 0
        self.state = None
        self.prn_target = None

    def send(self, data):
        if self.state == "cmd":
            self.received_cmd.extend(data)
        elif self.state == "data":
            self.received.extend(data)
            if self.prn_target and len(self.received) % (self.prn_target * 244) == 0:
                self.pending.append(
                    struct.pack(
                        "<BBBII",
                        C.DFU_OP_RESPONSE,
                        C.DFU_OP_CRC_GET,
                        C.DFU_RES_SUCCESS,
                        len(self.received),
                        crc32(self.received),
                    )
                )

    def send_with_response(self, data):
        self.written_cp.append(bytes(data))
        op = data[0]
        if op == C.DFU_OP_OBJECT_SELECT:
            obj = data[1]
            self.state = "cmd" if obj == C.DFU_OBJ_COMMAND else "data"
            recv = self.received_cmd if obj == C.DFU_OBJ_COMMAND else self.received
            self.pending.append(
                struct.pack("<BBBIII", C.DFU_OP_RESPONSE, op, C.DFU_RES_SUCCESS, 244, len(recv), crc32(recv))
            )
        elif op == C.DFU_OP_OBJECT_CREATE:
            self.object_size = struct.unpack_from("<I", data, 2)[0]
            self.pending.append(
                struct.pack("<BBB", C.DFU_OP_RESPONSE, op, C.DFU_RES_SUCCESS)
            )
        elif op == C.DFU_OP_CRC_GET:
            recv = self.received_cmd if self.state == "cmd" else self.received
            self.pending.append(
                struct.pack("<BBBII", C.DFU_OP_RESPONSE, op, C.DFU_RES_SUCCESS, len(recv), crc32(recv))
            )
        elif op == C.DFU_OP_OBJECT_EXECUTE:
            self.execute_count += 1
            if self.state == "cmd" and len(self.received_cmd) >= len(self.init_dat):
                self.state = "data-pending"
            self.pending.append(
                struct.pack("<BBB", C.DFU_OP_RESPONSE, op, C.DFU_RES_SUCCESS)
            )
        elif op == C.DFU_OP_ABORT:
            self.pending.append(struct.pack("<BBB", C.DFU_OP_RESPONSE, op, C.DFU_RES_SUCCESS))
        elif op == C.DFU_OP_RECEIPT_NOTIF_SET:
            self.prn_target = data[1]
            self.pending.append(struct.pack("<BBB", C.DFU_OP_RESPONSE, op, C.DFU_RES_SUCCESS))

    def recv(self, timeout=None):
        import time

        deadline = time.monotonic() + (timeout or 1.0)
        while time.monotonic() < deadline:
            if self.pending:
                return self.pending.pop(0)
            time.sleep(0.01)
        raise TimeoutError("no notification")

    def try_recv(self):
        items = list(self.pending)
        self.pending.clear()
        return items


class TestSecureDFU(unittest.TestCase):
    def test_crc32_known_value(self):
        self.assertEqual(crc32(b"123456789"), 0xCBF43926)
        self.assertEqual(crc32(b""), 0)
        import zlib

        self.assertEqual(crc32(b"123456789"), zlib.crc32(b"123456789") & 0xFFFFFFFF)

    def test_parse_package_zip(self):
        import tempfile

        path = tempfile.mktemp(suffix=".zip")
        try:
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("pixjs_ota_v1.dat", b"INIT")
                z.writestr("pixjs_app_v1.bin", b"FW" * 500)
            dat, bin_data = parse_package(path)
            self.assertEqual(dat, b"INIT")
            self.assertEqual(len(bin_data), 1000)
        finally:
            os.unlink(path)

    def test_parse_package_bin(self):
        import tempfile

        path = tempfile.mktemp(suffix=".bin")
        try:
            with open(path, "wb") as f:
                f.write(b"FW" * 100)
            dat, bin_data = parse_package(path)
            self.assertEqual(dat, b"")
            self.assertEqual(len(bin_data), 200)
        finally:
            os.unlink(path)

    def test_flash_package_flow(self):
        import tempfile

        init_dat = b"\x01\x00" + b"\x00" * 60
        fw_bin = b"F" * 1000
        path = tempfile.mktemp(suffix=".zip")
        try:
            with zipfile.ZipFile(path, "w") as z:
                z.writestr("init.dat", init_dat)
                z.writestr("app.bin", fw_bin)
            device = FakeDFUDevice(init_dat, fw_bin)
            dfu = SecureDFUClient(device)
            dfu.flash_package(path)
        finally:
            os.unlink(path)

        ops = [w[0] for w in device.written_cp]
        self.assertEqual(ops[0], C.DFU_OP_ABORT)
        self.assertIn(C.DFU_OP_RECEIPT_NOTIF_SET, ops)
        prn_write = next(w for w in device.written_cp if w[0] == C.DFU_OP_RECEIPT_NOTIF_SET)
        self.assertEqual(prn_write[1], 0)  # PRN disabled — no racy receipt handling
        self.assertEqual(device.prn_target, 0)
        self.assertEqual(ops.count(C.DFU_OP_OBJECT_EXECUTE), 1 + (len(fw_bin) + 243) // 244)
        self.assertEqual(device.received_cmd, init_dat)
        self.assertEqual(device.received, fw_bin)
        self.assertEqual(ops[-1], C.DFU_OP_OBJECT_EXECUTE)

    def test_error_raises(self):
        init_dat = b"\x01\x00" + b"\x00" * 60
        fw_bin = b"F" * 100
        device = FakeDFUDevice(init_dat, fw_bin)

        def bad_write(data):
            device.written_cp.append(bytes(data))

        dfu = SecureDFUClient(device)
        dfu._notify = lambda op=None, timeout=15.0: (_ for _ in ()).throw(
            PixlError(f"dfu op {op:#04x} failed: result 0x05")
        )
        with self.assertRaises(PixlError):
            dfu.crc_check(0, 0)


if __name__ == "__main__":
    unittest.main()
