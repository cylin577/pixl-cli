import errno
import os
import stat as stat_mod

from . import consts as C


class PixlFS:
    def __init__(self, client, root):
        from fuse import FUSE, Operations

        class _Ops(Operations):
            pass

        self.client = client
        self.root = root.rstrip("/") + "/"
        self._ops = _Ops()
        self._dirs = {}
        self._write_cache = {}
        self._fuse_cls = FUSE
        self._fuse_ops_cls = _Ops
        self._install_handlers()

    def _dp(self, path):
        return self.root + path.lstrip("/")

    def _install_handlers(self):
        ops = self._ops
        fs = self
        drive = self.root[0]

        def get_entry(path):
            parent, name = os.path.split(path.rstrip("/"))
            if not name:
                return None
            if parent not in fs._dirs:
                try:
                    fs._dirs[parent] = {
                        e.name: e for e in fs.client.read_dir(fs._dp(parent))
                    }
                except Exception:
                    fs._dirs[parent] = {}
            return fs._dirs[parent].get(name)

        def getattr(path, fh=None):
            if path == "/":
                st = {key: 0 for key in self._ST_KEYS}
                st["st_mode"] = stat_mod.S_IFDIR | 0o755
                st["st_nlink"] = 2
                st["st_size"] = 4096
                return st
            entry = get_entry(path)
            if entry is None:
                raise OSError(errno.ENOENT, "not found", path)
            st = {key: 0 for key in self._ST_KEYS}
            if entry.is_dir:
                st["st_mode"] = stat_mod.S_IFDIR | 0o755
                st["st_nlink"] = 2
                st["st_size"] = 4096
            else:
                st["st_mode"] = stat_mod.S_IFREG | 0o644
                st["st_nlink"] = 1
                st["st_size"] = entry.size
            return st

        def readdir(path, fh=None):
            entries = fs.client.read_dir(fs._dp(path))
            fs._dirs[path] = {e.name: e for e in entries}
            return [".", ".."] + [e.name for e in entries]

        def open(path, fh=None):
            entry = get_entry(path)
            if entry is None:
                raise OSError(errno.ENOENT, "not found", path)
            return fh

        def read(path, size, offset, fh=None):
            data = fs.client.read_file(fs._dp(path))
            return data[offset : offset + size]

        def write(path, data, offset, fh=None):
            existing = fs._write_cache.get(path)
            if existing is None:
                entry = get_entry(path)
                if entry is not None and entry.size > 0:
                    existing = fs.client.read_file(fs._dp(path))
                else:
                    existing = b""
            buf = bytearray(existing)
            end = offset + len(data)
            if end > len(buf):
                buf.extend(b"\x00" * (end - len(buf)))
            buf[offset:end] = data
            fs._write_cache[path] = bytes(buf)
            return len(data)

        def flush(path, fh=None):
            return 0

        def release(path, fh=None):
            data = fs._write_cache.pop(path, None)
            if data is not None:
                fs.client.write_file(fs._dp(path), data)
            return 0

        def truncate(path, length, fh=None):
            entry = get_entry(path)
            existing = fs._write_cache.get(path)
            if existing is None:
                existing = (
                    fs.client.read_file(fs._dp(path)) if entry is not None and entry.size else b""
                )
            buf = bytearray(existing[:length])
            if length > len(buf):
                buf.extend(b"\x00" * (length - len(buf)))
            fs._write_cache[path] = bytes(buf)
            return 0

        def unlink(path):
            fs.client.remove(fs._dp(path))
            fs._dirs.pop(os.path.dirname(path), None)

        def rmdir(path):
            fs.client.remove(fs._dp(path))
            fs._dirs.pop(os.path.dirname(path), None)

        def mkdir(path, mode=None):
            fs.client.create_dir(fs._dp(path))
            fs._dirs.pop(os.path.dirname(path), None)

        def rename(old, new):
            old_dp = fs._dp(old)
            new_dp = fs._dp(new)
            if old_dp[0] != new_dp[0]:
                raise OSError(errno.EXDEV, "cross-device rename not supported")
            data = fs._write_cache.pop(old, None)
            if data is not None:
                fs.client.write_file(new_dp, data)
                fs.client.remove(old_dp)
            else:
                fs.client.rename(old_dp, new_dp)
            fs._dirs.pop(os.path.dirname(old), None)
            fs._dirs.pop(os.path.dirname(new), None)

        def getxattr(path, name, position=0):
            if name != "user.pixl.note":
                raise OSError(errno.ENODATA, "no attribute", name)
            entry = get_entry(path)
            if entry is None:
                raise OSError(errno.ENOENT, "not found", path)
            return entry.meta.notes.encode("utf-8")

        def statfs(path):
            drives = fs.client.drive_list()
            drv = next((d for d in drives if d.label == drive), None)
            bsize = 4096
            return {
                "f_bsize": bsize,
                "f_frsize": bsize,
                "f_blocks": (drv.total_size // bsize) if drv else 0,
                "f_bfree": (drv.free_size // bsize) if drv else 0,
                "f_bavail": (drv.free_size // bsize) if drv else 0,
                "f_files": 0,
                "f_ffree": 0,
                "f_namemax": C.MAX_NAME_LEN,
            }

        handlers = {
            "getattr": getattr,
            "readdir": readdir,
            "open": open,
            "read": read,
            "write": write,
            "flush": flush,
            "release": release,
            "truncate": truncate,
            "unlink": unlink,
            "rmdir": rmdir,
            "mkdir": mkdir,
            "rename": rename,
            "getxattr": getxattr,
            "statfs": statfs,
        }
        for name_, fn in handlers.items():
            setattr(ops, name_, fn)

    _ST_KEYS = [
        "st_mode",
        "st_ino",
        "st_dev",
        "st_nlink",
        "st_uid",
        "st_gid",
        "st_size",
        "st_atime",
        "st_mtime",
        "st_ctime",
        "st_atime_ns",
        "st_mtime_ns",
        "st_ctime_ns",
    ]

    def mount(self, mountpoint, foreground=False):
        self._fuse_cls(self._ops(), mountpoint, foreground=foreground, nothreads=True)
