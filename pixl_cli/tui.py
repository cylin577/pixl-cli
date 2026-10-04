import asyncio
import sys
import threading

from .consts import NUS_SERVICE_UUID

KNOWN_NAMES = {
    "Pixl.js": "Pixl.js app (file transfer)",
    "amiibolink": "AmiiboLink app",
    "pixl dfu": "DFU bootloader",
}


def match_reason(name, service_uuids):
    if not name:
        return None
    reason = KNOWN_NAMES.get(name)
    if reason:
        return reason
    if NUS_SERVICE_UUID in service_uuids:
        return "Nordic UART Service"
    return None


class DeviceScanner:
    def __init__(self, timeout=10.0):
        self.timeout = timeout
        self.devices = {}
        self.version = 0
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._scanner = None
        self._done = threading.Event()

    def _run(self, coro, timeout):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def start(self):
        self._thread.start()
        asyncio.run_coroutine_threadsafe(self._scan(), self._loop)

    async def _scan(self):
        from bleak import BleakScanner

        try:
            self._scanner = BleakScanner(detection_callback=self._on_detect)
            await self._scanner.start()
            await asyncio.sleep(self.timeout)
            await self._scanner.stop()
        finally:
            self._done.set()

    def _on_detect(self, device, advertisement_data):
        name = device.name or advertisement_data.local_name
        prev = self.devices.get(device.address)
        if prev and prev[0] and not name:
            name = prev[0]
        self.devices[device.address] = (
            name,
            device.address,
            advertisement_data.rssi,
            set(advertisement_data.service_uuids or []),
        )
        self.version += 1

    def snapshot(self):
        entries = list(self.devices.values())
        matches = [e for e in entries if match_reason(e[0], e[3])]
        others = [e for e in entries if not match_reason(e[0], e[3])]
        matches.sort(key=lambda e: (-e[2], e[0] or ""))
        others.sort(key=lambda e: (-e[2], e[0] or ""))
        return matches + others

    def stop(self):
        if self._scanner is not None:
            try:
                self._run(self._scanner.stop(), 5.0)
            except Exception:
                pass
            self._scanner = None


def pick_device(timeout=10.0):
    scanner = DeviceScanner(timeout)
    return _pick(scanner)


def _pick(scanner):
    from rich.console import Console
    from rich.live import Live

    console = Console()
    if not console.is_terminal:
        return _pick_fallback(scanner, console)

    from .keys import cbreak_mode, read_key

    selected = None
    cursor = 0
    seen_version = -1
    console.print("[dim]scanning for BLE devices...[/dim]")
    scanner.start()
    with Live(console=console, refresh_per_second=10, transient=True) as live, cbreak_mode():
        while True:
            entries = scanner.snapshot()
            if scanner.version != seen_version:
                seen_version = scanner.version
                cursor = min(cursor, max(0, len(entries) - 1))
                live.update(_table(scanner, entries, cursor))
            key = read_key(0.1)
            if key == "enter" and entries:
                selected = entries[min(cursor, len(entries) - 1)]
                break
            if key in ("esc", "q", "ctrl-c"):
                break
            if key == "up":
                cursor = max(0, cursor - 1)
            if key == "down":
                cursor = min(max(0, len(entries) - 1), cursor + 1)
    scanner.stop()
    if selected is None:
        console.print("[dim]scan cancelled[/dim]")
        return None
    name, address, rssi, uuids = selected
    return {"name": name, "address": address, "rssi": rssi, "match": match_reason(name, uuids)}


def _table(scanner, entries, cursor):
    from rich.table import Table

    table = Table(title="BLE devices — ↑/↓ move, Enter pick, q quit", expand=False)
    table.add_column("")
    table.add_column("Name")
    table.add_column("Address")
    table.add_column("RSSI", justify="right")
    table.add_column("Match")
    for i, (name, address, rssi, uuids) in enumerate(entries):
        reason = match_reason(name, uuids)
        selected = i == cursor
        table.add_row(
            ">" if selected else "",
            (name or "(unknown)") + (" [green]*[/green]" if reason else ""),
            address,
            f"{rssi} dBm",
            reason or "[dim]—[/dim]",
            style="reverse" if selected else None,
        )
    return table


def _pick_fallback(scanner, console):
    console.print("scanning for BLE devices...")
    scanner.start()
    scanner._done.wait(scanner.timeout + 5.0)
    entries = scanner.snapshot()
    scanner.stop()
    for i, (name, address, rssi, uuids) in enumerate(entries):
        reason = match_reason(name, uuids)
        console.print(f"  [cyan][{i + 1}][/cyan] {name or '(unknown)':<20} {rssi:>4} dBm  {reason or ''}")
    try:
        choice = console.input("select device number (blank to cancel): ").strip()
    except EOFError:
        return None
    if not choice.isdigit() or not (1 <= int(choice) <= len(entries)):
        return None
    name, address, rssi, uuids = entries[int(choice) - 1]
    return {"name": name, "address": address, "rssi": rssi, "match": match_reason(name, uuids)}


ACTIONS = [
    ("scan", "search for BLE devices"),
    ("info", "show firmware version + BLE address"),
    ("disks", "list disks"),
    ("ls", "list a folder"),
    ("get", "download a file"),
    ("put", "upload a file"),
    ("mkdir", "create a folder"),
    ("mv", "rename a file or folder"),
    ("rm", "delete a file or folder"),
    ("meta", "show/update file meta"),
    ("format", "format a disk (destructive)"),
    ("update", "download a firmware release, then optionally flash it"),
    ("dfu", "reboot to DFU, then flash OTA package"),
    ("amiibolink", "write an amiibo dump"),
    ("mount", "mount device storage as local drive (FUSE)"),
    ("quit", "exit"),
]

PROMPTS = {
    "ls": [("path", "path", "E:/")],
    "get": [("remote", "device path", ""), ("local", "local file (blank = basename)", "")],
    "put": [("local", "local file", ""), ("remote", "device path", "")],
    "mkdir": [("path", "device path", "")],
    "mv": [("old", "rename from", ""), ("new", "rename to", "")],
    "rm": [("path", "device path", "")],
    "meta": [("path", "device path", "")],
    "format": [("label", "drive letter (E/I)", "E")],
    "amiibolink": [("file", "amiibo dump .bin", "")],
    "mount": [("path", "device path root (I:/ or E:/)", "E:/"), ("mountpoint", "mount point", "")],
}

CONFIRM = ("format", "dfu")


def run_tui(args, timeout=10.0):
    from rich.console import Console

    console = Console()
    if not console.is_terminal:
        sys.exit("interactive TUI requires a terminal; use subcommands, e.g. pixl --help")
    while True:
        cmd = _menu(console)
        if cmd is None or cmd == "quit":
            break
        try:
            _execute_tui(args, cmd, console, timeout)
        except KeyboardInterrupt:
            pass
        console.print()


def _menu(console):
    from rich.live import Live
    from rich.table import Table

    from .keys import cbreak_mode, read_key

    cursor = 0
    console.print("[bold]pixl-cli[/bold] [dim]— ↑/↓ move, Enter pick, q quit[/dim]")
    with Live(console=console, refresh_per_second=10, transient=True) as live, cbreak_mode():
        while True:
            table = Table(expand=False, box=None)
            table.add_column("")
            table.add_column("Command")
            table.add_column("Description")
            for i, (cmd, desc) in enumerate(ACTIONS):
                selected = i == cursor
                table.add_row(
                    ">" if selected else "",
                    cmd,
                    desc,
                    style="reverse" if selected else None,
                )
            live.update(table)
            key = read_key(0.1)
            if key == "enter":
                return ACTIONS[cursor][0]
            if key in ("esc", "q", "ctrl-c"):
                return None
            if key == "up":
                cursor = (cursor - 1) % len(ACTIONS)
            if key == "down":
                cursor = (cursor + 1) % len(ACTIONS)


def select_device_menu(console, timeout=10.0):
    from rich.live import Live
    from rich.table import Table

    from .keys import cbreak_mode, read_key
    from .store import forget_device, load_devices, remember_device

    while True:
        remembered = load_devices()
        cursor = 0
        rows = [("mem", d) for d in remembered] + [("scan", None)]
        picked = None
        forgotten = False
        with Live(console=console, refresh_per_second=10, transient=True) as live, cbreak_mode():
            while True:
                table = Table(
                    title="Select device — Enter pick, x forget, esc back",
                    expand=False,
                    box=None,
                )
                table.add_column("")
                table.add_column("Name")
                table.add_column("Address")
                table.add_column("Info", justify="right")
                for i, (kind, d) in enumerate(rows):
                    selected = i == cursor
                    if kind == "scan":
                        name, addr, info = "[cyan]scan for new devices...[/cyan]", "", ""
                    else:
                        name = d.get("name") or "(unknown)"
                        addr = d.get("address") or ""
                        info = f"{d.get('rssi', '?')} dBm" if d.get("rssi") is not None else ""
                    table.add_row(
                        ">" if selected else "",
                        name,
                        addr,
                        info,
                        style="reverse" if selected else None,
                    )
                live.update(table)
                key = read_key(0.1)
                if key == "enter" and rows:
                    kind, d = rows[cursor]
                    if kind == "scan":
                        result = _pick(DeviceScanner(timeout))
                        if result:
                            remember_device(result["name"], result["address"], result["rssi"])
                            picked = result
                    else:
                        picked = {"name": d.get("name"), "address": d.get("address")}
                    break
                if key in ("x", "X") and rows[cursor][0] == "mem":
                    forget_device(rows[cursor][1].get("address"))
                    forgotten = True
                    break
                if key in ("esc", "q", "ctrl-c"):
                    break
                if key == "up":
                    cursor = (cursor - 1) % len(rows)
                if key == "down":
                    cursor = (cursor + 1) % len(rows)
        if picked is not None:
            return picked
        if not forgotten:
            return None


def choose_index(console, title, labels, default=0):
    """Pick an index from ``labels`` (list of (primary, secondary)).

    Returns the chosen index or None. Falls back to a numbered prompt when the
    console is not an interactive terminal.
    """
    if not labels:
        return None
    if not console.is_terminal:
        for i, (primary, secondary) in enumerate(labels):
            suffix = f"  {secondary}" if secondary else ""
            console.print(f"  [cyan][{i + 1}][/cyan] {primary}{suffix}")
        try:
            choice = console.input(f"{title} [default {default + 1}]: ").strip()
        except EOFError:
            return None
        if not choice:
            return default
        if choice.isdigit() and 1 <= int(choice) <= len(labels):
            return int(choice) - 1
        return None

    from rich.live import Live
    from rich.table import Table

    from .keys import cbreak_mode, read_key

    cursor = min(max(0, default), len(labels) - 1)
    with Live(console=console, refresh_per_second=10, transient=True) as live, cbreak_mode():
        while True:
            table = Table(title=title, expand=False, box=None)
            table.add_column("")
            table.add_column("Name")
            table.add_column("Info")
            for i, (primary, secondary) in enumerate(labels):
                selected = i == cursor
                table.add_row(
                    ">" if selected else "",
                    primary,
                    secondary or "",
                    style="reverse" if selected else None,
                )
            live.update(table)
            key = read_key(0.1)
            if key == "enter":
                return cursor
            if key in ("esc", "q", "ctrl-c"):
                return None
            if key == "up":
                cursor = (cursor - 1) % len(labels)
            if key == "down":
                cursor = (cursor + 1) % len(labels)


def _execute_tui(args, cmd, console, timeout=10.0):
    from types import SimpleNamespace

    from . import main
    from .session import session
    from .store import remember_device

    if cmd == "scan":
        result = _pick(DeviceScanner(timeout))
        if result:
            remember_device(result["name"], result["address"], result["rssi"])
            console.print(f"[green]selected {result['name']} ({result['address']})[/green]")
        return

    if cmd == "update":
        _update_tui(args, console, timeout)
        return

    if cmd == "dfu":
        _dfu_and_ota(args, console, timeout)
        return

    device = select_device_menu(console, timeout)
    if device is None:
        return

    overrides = {"address": device["address"], "timeout": args.timeout}
    for arg_name, label, default in PROMPTS.get(cmd, []):
        value = console.input(f"[bold]{label}[/bold]" + (f" [dim]({default})[/dim]: " if default else ": ")).strip()
        if not value:
            if not default:
                console.print("[dim]cancelled[/dim]")
                return
            value = default
        overrides[arg_name] = value

    if cmd in CONFIRM and console.input(f"[yellow]confirm {cmd}? (y/N)[/yellow]: ").strip().lower() != "y":
        return

    targs = SimpleNamespace(**{**vars(args), **overrides})
    error = []

    def run():
        try:
            handler = getattr(main, f"cmd_{cmd}")
            handler(targs)
            remember_device(targs.name if targs.address is None else None, targs.address)
        except Exception as e:
            error.append(e)
            if not session.is_connected():
                session.reset()


    with console.status(f"[bold]{cmd}..."):
        thread = threading.Thread(target=run)
        thread.start()
        thread.join()
    if error:
        console.print(f"[red]error: {error[0]}[/red]")


def flash_ota_package(args, package, console=None):
    """Reboot the device into DFU, wait for it, then flash ``package``.

    Raises RuntimeError on timeout/failure. Uses a live status when ``console``
    is a terminal, otherwise writes progress to stderr.
    """
    from .consts import DFU_CP_UUID, DFU_PP_UUID
    from .dfu import SecureDFUClient
    from .session import session
    from .store import remember_device
    from .transport import BleakSyncTransport

    def say(message):
        if console is not None:
            console.print(message)
        else:
            sys.stderr.write(message + "\n")

    client = session.client(args)
    address = session.address
    remember_device(None, address)
    say(f"device {address}: rebooting into DFU mode...")
    try:
        client.enter_dfu()
    except Exception:
        pass
    session.reset()

    dfu_addr = _wait_for_dfu_reboot(address, timeout=60.0, console=console)
    if dfu_addr is None:
        raise RuntimeError(f"timeout waiting for pixl dfu at {address}")
    say(f"pixl dfu ready at {dfu_addr}")

    transport = BleakSyncTransport(
        address=dfu_addr, name="pixl dfu", timeout=15.0,
        tx_uuid=DFU_PP_UUID, rx_uuid=DFU_CP_UUID,
    )
    transport.connect()
    try:
        dfu = SecureDFUClient(transport)
        if console is not None and console.is_terminal:
            with console.status("flashing OTA package") as status:
                dfu.flash_package(
                    package,
                    progress=lambda off, total: status.update(f"flashing: {off}/{total} bytes"),
                )
        else:
            dfu.flash_package(package, progress=_stderr_progress("flashing"))
    finally:
        transport.disconnect()


def _stderr_progress(label):
    def progress(offset, total):
        sys.stderr.write(f"\r{label}: {offset}/{total} bytes")
        if total and offset >= total:
            sys.stderr.write("\n")

    return progress


def _dfu_and_ota(args, console, timeout=10.0):
    package = _pick_local_file(console)
    if package is None:
        console.print("[dim]no OTA package selected[/dim]")
        return
    try:
        flash_ota_package(args, package, console=console)
    except Exception as e:
        console.print(f"[red]OTA failed: {e}[/red]")
        return
    console.print(f"[green]OTA complete: {package} flashed, device rebooting[/green]")


def _update_tui(args, console, timeout=10.0):
    from types import SimpleNamespace

    from . import main

    options = SimpleNamespace(**{**vars(args), "repo": None, "tag": None, "board": None})
    ota = main.update_download(options, console, timeout=timeout)
    if ota is None:
        return

    from rich.live import Live
    from rich.table import Table

    from .keys import cbreak_mode, read_key

    labels = [("flash now", "reboot to DFU and flash"), ("later", "just keep the file")]
    rows = labels
    cursor = 0
    choice = None
    with Live(console=console, refresh_per_second=10, transient=True) as live, cbreak_mode():
        while True:
            table = Table(title=f"OTA ready: {ota} — Enter pick", expand=False, box=None)
            table.add_column("")
            table.add_column("Action")
            table.add_column("Info")
            for i, (primary, secondary) in enumerate(rows):
                selected = i == cursor
                table.add_row(
                    ">" if selected else "",
                    primary,
                    secondary,
                    style="reverse" if selected else None,
                )
            live.update(table)
            key = read_key(0.1)
            if key == "enter":
                choice = rows[cursor][0]
                break
            if key in ("esc", "q", "ctrl-c"):
                break
            if key == "up":
                cursor = (cursor - 1) % len(rows)
            if key == "down":
                cursor = (cursor + 1) % len(rows)
    if choice is None:
        return
    if choice == "later":
        console.print(f"[dim]flash later with: pixl ota {ota}[/dim]")
        return

    device = select_device_menu(console, timeout)
    if device is None:
        return
    targs = SimpleNamespace(**{**vars(args), "address": device["address"], "timeout": args.timeout})
    console.print("flashing OTA package ...")
    try:
        flash_ota_package(targs, ota, console=console)
    except Exception as e:
        console.print(f"[red]OTA failed: {e}[/red]")
        return
    console.print("[green]OTA complete, device rebooting[/green]")


def _wait_for_dfu_reboot(address, timeout=60.0, console=None):
    import time as _time

    deadline = _time.monotonic() + timeout
    _time.sleep(2.0)
    while _time.monotonic() < deadline:
        scanner = DeviceScanner(2.0)
        try:
            scanner.start()
            scanner._done.wait(3.0)
            for name, addr, rssi, uuids in scanner.snapshot():
                if addr.upper() == address.upper() and name == "pixl dfu":
                    return addr
        except Exception:
            pass
        finally:
            scanner.stop()
        _time.sleep(1.0)
    return None


def _pick_local_file(console, patterns=("*.zip", "*.bin")):
    import glob
    import os

    files = []
    for pattern in patterns:
        files.extend(glob.glob(pattern))
    files = sorted(set(files))
    from rich.live import Live
    from rich.table import Table

    from .keys import cbreak_mode, read_key

    rows = [("file", f) for f in files] + [("path", None)]
    cursor = 0
    with Live(console=console, refresh_per_second=10, transient=True) as live, cbreak_mode():
        while True:
            table = Table(title="Select OTA package — Enter pick, esc back", expand=False, box=None)
            table.add_column("")
            table.add_column("File")
            table.add_column("Size", justify="right")
            for i, (kind, f) in enumerate(rows):
                selected = i == cursor
                if kind == "path":
                    name, size = "[cyan]enter path manually...[/cyan]", ""
                else:
                    name, size = f, f"{os.path.getsize(f)} B"
                table.add_row(
                    ">" if selected else "",
                    name,
                    size,
                    style="reverse" if selected else None,
                )
            live.update(table)
            key = read_key(0.1)
            if key == "enter" and rows:
                kind, f = rows[cursor]
                if kind == "file":
                    return f
                value = console.input("package path: ").strip()
                if value and os.path.isfile(value):
                    return value
                if value:
                    console.print(f"[red]not a file: {value}[/red]")
                break
            if key in ("esc", "q", "ctrl-c"):
                return None
            if key == "up":
                cursor = (cursor - 1) % len(rows)
            if key == "down":
                cursor = (cursor + 1) % len(rows)
    return None
