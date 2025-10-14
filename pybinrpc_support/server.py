# SPDX-License-Identifier: MIT
# Copyright (c) 2021-2025 SukramJ
"""
Helper functions used within pybinrpc.

Public API of this module is defined by __all__.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import struct
import threading
from typing import Any

from pybinrpc.const import DEFAULT_ENCODING
from pybinrpc.server import SimpleBINRPCServer
from pybinrpc.support import enc_request

# =============================================================================
# Fake CUxD (stub) for tests
# =============================================================================


class FakeServer(SimpleBINRPCServer):
    """
    A minimal CUxD-like BIN-RPC server used for tests.

    Implements:
      - init(callback_url, interface_id): remembers callback and returns "OK".
      - setValue(address, datapoint, value): stores values; returns "".
      - getValue(address, datapoint): returns stored value or "".
      - listDevices(): returns a static set of devices.
      - system.multicall(): inherited from base.
      - triggerEvent(address, datapoint, value): test helper to emit an `event`
        to the registered callback server.
    """

    __kwonly_check__ = False

    def __init__(self, host: str, port: int, *, timeout: float = 10.0):
        """Initialize the server."""
        super().__init__((host, port), timeout=timeout)
        self._values: dict[tuple[str, str], Any] = {}
        self._callback: tuple[str, int] | None = None
        # Register CUxD-like RPCs
        self.register_function(self.init, "init")
        self.register_function(self.setValue, "setValue")
        self.register_function(self.getValue, "getValue")
        self.register_function(self.listDevices, "listDevices")
        self.register_introspection_functions()
        self.register_multicall_functions()
        self.events: list[tuple[str, str, str, Any]] = []
        # Start a lightweight callback server for handling 'event' RPCs during tests
        self._cb_server = SimpleBINRPCServer(("127.0.0.1", 19126), timeout=timeout)
        self._cb_server.register_function(self._on_event, "event")
        self._cb_thread = threading.Thread(target=self._cb_server.serve_forever, daemon=True)
        self._cb_thread.start()

    # CUxD methods ------------------------------------------------------------

    def init(self, callback: str, interface_id: str) -> str:
        """Register a callback server for events."""
        # Expect format xmlrpc_bin://host:port
        if not (m := re.match("^xmlrpc_bin://([^:]+):(\\d+)$", callback)):
            return "ERR"
        host, port = m.group(1), int(m.group(2))
        self._callback = (host, port)
        return "OK"

    def setValue(self, address: str, datapoint: str, value: Any) -> str:
        """Set a value for a datapoint."""
        self._values[(address, datapoint)] = value
        return ""

    def getValue(self, address: str, datapoint: str) -> Any:
        """Get a value for a datapoint."""
        return self._values.get((address, datapoint), "")

    def listDevices(self) -> list[dict[str, Any]]:
        """Return a static set of devices."""
        return [
            {"ADDRESS": "CUX2801001:1", "VERSION": 1},
            {"ADDRESS": "CUX2801002:1", "VERSION": 1},
        ]

    def _on_event(self, interface_id: str, address: str, datapoint: str, value: Any) -> str:
        """Handle an `event` RPC call from the callback server."""
        self.events.append((interface_id, address, datapoint, value))
        return ""

    def server_close(self) -> None:
        """Close main server and embedded callback server."""
        # First shut down the callback server
        with contextlib.suppress(Exception):
            self._cb_server.shutdown()

        with contextlib.suppress(Exception):
            self._cb_server.server_close()

        # Join callback thread
        if (t := getattr(self, "_cb_thread", None)) is not None:
            with contextlib.suppress(Exception):
                t.join(timeout=1)
        # Now close the main server
        super().server_close()

    # Test helper -------------------------------------------------------------

    async def triggerEvent(self, interface_id: str, address: str, datapoint: str, value: Any) -> None:
        """Fire an event to the registered callback."""
        if not self._callback:
            return
        host, port = self._callback
        # Fire an `event` call to the registered callback
        reader, writer = await asyncio.open_connection(host, port)
        try:
            frame = enc_request(
                method="event", params=[interface_id, address, datapoint, value], encoding=DEFAULT_ENCODING
            )
            writer.write(frame)
            await writer.drain()
            # read and ignore response
            hdr = await reader.readexactly(8)
            total = struct.unpack(">I", hdr[4:8])[0]
            _ = await reader.readexactly(total - 8)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()
