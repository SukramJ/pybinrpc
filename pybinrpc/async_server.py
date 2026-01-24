# SPDX-License-Identifier: MIT
# Copyright (c) 2021-2025 SukramJ
"""
Async BIN-RPC server module.

Provides an asyncio-native BIN-RPC server for receiving callbacks
from HomeMatic backends (CCU/CUxD devices).

This implementation follows the patterns from aiohomematic/central/rpc_server.py
but uses raw TCP sockets instead of HTTP, as BIN-RPC is a binary protocol.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import json
import logging
import struct
import time
from typing import Any, Final, Self

from pybinrpc.const import DEFAULT_ENCODING, IP_ANY_V4, PORT_ANY
from pybinrpc.support import async_drain_pending_bytes, dec_request, enc_response

_LOGGER: Final = logging.getLogger(__name__)

# Type alias for method handlers (sync or async)
type MethodHandler = Callable[..., Any] | Callable[..., Awaitable[Any]]


class AsyncBinRpcDispatcher:
    """
    Dispatcher for async BIN-RPC method calls.

    Supports both sync and async handlers. Sync handlers are automatically
    wrapped to run in the event loop.
    """

    __kwonly_check__ = False

    def __init__(self) -> None:
        """Initialize the dispatcher."""
        self._methods: Final[dict[str, MethodHandler]] = {}
        self._instance: object | None = None
        self._background_tasks: Final[set[asyncio.Task[None]]] = set()
        self._enable_introspection: bool = False

    @property
    def active_tasks_count(self) -> int:
        """Return the number of active background tasks."""
        return len(self._background_tasks)

    async def dispatch(self, method: str, params: list[Any]) -> Any:
        """
        Dispatch a method call to the registered handler.

        Args:
            method: The method name to call
            params: The parameters to pass to the method

        Returns:
            The result of the method call, or "" on error/not found

        """
        fn = self._resolve_instance_call(method)
        if fn is None:
            fn = self._methods.get(method)
        if fn is None:
            if method == "ping":
                return "pong"
            _LOGGER.debug("Unhandled BIN-RPC method: %s", method)
            return ""

        try:
            # Check if the handler is a coroutine function
            if asyncio.iscoroutinefunction(fn):
                return await fn(*params)
            # Sync function - run directly (could use to_thread for blocking)
            return fn(*params)
        except Exception as exc:
            _LOGGER.warning("Error in handler %s: %s", method, exc)
            return ""

    def register_function(self, func: MethodHandler, name: str | None = None) -> None:
        """Register a function under the given name (defaults to func.__name__)."""
        self._methods[name or func.__name__] = func

    def register_instance(self, instance: object, *, allow_dotted_names: bool = True) -> None:
        """Register an instance; public callables become exposed via dotted names."""
        self._instance = instance

    def register_introspection_functions(self) -> None:
        """Enable system.listMethods introspection."""
        self._enable_introspection = True
        self.register_function(self._system_list_methods, "system.listMethods")

    def register_multicall_functions(self) -> None:
        """Enable system.multicall batching."""
        self.register_function(self._system_multicall, "system.multicall")

    async def cancel_background_tasks(self) -> None:
        """Cancel all background tasks and wait for them to complete."""
        if not self._background_tasks:
            return

        _LOGGER.debug("Cancelling %d background tasks", len(self._background_tasks))

        for task in self._background_tasks:
            task.cancel()

        if self._background_tasks:
            await asyncio.wait(self._background_tasks, timeout=5.0)

    def create_background_task(self, coro: Any, /, *, name: str) -> None:
        """Create a background task and track it to prevent garbage collection."""
        task: asyncio.Task[None] = asyncio.create_task(coro, name=name)
        self._background_tasks.add(task)
        task.add_done_callback(self._on_background_task_done)

    def _on_background_task_done(self, task: asyncio.Task[None]) -> None:
        """Handle background task completion and log any errors."""
        self._background_tasks.discard(task)
        if task.cancelled():
            return
        if exc := task.exception():
            _LOGGER.warning(
                "Background task %s failed: %s",
                task.get_name(),
                exc,
            )

    def _resolve_instance_call(self, method: str) -> MethodHandler | None:
        """Resolve a dotted method name to a callable."""
        if not self._instance:
            return None
        target: Any = self._instance
        for part in method.split("."):
            if not hasattr(target, part):
                return None
            target = getattr(target, part)
        return target if callable(target) else None

    async def _system_list_methods(self, *_: Any) -> list[str]:
        """Return a list of all methods supported by the server."""
        if not self._enable_introspection:
            return []
        names = set(self._methods.keys())
        if self._instance is not None:
            for name in dir(self._instance):
                if name.startswith("_"):
                    continue
                attr = getattr(self._instance, name)
                if callable(attr):
                    names.add(name)
        return sorted(names)

    async def _system_multicall(self, calls: list[dict[str, Any]]) -> list[Any]:
        """Process a batch of method calls. Returns a list of results."""
        results: list[Any] = []
        for call in calls or []:
            try:
                name = str(call.get("methodName") or "")
                params = call.get("params", [])
                result = await self.dispatch(method=name, params=params)
                results.append(result)
            except Exception as exc:
                _LOGGER.warning("Error in multicall entry: %s", exc)
                results.append("")
        return results


class _ServerMetrics:
    """Container for server metrics."""

    __kwonly_check__ = False

    __slots__ = (
        "request_count",
        "error_count",
        "total_latency_ms",
        "last_request_time",
    )

    def __init__(self) -> None:
        """Initialize metrics."""
        self.request_count: int = 0
        self.error_count: int = 0
        self.total_latency_ms: float = 0.0
        self.last_request_time: float | None = None

    @property
    def avg_latency_ms(self) -> float:
        """Return average latency in milliseconds."""
        if self.request_count == 0:
            return 0.0
        return self.total_latency_ms / self.request_count

    def record_request(self, latency_ms: float) -> None:
        """Record a request with its latency."""
        self.request_count += 1
        self.total_latency_ms += latency_ms
        self.last_request_time = time.time()

    def record_error(self) -> None:
        """Record an error."""
        self.error_count += 1

    def to_dict(self) -> dict[str, Any]:
        """Return metrics as dictionary."""
        return {
            "request_count": self.request_count,
            "error_count": self.error_count,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "last_request_time": self.last_request_time,
        }


class AsyncBinRpcServer:
    """
    Async BIN-RPC server using asyncio.

    Singleton per (ip_addr, port) combination.

    This server provides:
    - Async BIN-RPC protocol handling
    - Method registration (functions and instances)
    - Introspection (system.listMethods)
    - Multicall batching (system.multicall)
    - HTTP health endpoint
    - Request metrics

    Example usage:
        server = AsyncBinRpcServer(ip_addr="0.0.0.0", port=2001)
        server.register_function(my_handler, "event")
        await server.start()
        # ... server is running ...
        await server.stop()

    """

    __kwonly_check__ = False

    _initialized: bool = False
    _instances: Final[dict[tuple[str, int], AsyncBinRpcServer]] = {}

    def __new__(
        cls,
        *,
        ip_addr: str = IP_ANY_V4,
        port: int = PORT_ANY,
        connection_timeout: float = 10.0,
        encoding: str = DEFAULT_ENCODING,
        health_port: int | None = None,
    ) -> Self:
        """Return existing instance or create new one."""
        if (key := (ip_addr, port)) not in cls._instances:
            _LOGGER.debug("Creating AsyncBinRpcServer for %s:%d", ip_addr, port)
            instance = super().__new__(cls)
            cls._instances[key] = instance
        return cls._instances[key]  # type: ignore[return-value]

    def __init__(
        self,
        *,
        ip_addr: str = IP_ANY_V4,
        port: int = PORT_ANY,
        connection_timeout: float = 10.0,
        encoding: str = DEFAULT_ENCODING,
        health_port: int | None = None,
    ) -> None:
        """
        Initialize the async BIN-RPC server.

        Args:
            ip_addr: IP address to bind to (default: 0.0.0.0)
            port: Port to bind to (default: 0 = auto-assign)
            connection_timeout: Per-connection read timeout in seconds
            encoding: Character encoding for strings (default: utf-8)
            health_port: Optional port for HTTP health endpoint

        """
        if self._initialized:
            return

        self._ip_addr: Final = ip_addr
        self._requested_port: Final = port
        self._actual_port: int = port
        self._connection_timeout: Final = connection_timeout
        self._encoding: Final = encoding
        self._health_port: Final = health_port

        self._server: asyncio.Server | None = None
        self._health_server: asyncio.Server | None = None
        self._started: bool = False
        self._dispatcher: Final = AsyncBinRpcDispatcher()
        self._metrics: Final = _ServerMetrics()

        self._initialized = True

    @property
    def listen_ip_addr(self) -> str:
        """Return the listening IP address."""
        return self._ip_addr

    @property
    def listen_port(self) -> int:
        """Return the actual listening port."""
        return self._actual_port

    @property
    def started(self) -> bool:
        """Return True if server is running."""
        return self._started

    @property
    def metrics(self) -> _ServerMetrics:
        """Return server metrics."""
        return self._metrics

    @property
    def active_tasks_count(self) -> int:
        """Return number of active background tasks."""
        return self._dispatcher.active_tasks_count

    # --- Registration API (delegates to dispatcher) ---

    def register_function(self, func: MethodHandler, name: str | None = None) -> None:
        """Register a function under the given name (defaults to func.__name__)."""
        self._dispatcher.register_function(func, name)

    def register_instance(self, instance: object, *, allow_dotted_names: bool = True) -> None:
        """Register an instance; public callables become exposed via dotted names."""
        self._dispatcher.register_instance(instance, allow_dotted_names=allow_dotted_names)

    def register_introspection_functions(self) -> None:
        """Enable system.listMethods introspection."""
        self._dispatcher.register_introspection_functions()

    def register_multicall_functions(self) -> None:
        """Enable system.multicall batching."""
        self._dispatcher.register_multicall_functions()

    # --- Server lifecycle ---

    async def start(self) -> None:
        """Start the BIN-RPC server."""
        if self._started:
            return

        self._server = await asyncio.start_server(
            self._handle_client,
            self._ip_addr,
            self._requested_port,
            reuse_address=True,
        )

        # Get actual port (important when PORT_ANY is used)
        if self._server.sockets:
            self._actual_port = self._server.sockets[0].getsockname()[1]

        # Start health server if port specified
        if self._health_port is not None:
            self._health_server = await asyncio.start_server(
                self._handle_health_request,
                self._ip_addr,
                self._health_port,
                reuse_address=True,
            )
            _LOGGER.debug(
                "Health endpoint started on %s:%d",
                self._ip_addr,
                self._health_port,
            )

        self._started = True
        _LOGGER.debug(
            "AsyncBinRpcServer started on %s:%d",
            self._ip_addr,
            self._actual_port,
        )

    async def stop(self) -> None:
        """Stop the BIN-RPC server."""
        if not self._started:
            return

        _LOGGER.debug("Stopping AsyncBinRpcServer")

        # Stop health server
        if self._health_server:
            self._health_server.close()
            await self._health_server.wait_closed()
            self._health_server = None

        # Stop main server
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        # Cancel background tasks
        await self._dispatcher.cancel_background_tasks()

        self._started = False

        # Remove from instances
        if (key := (self._ip_addr, self._requested_port)) in self._instances:
            del self._instances[key]

        _LOGGER.debug("AsyncBinRpcServer stopped")

    # --- Client handling ---

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle incoming client connection."""
        peer = writer.get_extra_info("peername")
        _LOGGER.debug("New BIN-RPC connection from %s", peer)

        try:
            while True:
                start_time = time.perf_counter()
                try:
                    # 1. Read header (8 bytes)
                    header = await asyncio.wait_for(
                        reader.readexactly(8),
                        timeout=self._connection_timeout,
                    )

                    # 2. Validate header
                    if header[:3] != b"Bin":
                        raise ValueError("Invalid BIN-RPC header")

                    # 3. Parse frame length
                    total = struct.unpack(">I", header[4:8])[0]

                    # 4. Read body
                    if (body_len := max(total - 8, 0)) > 0:
                        body = await asyncio.wait_for(
                            reader.readexactly(body_len),
                            timeout=self._connection_timeout,
                        )
                    else:
                        body = b""

                    # 5. Drain extra bytes (CUxD compatibility)
                    if extra := await async_drain_pending_bytes(reader):
                        body += extra

                    # 6. Decode request
                    method, params = dec_request(
                        frame=header + body,
                        encoding=self._encoding,
                    )
                    _LOGGER.debug(
                        "BIN-RPC request: method=%s, params=%s",
                        method,
                        params[:2] if len(params) > 2 else params,
                    )

                    # 7. Dispatch
                    result = await self._dispatcher.dispatch(method, params)

                    # 8. Send response
                    response = enc_response(ret=result, encoding=self._encoding)
                    writer.write(response)
                    await writer.drain()

                    # Record metrics
                    latency_ms = (time.perf_counter() - start_time) * 1000
                    self._metrics.record_request(latency_ms)

                except TimeoutError:
                    _LOGGER.debug("Client %s timed out", peer)
                    break
                except asyncio.IncompleteReadError:
                    _LOGGER.debug("Client %s disconnected", peer)
                    break
                except ValueError as exc:
                    _LOGGER.warning("Protocol error from %s: %s", peer, exc)
                    self._metrics.record_error()
                    # Send empty response on protocol error
                    try:
                        writer.write(enc_response(ret="", encoding=self._encoding))
                        await writer.drain()
                    except Exception:
                        pass
                    break

        except Exception as exc:
            _LOGGER.warning("Error handling client %s: %s", peer, exc)
            self._metrics.record_error()
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    # --- Health endpoint ---

    async def _handle_health_request(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle HTTP health check request."""
        try:
            # Read HTTP request (we don't really parse it)
            await asyncio.wait_for(reader.read(4096), timeout=5.0)

            # Build health data
            health_data = {
                "status": "healthy" if self._started else "stopped",
                "started": self._started,
                "listen_address": f"{self._ip_addr}:{self._actual_port}",
                "active_background_tasks": self._dispatcher.active_tasks_count,
                "metrics": self._metrics.to_dict(),
            }

            # Build HTTP response
            body = json.dumps(health_data, indent=2)
            response = (
                "HTTP/1.1 200 OK\r\n"
                "Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n"
                "\r\n"
                f"{body}"
            )

            writer.write(response.encode("utf-8"))
            await writer.drain()

        except Exception as exc:
            _LOGGER.debug("Health check error: %s", exc)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


# =============================================================================
# CUxD convenience server (async version)
# =============================================================================


class AsyncCuxdServer(AsyncBinRpcServer):
    """Async server with CUxD defaults and in-memory device registry."""

    __kwonly_check__ = False

    def __new__(
        cls,
        *,
        addr: tuple[str, int],
        connection_timeout: float = 10.0,
        encoding: str = DEFAULT_ENCODING,
        health_port: int | None = None,
    ) -> Self:
        """Return existing instance or create new one."""
        # Delegate to parent with mapped parameters
        return super().__new__(
            cls,
            ip_addr=addr[0],
            port=addr[1],
            connection_timeout=connection_timeout,
            encoding=encoding,
            health_port=health_port,
        )

    def __init__(
        self,
        *,
        addr: tuple[str, int],
        connection_timeout: float = 10.0,
        encoding: str = DEFAULT_ENCODING,
        health_port: int | None = None,
    ) -> None:
        """Initialize the async CUxD server."""
        super().__init__(
            ip_addr=addr[0],
            port=addr[1],
            connection_timeout=connection_timeout,
            encoding=encoding,
            health_port=health_port,
        )
        self._devices: dict[str, dict[str, Any]] = {}

        # Default CUxD callback methods
        self.register_function(self.event, "event")
        self.register_function(self.newDevices, "newDevices")
        self.register_function(self.deleteDevices, "deleteDevices")
        self.register_function(self.listDevices, "listDevices")

    @property
    def devices(self) -> dict[str, dict[str, Any]]:
        """Return the device registry."""
        return self._devices

    # Default handlers (async versions) ----------------------------------------

    async def event(
        self,
        interface_id: str,
        address: str,
        datapoint: str,
        value: Any,
    ) -> str:
        """Fire an event to the registered callback."""
        _LOGGER.info("[EVENT] %s %s %s = %r", interface_id, address, datapoint, value)
        return ""

    async def newDevices(
        self,
        interface_id: str,
        devices: list[dict[str, Any]],
    ) -> str:
        """Add new devices to the registry."""
        for d in devices or []:
            if addr := str(d.get("ADDRESS")):
                self._devices[addr] = dict(d)
        _LOGGER.info(
            "[NEW_DEVICES] %s -> %d (now %d)",
            interface_id,
            len(devices or []),
            len(self._devices),
        )
        return ""

    async def deleteDevices(
        self,
        interface_id: str,
        addresses: list[str],
    ) -> str:
        """Remove devices from the registry."""
        for a in addresses or []:
            self._devices.pop(str(a), None)
        _LOGGER.info(
            "[DELETE_DEVICES] %s -> %r (now %d)",
            interface_id,
            addresses,
            len(self._devices),
        )
        return ""

    async def listDevices(self, *_: Any) -> list[dict[str, Any]]:
        """Return all registered devices."""
        return list(self._devices.values())


# =============================================================================
# Factory function
# =============================================================================


async def create_async_bin_rpc_server(
    *,
    ip_addr: str = IP_ANY_V4,
    port: int = PORT_ANY,
    connection_timeout: float = 10.0,
    encoding: str = DEFAULT_ENCODING,
    health_port: int | None = None,
) -> AsyncBinRpcServer:
    """Create and start an async BIN-RPC server."""
    server = AsyncBinRpcServer(
        ip_addr=ip_addr,
        port=port,
        connection_timeout=connection_timeout,
        encoding=encoding,
        health_port=health_port,
    )
    if not server.started:
        await server.start()
        _LOGGER.debug(
            "Created AsyncBinRpcServer listening on %s:%d",
            server.listen_ip_addr,
            server.listen_port,
        )
    return server
