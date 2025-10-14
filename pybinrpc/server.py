"""
Async BIN-RPC server implemented in the style of Python's xmlrpc library.

License: MIT
"""

from __future__ import annotations

from collections.abc import Callable
import contextlib
import logging
import socketserver
import struct
from typing import Any, Final

from pybinrpc.const import DEFAULT_ENCODING
from pybinrpc.support import dec_request, enc_response, recv_exact

_LOGGER: Final = logging.getLogger(__name__)


class SimpleBINRPCRequestHandler(socketserver.BaseRequestHandler):
    """
    Handle a single BIN-RPC request and return a response.

    This mimics `xmlrpc.server.SimpleXMLRPCRequestHandler` behaviour for one-shot
    request/response over a persistent TCP connection (per-connection).
    """

    def handle(self) -> None:
        """Handle a single BIN-RPC request."""
        server: SimpleBINRPCServer = self.server  # type: ignore[assignment]
        try:
            hdr = recv_exact(sock=self.request, n=8, timeout=server.timeout)
            # Be lenient: accept any frame that starts with b"Bin" (request/response marker varies)
            if hdr[:3] != b"Bin":
                raise ValueError("Invalid BIN-RPC header")
            total = struct.unpack(">I", hdr[4:8])[0]
            body = recv_exact(sock=self.request, n=total - 8, timeout=server.timeout)
            method, params = dec_request(frame=hdr + body, encoding=server.encoding)
            _LOGGER.info("HANDLE: Received BIN-RPC method: %s, params: %s", method, params)
            result = server._dispatch(method, params)  # pylint: disable=protected-access
            self.request.sendall(enc_response(ret=result, encoding=server.encoding))
        except Exception as exc:
            _LOGGER.warning("BIN-RPC handler error: %s", exc)
            with contextlib.suppress(Exception):
                self.request.sendall(enc_response(ret="", encoding=server.encoding))


class SimpleBINRPCServer(socketserver.ThreadingTCPServer):
    """
    Threaded BIN-RPC server in the style of `SimpleXMLRPCServer`.

    Methods can be registered via `register_function` and `register_instance`.
    Introspection and multicall may be enabled via `register_introspection_functions()`.

    Parameters
    ----------
    addr : tuple[str, int]
        (host, port) listen address.
    allow_none : bool
        Accepted for API compatibility; this server encodes None as empty-string
        result by default. Adjust as needed for your peer.
    timeout : float
        Per-connection read timeout in seconds.

    """

    __kwonly_check__ = False

    allow_reuse_address = True

    def __init__(
        self, addr: tuple[str, int], *, allow_none: bool = True, timeout: float = 10.0, encoding: str = DEFAULT_ENCODING
    ) -> None:
        """Initialize the server."""
        self.encoding = encoding
        super().__init__(addr, SimpleBINRPCRequestHandler)
        self.timeout: float = float(timeout)
        self._functions: dict[str, Callable[..., Any]] = {}
        self._instance: object | None = None
        self._enable_introspection = False

    # --- registration --------------------------------------------------------

    def register_function(self, func: Callable[..., Any], name: str | None = None) -> None:
        """Register a function under the given name (defaults to func.__name__)."""
        self._functions[name or func.__name__] = func

    def register_instance(self, instance: object, *, allow_dotted_names: bool = True) -> None:
        """Register an instance; public callables become exposed via dotted names."""
        self._instance = instance

    def register_introspection_functions(self) -> None:
        """Enable `system.listMethods`."""
        self._enable_introspection = True
        self.register_function(self.system_listMethods, "system.listMethods")

    def register_multicall_functions(self) -> None:
        """Enable `system.multicall`."""
        self.register_function(self.system_multicall, "system.multicall")

    # --- dispatch ------------------------------------------------------------

    def _resolve_instance_call(self, method: str) -> Callable[..., Any] | None:
        """Resolve a dotted method name to a callable."""
        if not self._instance:
            return None
        target = self._instance
        for part in method.split("."):
            if not hasattr(target, part):
                return None
            target = getattr(target, part)
        return target if callable(target) else None

    def _dispatch(self, method: str, params: list[Any]) -> Any:
        """Dispatch a method call."""
        fn = self._resolve_instance_call(method)
        if fn is None:
            fn = self._functions.get(method)
        if fn is None:
            if method == "ping":
                return "pong"
            _LOGGER.debug("Unhandled BIN-RPC method: %s", method)
            return ""
        try:
            return fn(*params)
        except Exception as exc:
            _LOGGER.warning("Error in handler %s: %s", method, exc)
            return ""

    # --- system.* ------------------------------------------------------------

    def system_listMethods(self) -> list[str]:
        """Return a list of all methods supported by the server."""
        if not self._enable_introspection:
            return []
        names = set(self._functions.keys())
        if self._instance is not None:
            for name in dir(self._instance):
                if name.startswith("_"):
                    continue
                attr = getattr(self._instance, name)
                if callable(attr):
                    names.add(name)
        return sorted(names)

    def system_multicall(self, calls: list[dict[str, Any]]) -> list[Any]:
        """Process a batch of method calls. Returns a list of results."""
        results: list[Any] = []
        for call in calls or []:
            try:
                name = str(call.get("methodName") or "")
                params = call.get("params", [])
                results.append(self._dispatch(method=name, params=params))
            except Exception as exc:
                _LOGGER.warning("Error in multicall entry: %s", exc)
                results.append("")
        return results


# =============================================================================
# CUxD convenience server
# =============================================================================


class CuxdServer(SimpleBINRPCServer):
    """Simple server with CUxD defaults and in-memory device registry."""

    __kwonly_check__ = False

    def __init__(self, *, addr: tuple[str, int], timeout: float = 10.0):
        """Initialize the server."""
        super().__init__(addr, timeout=timeout)
        self._devices: dict[str, dict[str, Any]] = {}
        # Default CUxD callback methods
        self.register_function(self.event, "event")
        self.register_function(self.newDevices, "newDevices")
        self.register_function(self.deleteDevices, "deleteDevices")
        self.register_function(self.listDevices, "listDevices")

    # Default handlers --------------------------------------------------------

    def event(self, interface_id: str, address: str, datapoint: str, value: Any) -> str:
        """Fire an event to the registered callback."""
        _LOGGER.info("[EVENT] %s %s %s = %r", interface_id, address, datapoint, value)
        return ""

    def newDevices(self, interface_id: str, devices: list[dict[str, Any]]) -> str:
        """Add new devices to the registry."""
        for d in devices or []:
            if addr := str(d.get("ADDRESS")):
                self._devices[addr] = dict(d)
        _LOGGER.info("[NEW_DEVICES] %s -> %d (now %d)", interface_id, len(devices or []), len(self._devices))
        return ""

    def deleteDevices(self, interface_id: str, addresses: list[str]) -> str:
        """Remove devices from the registry."""
        for a in addresses or []:
            self._devices.pop(str(a), None)
        _LOGGER.info("[DELETE_DEVICES] %s -> %r (now %d)", interface_id, addresses, len(self._devices))
        return ""

    def listDevices(self, *_: Any) -> list[dict[str, Any]]:
        """Return a static set of devices."""
        return list(self._devices.values())
