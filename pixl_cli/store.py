import json
import os
import time

STORE_PATH = os.environ.get(
    "PIXL_CLI_STORE",
    os.path.join(os.path.expanduser("~"), ".config", "pixl-cli", "devices.json"),
)


def load_devices():
    try:
        with open(STORE_PATH) as f:
            devices = json.load(f)
        if isinstance(devices, list):
            return devices
    except (OSError, ValueError):
        pass
    return []


def save_devices(devices):
    os.makedirs(os.path.dirname(STORE_PATH), exist_ok=True)
    with open(STORE_PATH, "w") as f:
        json.dump(devices, f, indent=2)


def remember_device(name, address, rssi=None):
    devices = load_devices()
    for d in devices:
        if d.get("address") == address:
            if name:
                d["name"] = name
            if rssi is not None:
                d["rssi"] = rssi
            d["last_seen"] = time.time()
            break
    else:
        devices.append(
            {
                "name": name or "(unknown)",
                "address": address,
                "rssi": rssi,
                "last_seen": time.time(),
            }
        )
    devices.sort(key=lambda d: -d.get("last_seen", 0))
    save_devices(devices)


def forget_device(address):
    devices = [d for d in load_devices() if d.get("address") != address]
    save_devices(devices)
