# SPDX-License-Identifier: MIT
# Copyright (c) 2021-2025 SukramJ
"""
Helper functions used within pybinrpc.

Public API of this module is defined by __all__.
"""

from __future__ import annotations

import asyncio
import socket
import struct
import threading
import time

from pybinrpc.client import BinRpcServerProxy
from pybinrpc.server import SimpleBINRPCServer
from pybinrpc.support import enc_request
from pybinrpc_support.server import FakeServer

# =============================================================================
# Tests (unittest)
# =============================================================================


async def test_serverproxy_init_set_get(fake_server: FakeServer) -> None:
    """Test server proxy initialization, setting, and getting values."""
    assert fake_server
    client = BinRpcServerProxy(host="127.0.0.1", port=18701, timeout=2.0, keep_alive=True)
    ok = client.init("xmlrpc_bin://127.0.0.1:19126", "iface-test")
    assert ok == "OK"
    client.setValue("CUX2801001:1", "STATE", True)
    val = client.getValue("CUX2801001:1", "STATE")
    assert val is True


async def test_multicall(fake_server: FakeServer) -> None:
    """Test multicall."""
    assert fake_server
    client = BinRpcServerProxy(host="127.0.0.1", port=18701)
    res = client.system.multicall(
        [
            {"methodName": "setValue", "params": ["CUX2801002:1", "STATE", 42]},
            {"methodName": "getValue", "params": ["CUX2801002:1", "STATE"]},
        ]
    )
    assert res[-1] == 42


async def test_event_callback_with_int(fake_server: FakeServer) -> None:
    """Test event callback."""
    assert fake_server
    client = BinRpcServerProxy(host="127.0.0.1", port=18701)
    ok = client.init("xmlrpc_bin://127.0.0.1:19126", "iface-test")
    assert ok == "OK"
    # Trigger event from fake CUxD
    await fake_server.triggerEvent("iface-test", "CUX2801001:1", "STATE", 1)
    # Allow a tiny delay for callback handling
    await asyncio.sleep(0.05)
    assert fake_server.events
    assert fake_server.events[-1] == ("iface-test", "CUX2801001:1", "STATE", 1)


async def test_event_callback_with_bool(fake_server: FakeServer) -> None:
    """Test event callback."""
    assert fake_server
    client = BinRpcServerProxy(host="127.0.0.1", port=18701)
    ok = client.init("xmlrpc_bin://127.0.0.1:19126", "iface-test")
    assert ok == "OK"
    # Trigger event from fake CUxD
    await fake_server.triggerEvent("iface-test", "CUX2801001:1", "PRESS_SHORT", True)
    # Allow a tiny delay for callback handling
    await asyncio.sleep(0.05)
    assert fake_server.events
    assert fake_server.events[-1] == ("iface-test", "CUX2801001:1", "PRESS_SHORT", True)


async def test_event_callback_with_double(fake_server: FakeServer) -> None:
    """Test event callback."""
    assert fake_server
    client = BinRpcServerProxy(host="127.0.0.1", port=18701)
    ok = client.init("xmlrpc_bin://127.0.0.1:19126", "iface-test")
    assert ok == "OK"
    # Trigger event from fake CUxD
    for value in range(1, 100):
        value = round(value / 100, 2)
        await fake_server.triggerEvent("iface-test", "CUX2801001:1", "LEVEL", value)
        # Allow a tiny delay for callback handling
        assert fake_server.events
        assert fake_server.events[-1] == ("iface-test", "CUX2801001:1", "LEVEL", value)


async def test_list_devices(fake_server: FakeServer) -> None:
    """Test list devices."""
    assert fake_server
    client = BinRpcServerProxy(host="127.0.0.1", port=18701)
    devs = client.listDevices()
    assert isinstance(devs, list)
    assert any(d.get("ADDRESS") == "CUX2801001:1" for d in devs) is True


def test_simple_server_accepts_underreported_frame_length() -> None:
    """Server must cope with CUxD frames that under-report their size."""

    calls: list[tuple[str, str, str, bool]] = []

    def event(interface_id: str, address: str, datapoint: str, value: bool) -> str:
        calls.append((interface_id, address, datapoint, value))
        return ""

    server = SimpleBINRPCServer(("127.0.0.1", 0), timeout=0.5)
    server.register_function(event, "event")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        frame = enc_request(
            method="event",
            params=["iface", "CUX3900001:1", "STATE", True],
            encoding="ascii",
        )
        total = struct.unpack(">I", frame[4:8])[0]
        truncated_frame = frame[:4] + struct.pack(">I", total - 3) + frame[8:]
        with socket.create_connection((host, port), timeout=1.0) as sock:
            sock.sendall(truncated_frame)
            # Allow server to respond, then read the reply (ignore content)
            sock.shutdown(socket.SHUT_WR)
            _ = sock.recv(1024)
        timeout_at = time.time() + 1.0
        while not calls and time.time() < timeout_at:
            time.sleep(0.01)
        assert calls, "Server did not dispatch event"
        assert calls[-1] == ("iface", "CUX3900001:1", "STATE", True)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
