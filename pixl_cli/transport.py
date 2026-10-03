import asyncio
import threading

try:
    from bleak import BleakClient, BleakScanner
except ImportError as e:
    raise ImportError("bleak is required for BLE transport: pip install bleak") from e

from .consts import NUS_CHAR_RX_UUID, NUS_CHAR_TX_UUID, NUS_SERVICE_UUID


class BleakSyncTransport:
    def __init__(self, address=None, name=None, timeout=10.0):
        self.address = address
        self.name = name
        self.timeout = timeout
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._client = None
        self._rx = None
        self._connected = False

    def _run(self, coro, timeout=None):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    def connect(self):
        self._thread.start()
        self._run(self._connect(), self.timeout + 30.0)

    async def _connect(self):
        self._rx = asyncio.Queue()
        address = self.address
        if not address:
            devices = await BleakScanner.discover(
                service_uuids=[NUS_SERVICE_UUID], timeout=self.timeout
            )
            named = [d for d in devices if self.name and d.name == self.name]
            if self.name and not named:
                raise RuntimeError(f"no BLE device named {self.name!r} found")
            if not named and len(devices) == 0:
                raise RuntimeError("no BLE devices found")
            address = named[0].address if named else devices[0].address
        self._client = BleakClient(address)
        await self._client.connect()
        await self._client.start_notify(NUS_CHAR_RX_UUID, self._on_rx)
        self._connected = True

    def _on_rx(self, _handle, value):
        self._loop.call_soon_threadsafe(self._rx.put_nowait, bytes(value))

    def send(self, data):
        if not self._connected:
            raise RuntimeError("not connected")
        self._run(self._client.write_gatt_char(NUS_CHAR_TX_UUID, data, response=False), self.timeout)

    def recv(self, timeout=None):
        if not self._connected:
            raise RuntimeError("not connected")
        return self._run(self._rx.get(), timeout or self.timeout)

    def disconnect(self):
        if self._client is not None:
            try:
                self._run(self._client.disconnect(), self.timeout)
            except Exception:
                pass
            self._client = None
        self._connected = False
