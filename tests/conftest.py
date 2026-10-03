import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pixl_cli import consts as C  # noqa: E402
from pixl_cli.proto import build_frame, parse_frame  # noqa: E402


class MockTransport:
    def __init__(self, handler=None):
        self.sent = []
        self.rx = []
        self.handler = handler
        self.lock = threading.Lock()

    def connect(self):
        pass

    def disconnect(self):
        pass

    def send(self, data):
        with self.lock:
            self.sent.append(bytes(data))
            if self.handler:
                for response in self.handler(self.sent[-1]):
                    self.rx.append(bytes(response))

    def recv(self, timeout=None):
        with self.lock:
            return self.rx.pop(0)


def df_device_handler(sent):
    frame = parse_frame(sent)
    if frame.cmd == C.CMD_VFS_FILE_OPEN:
        return [build_frame(frame.cmd, 0, 0, b"\x00")]
    if frame.cmd == C.CMD_VFS_FILE_READ:
        data = b"A" * 243 + b"B" * 100
        chunks = [data[0:243], data[243:]]
        responses = []
        for i, chunk in enumerate(chunks):
            last = i == len(chunks) - 1
            responses.append(
                build_frame(frame.cmd, 0, i if last else (i | C.CHUNK_MORE), chunk)
            )
        return responses
    if frame.cmd == C.CMD_VFS_FILE_WRITE:
        if not frame.chunk & C.CHUNK_MORE:
            return [build_frame(frame.cmd, 0, frame.chunk)]
        return []
    if frame.cmd == C.CMD_VFS_FILE_CLOSE:
        return [build_frame(frame.cmd, 0, 0)]
    if frame.cmd in (
        C.CMD_VFS_DRIVE_LIST,
        C.CMD_VFS_DIR_READ,
        C.CMD_VFS_DIR_CREATE,
        C.CMD_VFS_REMOVE,
        C.CMD_VFS_RENAME,
        C.CMD_VFS_UPDATE_META,
    ):
        if frame.cmd == C.CMD_VFS_DRIVE_LIST:
            name = b"External Flash"
            payload = bytes([1, 0, ord("E")])
            payload += len(name).to_bytes(2, "little")
            payload += name
            payload += (1024 * 1024).to_bytes(4, "little")
            payload += (2048 * 1024).to_bytes(4, "little")
            return [build_frame(frame.cmd, 0, 0, payload)]
        if frame.cmd == C.CMD_VFS_DIR_READ:
            name = b"hello.txt"
            payload = len(name).to_bytes(2, "little") + name
            payload += (42).to_bytes(4, "little")
            payload += bytes([C.VFS_TYPE_FILE, 0])
            return [build_frame(frame.cmd, 0, 0, payload)]
        return [build_frame(frame.cmd, 0, 0)]
    return [build_frame(frame.cmd, C.STATUS_UNSUPPORTED)]
