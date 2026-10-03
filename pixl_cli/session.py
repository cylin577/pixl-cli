import threading

from .client import PixlClient
from .transport import BleakSyncTransport
from .store import remember_device


class Session:
    def __init__(self):
        self._transport = None
        self._client = None
        self._lock = threading.Lock()

    def client(self, args=None):
        with self._lock:
            if self._client is not None and self._transport is not None and not self._transport._connected:
                self._transport.disconnect()
                self._client = None
            if self._client is not None:
                return self._client
            address = getattr(args, "address", None)
            name = getattr(args, "name", "Pixl.js")
            timeout = getattr(args, "timeout", 10.0)
            transport = BleakSyncTransport(address=address, name=name, timeout=timeout)
            transport.connect()
            self._transport = transport
            self._client = PixlClient(transport)
            remember_device(name if address is None else None, transport.address)
            return self._client

    def transport(self, args=None):
        self.client(args)
        return self._transport

    @property
    def address(self):
        return self._transport.address if self._transport else None

    def is_connected(self):
        return self._transport is not None and self._transport._connected

    def reset(self):
        with self._lock:
            if self._transport is not None:
                self._transport.disconnect()
            self._transport = None
            self._client = None


session = Session()
