# pixl-cli

CLI for [Pixl.js](https://github.com/solosky/pixl.js) over BLE: file transfer, VFS disk operations, DFU, amiibolink and a FUSE mount that exposes device storage as a local drive.

Implements the wire formats documented in `docs/en/05+1-ble_protocol.md` (pixl data-transfer protocol) and `docs/en/05+2-amiibolink_ble.md` (amiibolink), cross-checked against the firmware sources (`fw/application/src/mod/df/`, `fw/application/src/mod/ble/ble_amiibolink.c`) — the firmware is authoritative where docs drift.

## Install

```
uv tool install --editable . --with fusepy   # system-wide, editable, incl. fuse support
uv sync --directory . --group dev            # dev env with pytest + fusepy
uv run --directory . pixl info
```

`pixl mount` additionally needs the libfuse runtime (`libfuse2` package on Debian/Ubuntu).

## Usage

Device is discovered by BLE name (`Pixl.js` by default; `amiibolink` for the amiibolink app, `pixl dfu` for the DFU bootloader). `pixl` with no arguments opens the TUI: pick a remembered device or scan for new ones, then run any command. Remembered devices persist in `~/.config/pixl-cli/devices.json` (`x` forgets, new picks/connects remember). Use `pixl scan` for a standalone TUI search or `--address <MAC>` to pin a specific device.

```
pixl                               # no args → interactive TUI (device picker + all commands)
pixl scan                          # interactive TUI device search
pixl info                          # firmware version + BLE address
pixl disks                         # list disks (I: internal, E: external)
pixl format E                      # format a disk (destructive!)
pixl ls E:/                        # list a folder
pixl ls E:/amiibo
pixl get E:/amiibo/mifa.bin        # download (to ./mifa.bin or a given path)
pixl put mifa.bin E:/amiibo/mifa.bin
pixl mkdir E:/amiibo
pixl mv E:/a.bin E:/b.bin          # rename (same drive)
pixl rm E:/b.bin
pixl meta E:/amiibo/mifa.bin       # show file meta (notes/flags/amiibo id)
pixl meta E:/amiibo/mifa.bin --note "my pick" --hide
pixl dfu                           # reboot into DFU bootloader
pixl ota pixjs_ota_v123.zip        # flash OTA package over BLE (Nordic secure DFU)
pixl update                        # download a firmware release, then optionally flash it
```

The BLE connection is kept alive per session: run several commands against the same device and they reuse one connection (errors/disconnects reset it and the next command reconnects).

### OTA update flow

`pixl dfu` reboots the device into the DFU bootloader; in the TUI, the dfu action then waits for the device to come back as `pixl dfu` on the same MAC, auto-reconnects and opens an OTA package selector (local `.zip`/`.bin`), then flashes it with CRC-validated object transfer (Nordic secure DFU, service `0xFE59`). Standalone: `pixl ota <package.zip> --address <MAC>`.

### Downloading a firmware release

`pixl update` fetches the predefined repo list from
`https://raw.githubusercontent.com/cylin577/pixl-cli/main/pixl_cli/repos.yaml`
(bundled `pixl_cli/repos.yaml` is the offline fallback), lets you pick a repo and
a release tag (latest by default), and asks whether the device has an OLED or LCD
screen. It downloads the matching `*_OLED.zip`/`*_LCD.zip` through the
`ghs.cylin577.fyi` proxy, extracts the inner `pixjs_ota_vX.zip` into
`~/.cache/pixl-cli/releases/<tag>/`, then offers to flash it now (reboot to DFU
and run the normal OTA flow) or later.

```
pixl update                                  # interactive: repo → tag → OLED/LCD → flash?
pixl update --repo solosky/pixl.js           # skip repo picker
pixl update --tag v2.17 --board OLED         # substring tag match + explicit board
pixl update --repo cylin577/pixl.js -y       # download only, no prompts (add --flash to flash)
```

### Mount as local drive

```
pixl mount E:/ ~/pixjs-ext              # foreground; ctrl-c to unmount
ls ~/pixjs-ext/amiibo
cp mifa.bin ~/pixjs-ext/amiibo/
getfattr -n user.pixl.note ~/pixjs-ext/amiibo/mifa.bin   # amiibo remark via xattr
```

`mount` runs in the foreground (ctrl-c to unmount) and creates the mountpoint if
it does not exist. A stale mountpoint left behind by a previous crash is detected
and unmounted automatically; otherwise the command reports it already mounted.

File contents are read from the device once and cached in memory so the kernel
can service partial reads without re-downloading the whole file over BLE. Writes
are buffered and flushed on `release` (when the writing process closes the file),
since the device only supports sequential writes with truncate. Amiibo remarks
stored in file meta are exposed as the `user.pixl.note` extended attribute.

### Amiibolink

Write an NTAG215 dump to a device running the amiibolink app:

```
pixl amiibolink mifa.bin --ver v2 --mode random
pixl amiibolink mifa.bin --ver v1
pixl amiibolink mifa.bin --ver amiiloop
```

`--mode`: `random`, `cycle`, `ntag` (read/write). For the amiibolink app connect with `--name amiibolink`.

## Development

```
uv sync --directory . --group dev
uv run --directory . pytest tests/
```

Protocol layer is transport-injectable; tests use a mock BLE transport and require no hardware.

License: GPL 2.0 (same as the main repo). No Nintendo-licensed assets included.
