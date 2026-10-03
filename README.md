# pixl-cli

CLI for [Pixl.js](https://github.com/solosky/pixl.js) over BLE: file transfer, VFS disk operations, DFU, amiibolink and a FUSE mount that exposes device storage as a local drive.

Implements the wire formats documented in `docs/en/05+1-ble_protocol.md` (pixl data-transfer protocol) and `docs/en/05+2-amiibolink_ble.md` (amiibolink), cross-checked against the firmware sources (`fw/application/src/mod/df/`, `fw/application/src/mod/ble/ble_amiibolink.c`) — the firmware is authoritative where docs drift.

## Install

```
uv sync --directory cli/            # core (bleak + pycryptodome)
uv sync --directory "cli/" --extra fuse   # + fusepy for `pixl mount`
uv run --directory cli/ pixl info
```

`pixl mount` additionally needs the libfuse runtime (`libfuse2` package on Debian/Ubuntu).

## Usage

Device is discovered by BLE name (`Pixl.js` by default; `amiibolink` for the amiibolink app). Use `--address <MAC>` to pin a specific device.

```
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
```

### Mount as local drive

```
pixl mount E:/ ~/pixjs-ext
ls ~/pixjs-ext/amiibo
cp mifa.bin ~/pixjs-ext/amiibo/
getfattr -n user.pixl.note ~/pixjs-ext/amiibo/mifa.bin   # amiibo remark via xattr
```

Reads are streamed with chunked transfer; writes are buffered and flushed on `release` (when the writing process closes the file), since the device only supports sequential writes with truncate. Amiibo remarks stored in file meta are exposed as the `user.pixl.note` extended attribute.

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
uv sync --directory cli/ --group dev
uv run --directory cli/ pytest tests/
```

Protocol layer is transport-injectable; tests use a mock BLE transport and require no hardware.

License: GPL 2.0 (same as the main repo). No Nintendo-licensed assets included.
