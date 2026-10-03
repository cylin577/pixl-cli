import struct


class PixlError(Exception):
    pass


class Frame:
    __slots__ = ("cmd", "status", "chunk", "data")

    def __init__(self, cmd, status=0, chunk=0, data=b""):
        self.cmd = cmd
        self.status = status
        self.chunk = chunk
        self.data = data

    def __repr__(self):
        return f"Frame(cmd={self.cmd:#04x} status={self.status} chunk={self.chunk:#06x} len={len(self.data)})"


def build_frame(cmd, status=0, chunk=0, data=b""):
    return struct.pack("<BBH", cmd, status, chunk & 0xFFFF) + bytes(data)


def parse_frame(data):
    cmd, status, chunk = struct.unpack_from("<BBH", data)
    return Frame(cmd, status, chunk, data[4:])


def encode_string(s):
    encoded = s.encode("utf-8")
    return struct.pack("<H", len(encoded)) + encoded


def decode_string(data):
    (length,) = struct.unpack_from("<H", data)
    return data[2 : 2 + length].decode("utf-8")


class Meta:
    __slots__ = ("notes", "hide", "readonly", "head", "tail")

    def __init__(self, notes="", hide=False, readonly=False, head=0, tail=0):
        self.notes = notes
        self.hide = hide
        self.readonly = readonly
        self.head = head
        self.tail = tail

    def __repr__(self):
        return f"Meta(notes={self.notes!r} hide={self.hide} readonly={self.readonly} head={self.head:#x} tail={self.tail:#x})"


def parse_meta(data):
    meta = Meta()
    if not data:
        return meta
    pos = 0
    while pos < len(data):
        mtype = data[pos]
        pos += 1
        if mtype == 1:
            (note_len,) = struct.unpack_from("<B", data, pos)
            pos += 1
            meta.notes = data[pos : pos + note_len].decode("utf-8")
            pos += note_len
        elif mtype == 2:
            (flags,) = struct.unpack_from("<B", data, pos)
            pos += 1
            meta.hide = bool(flags & 0x01)
            meta.readonly = bool(flags & 0x04)
        elif mtype == 3:
            meta.head, meta.tail = struct.unpack_from("<II", data, pos)
            pos += 8
        else:
            if mtype == 0:
                continue
            raise PixlError(f"unknown meta type {mtype}")
    return meta


def build_meta(meta):
    body = b""
    if meta.notes:
        encoded = meta.notes.encode("utf-8")
        if len(encoded) > 90:
            raise PixlError("note too long (max 90 utf-8 bytes)")
        body += struct.pack("<BB", 1, len(encoded)) + encoded
    flags = 0
    if meta.hide:
        flags |= 0x01
    if meta.readonly:
        flags |= 0x04
    body += struct.pack("<BB", 2, flags)
    if meta.head or meta.tail:
        body += struct.pack("<BII", 3, meta.head, meta.tail)
    return struct.pack("<B", len(body)) + body


def validate_path(path):
    if len(path) < 3:
        raise PixlError(f"invalid device path: {path!r}")
    if path[0] not in ("I", "E") or path[1] != ":" or path[2] != "/":
        raise PixlError(f"invalid device path (must be I:/... or E:/...): {path!r}")
    if len(path.encode("utf-8")) > 63:
        raise PixlError(f"device path too long (max 63 utf-8 bytes): {path!r}")
    name = path.rstrip("/").rsplit("/", 1)[-1]
    if name and len(name.encode("utf-8")) > 47:
        raise PixlError(f"file name too long (max 47 utf-8 bytes): {name!r}")
