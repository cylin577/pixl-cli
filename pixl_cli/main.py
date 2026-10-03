import argparse
import os
import sys

from .session import session


def progress_printer(label):
    def progress(offset, total):
        sys.stderr.write(f"\r{label}: {offset}/{total} bytes")
        if offset >= total:
            sys.stderr.write("\n")

    return progress


def cmd_scan(args):
    from .tui import pick_device
    from .store import remember_device

    result = pick_device(timeout=args.timeout)
    if result is None:
        sys.exit(1)
    remember_device(result["name"], result["address"], result["rssi"])
    print(f"selected: {result['name']} ({result['address']}) {result['rssi']} dBm")
    if result["match"]:
        print(f"match:    {result['match']}")


def cmd_info(args):
    info = session.client(args).get_version()
    print(f"version:  {info.version}")
    print(f"ble addr: {info.ble_addr}")


def cmd_disks(args):
    for d in session.client(args).drive_list():
        state = "ok" if d.available else "unavailable"
        print(
            f"{d.label}: {d.name} [{state}] "
            f"total={d.total_size} used={d.used_size} free={d.free_size}"
        )


def cmd_format(args):
    if args.label not in ("E", "I"):
        sys.exit("drive label must be E or I")
    session.client(args).drive_format(args.label)
    print(f"drive {args.label} formatted")


def cmd_ls(args):
    for e in session.client(args).read_dir(args.path):
        kind = "d" if e.is_dir else "-"
        flags = ""
        if e.meta.hide:
            flags += "h"
        if e.meta.readonly:
            flags += "r"
        print(f"{kind}{flags} {e.size:>10} {e.name}"
              + (f"  [{e.meta.notes}]" if e.meta.notes else ""))


def cmd_get(args):
    client = session.client(args)
    data = client.read_file(args.remote)
    dest = args.local or os.path.basename(args.remote.rstrip("/"))
    with open(dest, "wb") as f:
        f.write(data)
    print(f"wrote {len(data)} bytes to {dest}")


def cmd_put(args):
    with open(args.local, "rb") as f:
        data = f.read()
    session.client(args).write_file(args.remote, data, progress_printer("put"))
    print(f"uploaded {len(data)} bytes to {args.remote}")


def cmd_rm(args):
    session.client(args).remove(args.path)
    print(f"removed {args.path}")


def cmd_mkdir(args):
    session.client(args).create_dir(args.path)
    print(f"created {args.path}")


def cmd_mv(args):
    session.client(args).rename(args.old, args.new)
    print(f"renamed {args.old} -> {args.new}")


def cmd_meta(args):
    client = session.client(args)
    entry = client.exists(args.path)
    if entry is None:
        sys.exit(f"not found: {args.path}")
    if args.note is None and not args.hide and not args.readonly and args.head is None:
        print(f"notes:    {entry.meta.notes}")
        print(f"hidden:   {entry.meta.hide}")
        print(f"readonly: {entry.meta.readonly}")
        print(f"amiibo:   {entry.meta.head:08x} {entry.meta.tail:08x}")
        return
    meta = entry.meta
    if args.note is not None:
        meta.notes = args.note
    if args.hide:
        meta.hide = True
    if args.readonly:
        meta.readonly = True
    if args.head is not None:
        meta.head = int(args.head, 16)
    if args.tail is not None:
        meta.tail = int(args.tail, 16)
    client.update_meta(args.path, meta)
    print(f"updated meta for {args.path}")


def cmd_dfu(args):
    client = session.client(args)
    print("device entering DFU mode")
    try:
        client.enter_dfu()
    finally:
        session.reset()


def cmd_amiibolink(args):
    from .amiibolink import AmiiboLinkClient, AmiLoopClient

    modes = {
        "random": C.AMIIBOLINK_MODE_RANDOM,
        "cycle": C.AMIIBOLINK_MODE_CYCLE,
        "ntag": C.AMIIBOLINK_MODE_NTAG,
    }
    loop_modes = {
        "random": C.AMILOOP_MODE_RANDOM,
        "cycle": C.AMILOOP_MODE_CYCLE,
        "ntag": C.AMILOOP_MODE_READ_WRITE,
    }
    versions = {"v1": C.AMIIBOLINK_VER_V1, "v2": C.AMIIBOLINK_VER_V2, "amiiloop": C.AMIIBOLINK_VER_AMILOOP}
    transport = session.transport(args)
    with open(args.file, "rb") as f:
        data = f.read()
    if versions[args.ver] == C.AMIIBOLINK_VER_AMILOOP:
        client = AmiLoopClient(transport)
        client.write_card(data, loop_modes[args.mode], progress_printer("amiibolink"))
    else:
        client = AmiiboLinkClient(transport, versions[args.ver])
        client.write_card(data, modes[args.mode], progress_printer("amiibolink"))
    print("tag written, emulating now")


def cmd_ota(args):
    from .consts import DFU_CP_UUID, DFU_PP_UUID
    from .dfu import SecureDFUClient
    from .transport import BleakSyncTransport
    from .store import remember_device

    transport = BleakSyncTransport(
        address=args.address,
        name=args.name if args.address is None else None,
        timeout=args.timeout,
        tx_uuid=DFU_PP_UUID,
        rx_uuid=DFU_CP_UUID,
    )
    if args.address is None:
        args.name = "pixl dfu"
    transport.name = "pixl dfu"
    sys.stderr.write(f"connecting to pixl dfu at {args.address or '(scan)'} ...\n")
    transport.connect()
    remember_device("pixl dfu", transport.address)
    try:
        dfu = SecureDFUClient(transport)
        dfu.flash_package(args.package, progress_printer("ota"))
        print("OTA complete, device rebooting")
    finally:
        transport.disconnect()


def cmd_mount(args):
    try:
        from .fuse_fs import PixlFS
    except ImportError:
        sys.exit(
            "fuse support requires fusepy and libfuse:\n"
            "  uv tool install --force --editable <cli dir> --with fusepy\n"
            "  (or: uv sync --group dev)"
        )
    if args.path[0] not in ("I", "E") or not args.path.startswith(("I:/", "E:/")):
        sys.exit("device path root must be I:/ or E:/")
    client = session.client(args)
    sys.stderr.write(f"mounting {args.path} at {args.mountpoint} (ctrl-c to unmount)\n")
    fs = PixlFS(client, args.path)
    fs.mount(args.mountpoint, foreground=True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="pixl", description="CLI for Pixl.js (BLE data transfer, VFS, DFU, amiibolink)"
    )
    parser.add_argument("--address", help="BLE MAC address of the device")
    parser.add_argument("--name", default="Pixl.js", help="BLE device name filter (default: Pixl.js)")
    parser.add_argument("--timeout", type=float, default=10.0, help="BLE io timeout in seconds")

    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("scan", help="interactive TUI device search").set_defaults(func=cmd_scan)
    sub.add_parser("info", help="get device version info").set_defaults(func=cmd_info)
    sub.add_parser("disks", help="list disks").set_defaults(func=cmd_disks)

    p = sub.add_parser("format", help="format a disk (E or I)")
    p.add_argument("label")
    p.set_defaults(func=cmd_format)

    p = sub.add_parser("ls", help="list a folder")
    p.add_argument("path", nargs="?", default="E:/")
    p.set_defaults(func=cmd_ls)

    p = sub.add_parser("get", help="download a file")
    p.add_argument("remote")
    p.add_argument("local", nargs="?")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("put", help="upload a file")
    p.add_argument("local")
    p.add_argument("remote")
    p.set_defaults(func=cmd_put)

    p = sub.add_parser("rm", help="delete a file or folder")
    p.add_argument("path")
    p.set_defaults(func=cmd_rm)

    p = sub.add_parser("mkdir", help="create a folder")
    p.add_argument("path")
    p.set_defaults(func=cmd_mkdir)

    p = sub.add_parser("mv", help="rename a file or folder (same drive)")
    p.add_argument("old")
    p.add_argument("new")
    p.set_defaults(func=cmd_mv)

    p = sub.add_parser("meta", help="show/update file meta")
    p.add_argument("path")
    p.add_argument("--note")
    p.add_argument("--hide", action="store_true")
    p.add_argument("--readonly", action="store_true")
    p.add_argument("--head", help="amiibo id head (hex)")
    p.add_argument("--tail", help="amiibo id tail (hex)")
    p.set_defaults(func=cmd_meta)

    sub.add_parser("dfu", help="enter DFU mode").set_defaults(func=cmd_dfu)

    p = sub.add_parser("ota", help="flash an OTA package (.zip) over BLE DFU")
    p.add_argument("package", help="OTA package .zip (or raw .bin)")
    p.set_defaults(func=cmd_ota)

    p = sub.add_parser("amiibolink", help="write an amiibo dump over amiibolink protocol")
    p.add_argument("file", help="amiibo dump .bin file")
    p.add_argument("--mode", choices=["random", "cycle", "ntag"], default="random")
    p.add_argument("--ver", choices=["v1", "v2", "amiiloop"], default="v2")
    p.set_defaults(func=cmd_amiibolink)

    p = sub.add_parser("mount", help="mount device storage as a local drive (FUSE)")
    p.add_argument("path", help="device path root, e.g. E:/")
    p.add_argument("mountpoint")
    p.set_defaults(func=cmd_mount)

    args = parser.parse_args(argv)
    if not getattr(args, "cmd", None):
        from .tui import run_tui

        run_tui(args)
        return
    try:
        args.func(args)
    except KeyboardInterrupt:
        pass
    finally:
        session.reset()


if __name__ == "__main__":
    main()
