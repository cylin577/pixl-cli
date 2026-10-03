import asyncio
import threading
import time
from collections import deque

try:
    from bleak import BleakClient, BleakScanner
except ImportError as e:
    raise ImportError("bleak is required for BLE transport: uv sync") from e

from .consts import (
    DFU_CP_UUID,
    DFU_PP_UUID,
    NUS_CHAR_RX_UUID,
    NUS_CHAR_TX_UUID,
    NUS_SERVICE_UUID,
)


class BleakSyncTransport:
    def __init__(self, address=None, name=None, timeout=10.0, tx_uuid=None, rx_uuid=None):
        self.address = address
        self.name = name
        self.timeout = timeout
        self.tx_uuid = tx_uuid or NUS_CHAR_TX_UUID
        self.rx_uuid = rx_uuid or NUS_CHAR_RX_UUID
        self.mtu_size = 247
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._client = None
        self._queue = deque()
        self._lock = threading.Lock()
        self._connected = False
        self._disconnected = False

    def _run(self, coro, timeout=None):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def connect(self):
        self._thread.start()
        self._run(self._connect(), self.timeout + 30.0)

    async def _connect(self):
        with self._lock:
            self._queue.clear()
            self._disconnected = False
        address = self.address
        if not address:
            devices = await BleakScanner.discover(
                service_uuids=[NUS_SERVICE_UUID], timeout=self.timeout
            )
            named = [d for d in devices if self.name and d.name == self.name]
            if self.name and not named:
                raise RuntimeError(f"no BLE device named {self.name!r} found")
            if not named and not devices:
                raise RuntimeError("no BLE devices found")
            address = named[0].address if named else devices[0].address
        self._client = BleakClient(address, disconnected_callback=self._on_disconnect)
        await self._client.connect()
        await self._client.start_notify(self.rx_uuid, self._on_rx)
        self.address = address
        self.mtu_size = self._client.mtu_size or 247
        self._connected = True

    def _on_rx(self, _handle, value):
        with self._lock:
            self._queue.append(bytes(value))

    def _on_disconnect(self, _client):
        self._connected = False
        self._disconnected = True

    def send(self, data):
        if not self._connected:
            raise ConnectionError("device not connected")
        self._run(
            self._client.write_gatt_char(self.tx_uuid, data, response=False), self.timeout
        )

    def send_with_response(self, data):
        if not self._connected:
            raise ConnectionError("device not connected")
        self._run(
            self._client.write_gatt_char(self.tx_uuid, data, response=True), self.timeout
        )

    def recv(self, timeout=None):
        deadline = time.monotonic() + (timeout or self.timeout)
        while time.monotonic() < deadline:
            with self._lock:
                if self._queue:
                    return self._queue.popleft()
            if self._disconnected:
                raise ConnectionError("device disconnected")
            time.sleep(0.02)
        raise TimeoutError(f"no data within {timeout or self.timeout}s")

    def try_recv(self):
        with self._lock:
            items = list(self._queue)
            self._queue.clear()
        return items

    def disconnect(self):
        if self._client is not None:
            try:
                self._run(self._client.disconnect(), self.timeout)
            except Exception:
                pass
            self._client = None
        self._connected = False
