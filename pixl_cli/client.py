import struct
from dataclasses import dataclass

from . import consts as C
from .proto import (
    Frame,
    PixlError,
    build_frame,
    build_meta,
    encode_string,
    parse_frame,
    parse_meta,
    validate_path,
)


@dataclass
class Drive:
    status: int
    label: str
    name: str
    total_size: int
    free_size: int

    @property
    def used_size(self):
        return self.total_size - self.free_size

    @property
    def available(self):
        return self.status == 0


@dataclass
class FileEntry:
    name: str
    size: int
    type: int
    meta: "object"

    @property
    def is_dir(self):
        return self.type == C.VFS_TYPE_DIR


@dataclass
class VersionInfo:
    version: str
    ble_addr: str


class PixlClient:
    def __init__(self, transport):
        self.transport = transport

    def _recv_response(self):
        accumulated = b""
        while True:
            frame = parse_frame(self.transport.recv())
            accumulated += frame.data
            if not frame.chunk & C.CHUNK_MORE:
                break
        if frame.status == C.STATUS_UNSUPPORTED:
            raise PixlError(f"cmd {frame.cmd:#04x} not supported by firmware")
        if frame.status != C.STATUS_OK:
            raise PixlError(f"cmd {frame.cmd:#04x} failed with status {frame.status}")
        return Frame(frame.cmd, frame.status, frame.chunk, accumulated)

    def _request(self, cmd, payload=b""):
        self.transport.send(build_frame(cmd, 0, 0, payload))
        return self._recv_response()

    def get_version(self):
        frame = self._request(C.CMD_INFO_VERSION)
        payload = frame.data
        (vlen,) = struct.unpack_from("<H", payload)
        version = payload[2 : 2 + vlen].decode("utf-8")
        pos = 2 + vlen
        ble_addr = ""
        if len(payload) > pos:
            (alen,) = struct.unpack_from("<H", payload, pos)
            ble_addr = payload[pos + 2 : pos + 2 + alen].decode("utf-8")
        return VersionInfo(version, ble_addr)

    def enter_dfu(self):
        self._request(C.CMD_INFO_ENTER_DFU)

    def drive_list(self):
        frame = self._request(C.CMD_VFS_DRIVE_LIST)
        payload = frame.data
        (count,) = struct.unpack_from("<B", payload)
        drives = []
        pos = 1
        for _ in range(count):
            status = payload[pos]
            label = chr(payload[pos + 1])
            (name_len,) = struct.unpack_from("<H", payload, pos + 2)
            name = payload[pos + 4 : pos + 4 + name_len].decode("utf-8")
            total, free = struct.unpack_from("<II", payload, pos + 4 + name_len)
            drives.append(Drive(status, label, name, total, free))
            pos += 12 + name_len
        return drives

    def drive_format(self, label):
        self._request(C.CMD_VFS_DRIVE_FORMAT, label.encode("ascii"))

    def open_file(self, path, flags):
        validate_path(path)
        frame = self._request(
            C.CMD_VFS_FILE_OPEN, encode_string(path) + struct.pack("<I", flags)
        )
        return frame.data[0] if frame.data else 0

    def close_file(self, file_id):
        self._request(C.CMD_VFS_FILE_CLOSE, struct.pack("<B", file_id))

    def write_file(self, path, data, progress=None):
        validate_path(path)
        file_id = self.open_file(path, C.VFS_MODE_TRUNC | C.VFS_MODE_CREATE | C.VFS_MODE_WRITEONLY)
        try:
            total = len(data)
            offset = 0
            index = 0
            if total == 0:
                self.transport.send(
                    build_frame(C.CMD_VFS_FILE_WRITE, 0, 0, struct.pack("<B", file_id))
                )
                self._recv_response()
            while offset < total:
                chunk = data[offset : offset + C.FILE_WRITE_CHUNK]
                last = offset + len(chunk) >= total
                chunk_field = index if last else (index | C.CHUNK_MORE)
                self.transport.send(
                    build_frame(
                        C.CMD_VFS_FILE_WRITE,
                        0,
                        chunk_field,
                        struct.pack("<B", file_id) + chunk,
                    )
                )
                if last:
                    self._recv_response()
                offset += len(chunk)
                index += 1
                if progress:
                    progress(offset, total)
        finally:
            self.close_file(file_id)

    def read_file(self, path):
        validate_path(path)
        file_id = self.open_file(path, C.VFS_MODE_READONLY)
        try:
            return self._request(C.CMD_VFS_FILE_READ, struct.pack("<B", file_id)).data
        finally:
            self.close_file(file_id)

    def read_dir(self, path):
        validate_path(path)
        frame = self._request(C.CMD_VFS_DIR_READ, encode_string(path))
        payload = frame.data
        entries = []
        pos = 0
        while pos < len(payload):
            (name_len,) = struct.unpack_from("<H", payload, pos)
            name = payload[pos + 2 : pos + 2 + name_len].decode("utf-8")
            pos += 2 + name_len
            (size,) = struct.unpack_from("<I", payload, pos)
            pos += 4
            ftype = payload[pos]
            pos += 1
            (meta_len,) = struct.unpack_from("<B", payload, pos)
            pos += 1
            meta = parse_meta(payload[pos : pos + meta_len])
            pos += meta_len
            entries.append(FileEntry(name, size, ftype, meta))
        return entries

    def create_dir(self, path):
        validate_path(path)
        self._request(C.CMD_VFS_DIR_CREATE, encode_string(path))

    def remove(self, path):
        validate_path(path)
        self._request(C.CMD_VFS_REMOVE, encode_string(path))

    def rename(self, old_path, new_path):
        validate_path(old_path)
        validate_path(new_path)
        if old_path[0] != new_path[0]:
            raise PixlError("rename across drives is not supported")
        payload = encode_string(old_path) + encode_string(new_path)
        self._request(C.CMD_VFS_RENAME, payload)

    def update_meta(self, path, meta):
        validate_path(path)
        self._request(C.CMD_VFS_UPDATE_META, encode_string(path) + build_meta(meta))

    def exists(self, path):
        parent = path.rstrip("/")
        if "/" not in parent[3:]:
            parent = path[0] + ":/"
        else:
            parent = parent.rsplit("/", 1)[0]
            if not parent.endswith("/"):
                parent += "/"
        name = path.rstrip("/").rsplit("/", 1)[-1]
        try:
            for entry in self.read_dir(parent):
                if entry.name == name:
                    return entry
            return None
        except PixlError:
            return None
