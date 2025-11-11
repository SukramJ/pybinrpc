# SPDX-License-Identifier: MIT
# Copyright (c) 2021-2025 SukramJ
"""
Helper functions used within pybinrpc.

Public API of this module is defined by __all__.
"""

from __future__ import annotations

from collections.abc import Iterator
import contextlib
import os
import threading
from typing import Any
import uuid

import pytest

from pybinrpc.client import BinRpcServerProxy
from pybinrpc.server import SimpleBINRPCServer

# =============================================================================
# Tests (unittest)
# =============================================================================


async def test_serverproxy_init_set_get_remote() -> None:
    """
    Integration test against a real CUxD server (opt-in via env vars).

    Set environment variables to run this test:
      - CUXD_HOST: hostname or IP of the CUxD BIN-RPC server
      - CUXD_PORT: port number (e.g., 8701)
    Optional overrides:
      - CUXD_CALLBACK (default: xmlrpc_bin://127.0.0.1:19126)
      - CUXD_IFACE (default: iface-test)
      - CUXD_ADDRESS (default: CUX2801001:1)
      - CUXD_DATAPOINT (default: STATE)
    """
    host = os.getenv("CUXD_HOST")
    port = os.getenv("CUXD_PORT")
    if not host or not port:
        pytest.skip("CUXD_HOST/CUXD_PORT not set; skipping external CUxD integration test")

    callback = os.getenv("CUXD_CALLBACK", "xmlrpc_bin://127.0.0.1:19126")
    iface = os.getenv("CUXD_IFACE", "iface-test")
    address = os.getenv("CUXD_ADDRESS", "CUX3901001:1")
    datapoint = os.getenv("CUXD_DATAPOINT", "LEVEL")

    client = BinRpcServerProxy(host=host, port=int(port))
    try:
        ok = client.init(callback, iface)
        # Some CUxD variants may return an empty response to init; accept OK or empty/None
        assert ok in ("OK", "", None)
        client.setValue(address, datapoint, 1)
        val = client.getValue(address, datapoint)
        assert val == 0.8
    finally:
        client.init(callback)


class _CallbackRecorder:
    """Collect callback events from CUxD."""

    def __init__(self) -> None:
        self._events: list[tuple[str, str, str, Any]] = []
        self._event = threading.Event()

    def event(self, interface_id: str, address: str, datapoint: str, value: Any) -> str:
        """RPC entrypoint registered on the local callback server."""
        self._events.append((interface_id, address, datapoint, value))
        self._event.set()
        return ""

    def wait_for_event(self, timeout: float) -> tuple[str, str, str, Any]:
        """Return the last received event or fail if nothing arrived in time."""
        if not self._event.wait(timeout):
            raise AssertionError(f"CUxD did not emit an event within {timeout} seconds")
        return self._events[-1]


@contextlib.contextmanager
def _callback_server(bind_host: str, port: int, handler: _CallbackRecorder) -> Iterator[SimpleBINRPCServer]:
    """Start a BIN-RPC server that exposes the test event handler."""
    server = SimpleBINRPCServer((bind_host, port), timeout=15.0)
    server.register_function(handler.event, "event")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_serverproxy_event_roundtrip_real_cuxd() -> None:
    """
    Validate CUxD -> callback-server events against a real CUxD instance.

    Required env vars:
      - CUXD_HOST / CUXD_PORT: remote CUxD BIN-RPC endpoint (e.g., 172.18.4.39 / 8701)
      - CUXD_CALLBACK_HOST: IP/hostname reachable by the CUxD instance for callbacks

    Optional overrides:
      - CUXD_CALLBACK_BIND (default: 0.0.0.0)
      - CUXD_CALLBACK_PORT (default: 0 / ephemeral)
      - CUXD_IFACE (default: auto-generated)
      - CUXD_ADDRESS (default: CUX3900001:1)
      - CUXD_DATAPOINT (default: STATE)
    """
    host = os.getenv("CUXD_HOST")
    port = os.getenv("CUXD_PORT")
    callback_host = os.getenv("CUXD_CALLBACK_HOST")
    if not host or not port or not callback_host:
        pytest.skip("Set CUXD_HOST, CUXD_PORT, and CUXD_CALLBACK_HOST to run the CUxD event integration test")

    bind_host = os.getenv("CUXD_CALLBACK_BIND", "0.0.0.0")
    callback_port_env = os.getenv("CUXD_CALLBACK_PORT")
    callback_port = int(callback_port_env) if callback_port_env else 0

    iface = os.getenv("CUXD_IFACE", f"iface-event-{uuid.uuid4().hex[:8]}")
    address = os.getenv("CUXD_ADDRESS", "CUX3900001:1")
    datapoint = os.getenv("CUXD_DATAPOINT", "STATE")

    recorder = _CallbackRecorder()
    with _callback_server(bind_host, callback_port, recorder) as server:
        _, cb_port = server.server_address
        callback_url = f"xmlrpc_bin://{callback_host}:{cb_port}"

        client = BinRpcServerProxy(host=host, port=int(port))
        try:
            ok = client.init(callback_url, iface)
            assert ok in ("OK", "", None)

            desired_value = True
            client.setValue(address, datapoint, desired_value)
            read_back = client.getValue(address, datapoint)
            assert read_back in (desired_value, 1, "1", "true", "TRUE")

            iface_ev, addr_ev, dp_ev, value_ev = recorder.wait_for_event(timeout=20.0)
            assert iface_ev == iface
            assert addr_ev == address
            assert dp_ev == datapoint
            assert value_ev in (desired_value, 1, "1", "true", "TRUE")
        finally:
            with contextlib.suppress(Exception):
                client.init(callback_url)
