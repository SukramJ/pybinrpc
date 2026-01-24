# SPDX-License-Identifier: MIT
# Copyright (c) 2021-2025 SukramJ
"""
Tests for the async BIN-RPC server.

These tests verify the AsyncBinRpcServer functionality including:
- Basic server lifecycle (start/stop)
- Method registration and dispatch
- System introspection (system.listMethods)
- System multicall batching
- Health endpoint
- Metrics
- CUxD compatibility

Note: The sync BinRpcServerProxy client must be run in a thread when used with
async tests, otherwise it blocks the event loop and prevents the server from
responding.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import struct

import pytest

from pybinrpc import AsyncBinRpcServer, AsyncCuxdServer, BinRpcServerProxy, create_async_bin_rpc_server
from pybinrpc.support import enc_request


# Helper to run sync client calls in a thread
async def _call_sync(host: str, port: int, method: str, *args, timeout: float = 2.0):
    """Run a sync RPC call in a thread to avoid blocking the event loop."""

    def do_call():
        client = BinRpcServerProxy(host=host, port=port, timeout=timeout)
        fn = client
        for part in method.split("."):
            fn = getattr(fn, part)
        return fn(*args)

    return await asyncio.to_thread(do_call)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
async def async_server():
    """Create and start an async BIN-RPC server for testing."""
    server = AsyncBinRpcServer(ip_addr="127.0.0.1", port=0, connection_timeout=2.0)
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
async def async_server_with_health():
    """Create and start an async BIN-RPC server with health endpoint."""
    server = AsyncBinRpcServer(
        ip_addr="127.0.0.1",
        port=0,
        connection_timeout=2.0,
        health_port=0,  # Use ephemeral port
    )
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
async def async_cuxd_server():
    """Create and start an async CUxD server for testing."""
    server = AsyncCuxdServer(addr=("127.0.0.1", 0), connection_timeout=2.0)
    await server.start()
    yield server
    await server.stop()


# =============================================================================
# Basic Server Tests
# =============================================================================


async def test_server_start_stop():
    """Test basic server start and stop lifecycle."""
    server = AsyncBinRpcServer(ip_addr="127.0.0.1", port=0)
    assert not server.started

    await server.start()
    assert server.started
    assert server.listen_port > 0

    await server.stop()
    assert not server.started


async def test_server_singleton():
    """Test that server uses singleton pattern."""
    server1 = AsyncBinRpcServer(ip_addr="127.0.0.1", port=12345)
    server2 = AsyncBinRpcServer(ip_addr="127.0.0.1", port=12345)
    assert server1 is server2

    # Different port should create different instance
    server3 = AsyncBinRpcServer(ip_addr="127.0.0.1", port=12346)
    assert server1 is not server3

    # Cleanup
    await server1.stop()
    await server3.stop()


async def test_factory_function():
    """Test create_async_bin_rpc_server factory."""
    server = await create_async_bin_rpc_server(
        ip_addr="127.0.0.1",
        port=0,
    )
    assert server.started
    assert server.listen_port > 0
    await server.stop()


# =============================================================================
# Method Registration Tests
# =============================================================================


async def test_ping(async_server: AsyncBinRpcServer):
    """Test built-in ping method."""
    result = await _call_sync("127.0.0.1", async_server.listen_port, "ping")
    assert result == "pong"


async def test_register_sync_function(async_server: AsyncBinRpcServer):
    """Test registering and calling sync functions."""

    def add(a: int, b: int) -> int:
        return a + b

    async_server.register_function(add, "add")

    result = await _call_sync("127.0.0.1", async_server.listen_port, "add", 2, 3)
    assert result == 5


async def test_register_async_function(async_server: AsyncBinRpcServer):
    """Test registering and calling async functions."""

    async def async_multiply(a: int, b: int) -> int:
        await asyncio.sleep(0.001)  # Simulate async work
        return a * b

    async_server.register_function(async_multiply, "multiply")

    result = await _call_sync("127.0.0.1", async_server.listen_port, "multiply", 4, 5)
    assert result == 20


async def test_register_instance(async_server: AsyncBinRpcServer):
    """Test registering an instance with methods."""

    class Calculator:
        def add(self, a: int, b: int) -> int:
            return a + b

        def subtract(self, a: int, b: int) -> int:
            return a - b

    calc = Calculator()
    async_server.register_instance(calc)

    result1 = await _call_sync("127.0.0.1", async_server.listen_port, "add", 10, 5)
    result2 = await _call_sync("127.0.0.1", async_server.listen_port, "subtract", 10, 5)
    assert result1 == 15
    assert result2 == 5


async def test_unknown_method_returns_empty_string(async_server: AsyncBinRpcServer):
    """Test that unknown methods return empty string."""
    result = await _call_sync("127.0.0.1", async_server.listen_port, "nonexistent_method")
    assert result == ""


# =============================================================================
# System Methods Tests
# =============================================================================


async def test_system_list_methods(async_server: AsyncBinRpcServer):
    """Test system.listMethods introspection."""
    async_server.register_introspection_functions()

    def my_method() -> str:
        return "hello"

    async_server.register_function(my_method, "myMethod")

    methods = await _call_sync("127.0.0.1", async_server.listen_port, "system.listMethods")
    assert "system.listMethods" in methods
    assert "myMethod" in methods


async def test_system_multicall(async_server: AsyncBinRpcServer):
    """Test system.multicall batching."""
    async_server.register_multicall_functions()

    def echo(value: str) -> str:
        return value

    async_server.register_function(echo, "echo")

    # Note: Using non-empty params to avoid BIN-RPC leniency rule issue
    # where empty arrays followed by structs with methodName/params get merged
    results = await _call_sync(
        "127.0.0.1",
        async_server.listen_port,
        "system.multicall",
        [
            {"methodName": "echo", "params": ["hello"]},
            {"methodName": "echo", "params": ["world"]},
        ],
    )
    assert results == ["hello", "world"]


async def test_system_multicall_with_custom_methods(async_server: AsyncBinRpcServer):
    """Test system.multicall with custom methods."""
    async_server.register_multicall_functions()

    def double(x: int) -> int:
        return x * 2

    async_server.register_function(double, "double")

    results = await _call_sync(
        "127.0.0.1",
        async_server.listen_port,
        "system.multicall",
        [
            {"methodName": "double", "params": [5]},
            {"methodName": "double", "params": [10]},
            {"methodName": "ping", "params": []},
        ],
    )
    assert results == [10, 20, "pong"]


# =============================================================================
# Metrics Tests
# =============================================================================


async def test_metrics(async_server: AsyncBinRpcServer):
    """Test that metrics are recorded."""
    # Make some requests (run in thread to avoid blocking)
    await _call_sync("127.0.0.1", async_server.listen_port, "ping")
    await _call_sync("127.0.0.1", async_server.listen_port, "ping")
    await _call_sync("127.0.0.1", async_server.listen_port, "ping")

    metrics = async_server.metrics
    assert metrics.request_count == 3
    assert metrics.error_count == 0
    assert metrics.avg_latency_ms > 0
    assert metrics.last_request_time is not None


# =============================================================================
# Health Endpoint Tests
# =============================================================================


async def test_health_endpoint(async_server_with_health: AsyncBinRpcServer):
    """Test HTTP health endpoint."""
    # Get the health port from the server
    # Note: We need to access the internal health server to get its port
    server = async_server_with_health
    if server._health_server and server._health_server.sockets:
        health_port = server._health_server.sockets[0].getsockname()[1]

        # Make HTTP request to health endpoint
        reader, writer = await asyncio.open_connection("127.0.0.1", health_port)
        writer.write(b"GET /health HTTP/1.1\r\nHost: localhost\r\n\r\n")
        await writer.drain()

        response = await asyncio.wait_for(reader.read(4096), timeout=2.0)
        writer.close()
        await writer.wait_closed()

        # Parse response
        response_str = response.decode("utf-8")
        assert "200 OK" in response_str
        assert "application/json" in response_str

        # Extract JSON body
        body_start = response_str.find("\r\n\r\n") + 4
        body = response_str[body_start:]
        health_data = json.loads(body)

        assert health_data["status"] == "healthy"
        assert health_data["started"] is True
        assert "metrics" in health_data


# =============================================================================
# CUxD Server Tests
# =============================================================================


async def test_cuxd_server_event(async_cuxd_server: AsyncCuxdServer):
    """Test CUxD event method."""
    result = await _call_sync(
        "127.0.0.1",
        async_cuxd_server.listen_port,
        "event",
        "iface-test",
        "CUX001:1",
        "STATE",
        True,
    )
    assert result == ""


async def test_cuxd_server_new_devices(async_cuxd_server: AsyncCuxdServer):
    """Test CUxD newDevices method."""
    devices = [
        {"ADDRESS": "CUX001", "TYPE": "DEVICE"},
        {"ADDRESS": "CUX001:1", "TYPE": "CHANNEL", "PARENT": "CUX001"},
    ]
    result = await _call_sync(
        "127.0.0.1",
        async_cuxd_server.listen_port,
        "newDevices",
        "iface-test",
        devices,
    )
    assert result == ""

    # Check devices were registered
    assert "CUX001" in async_cuxd_server.devices
    assert "CUX001:1" in async_cuxd_server.devices


async def test_cuxd_server_delete_devices(async_cuxd_server: AsyncCuxdServer):
    """Test CUxD deleteDevices method."""
    # First add devices
    devices = [{"ADDRESS": "CUX002", "TYPE": "DEVICE"}]
    await _call_sync(
        "127.0.0.1",
        async_cuxd_server.listen_port,
        "newDevices",
        "iface-test",
        devices,
    )
    assert "CUX002" in async_cuxd_server.devices

    # Then delete
    result = await _call_sync(
        "127.0.0.1",
        async_cuxd_server.listen_port,
        "deleteDevices",
        "iface-test",
        ["CUX002"],
    )
    assert result == ""
    assert "CUX002" not in async_cuxd_server.devices


async def test_cuxd_server_list_devices(async_cuxd_server: AsyncCuxdServer):
    """Test CUxD listDevices method."""
    # Add some devices
    devices = [
        {"ADDRESS": "CUX003", "TYPE": "DEVICE"},
        {"ADDRESS": "CUX003:1", "TYPE": "CHANNEL"},
    ]
    await _call_sync(
        "127.0.0.1",
        async_cuxd_server.listen_port,
        "newDevices",
        "iface-test",
        devices,
    )

    # List devices
    result = await _call_sync(
        "127.0.0.1",
        async_cuxd_server.listen_port,
        "listDevices",
    )
    assert isinstance(result, list)
    assert len(result) == 2
    addresses = [d["ADDRESS"] for d in result]
    assert "CUX003" in addresses
    assert "CUX003:1" in addresses


# =============================================================================
# CUxD Compatibility Tests
# =============================================================================


async def test_async_server_accepts_underreported_frame_length(async_server: AsyncBinRpcServer):
    """Async server must cope with CUxD frames that under-report their size."""
    calls: list[tuple[str, str, str, bool]] = []

    async def event(interface_id: str, address: str, datapoint: str, value: bool) -> str:
        calls.append((interface_id, address, datapoint, value))
        return ""

    async_server.register_function(event, "event")

    host = "127.0.0.1"
    port = async_server.listen_port

    # Create a frame with under-reported length
    frame = enc_request(
        method="event",
        params=["iface", "CUX3900001:1", "STATE", True],
        encoding="utf-8",
    )
    total = struct.unpack(">I", frame[4:8])[0]
    truncated_frame = frame[:4] + struct.pack(">I", total - 3) + frame[8:]

    # Send the malformed frame
    reader, writer = await asyncio.open_connection(host, port)
    writer.write(truncated_frame)
    await writer.drain()

    # Read response
    response = await asyncio.wait_for(reader.read(1024), timeout=2.0)
    writer.close()
    await writer.wait_closed()

    # Verify the call was dispatched
    assert response  # Should have received a response
    assert len(calls) == 1
    assert calls[0] == ("iface", "CUX3900001:1", "STATE", True)


async def test_multiple_concurrent_connections(async_server: AsyncBinRpcServer):
    """Test handling multiple concurrent client connections."""
    # Make multiple concurrent requests (each in its own thread)
    results = await asyncio.gather(
        _call_sync("127.0.0.1", async_server.listen_port, "ping"),
        _call_sync("127.0.0.1", async_server.listen_port, "ping"),
        _call_sync("127.0.0.1", async_server.listen_port, "ping"),
    )

    assert results == ["pong", "pong", "pong"]


async def test_connection_timeout(async_server: AsyncBinRpcServer):
    """Test that idle connections are handled properly."""
    # Open connection but don't send anything
    reader, writer = await asyncio.open_connection(
        "127.0.0.1",
        async_server.listen_port,
    )

    # Wait a bit (but less than timeout)
    await asyncio.sleep(0.1)

    # Connection should still work
    frame = enc_request(method="ping", params=[], encoding="utf-8")
    writer.write(frame)
    await writer.drain()

    response = await asyncio.wait_for(reader.read(1024), timeout=2.0)
    writer.close()
    await writer.wait_closed()

    assert response  # Should have received a response


# =============================================================================
# Error Handling Tests
# =============================================================================


async def test_handler_exception_returns_empty_string(async_server: AsyncBinRpcServer):
    """Test that handler exceptions return empty string."""

    def failing_method() -> str:
        raise ValueError("Test error")

    async_server.register_function(failing_method, "fail")

    result = await _call_sync("127.0.0.1", async_server.listen_port, "fail")
    assert result == ""


async def test_invalid_frame_handling(async_server: AsyncBinRpcServer):
    """Test handling of invalid BIN-RPC frames."""
    reader, writer = await asyncio.open_connection(
        "127.0.0.1",
        async_server.listen_port,
    )

    # Send invalid header
    writer.write(b"INVALID_HEADER")
    await writer.drain()

    # Server should close connection or send error response
    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(reader.read(1024), timeout=2.0)

    writer.close()
    await writer.wait_closed()

    # Server should still be running
    assert async_server.started
