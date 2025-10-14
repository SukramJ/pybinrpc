"""Async BIN-RPC client and server implemented in the style of Python's xmlrpc library."""

from __future__ import annotations

import contextlib
import logging
import socket
import ssl
import struct
import threading
from typing import Any, Final, Self

from pybinrpc.const import DEFAULT_ENCODING
from pybinrpc.support import dec_response, enc_request, recv_exact

_LOGGER: Final = logging.getLogger(__name__)


# =============================================================================
# Transport & ServerProxy-like API
# =============================================================================


class _Method:
    """
    Callable method proxy used by `BinRpcServerProxy`.

    Attribute access composes dotted names; calling performs a synchronous
    BIN-RPC request with that method name.
    """

    __kwonly_check__ = False

    def __init__(self, transport: _Transport, name: str):
        """Initialize the method proxy."""
        self._t = transport
        self._name = name

    def __getattr__(self, item: str) -> _Method:
        """Return a new method proxy with the given name."""
        return _Method(transport=self._t, name=f"{self._name}.{item}")

    def __call__(self, *params: Any) -> Any:
        """Call the BIN-RPC method with the given parameters."""
        return self._t.call(method=self._name, params=list(params))


class _Transport:
    """
    Thin synchronous transport with optional keep-alive and TLS.

    Parameters
    ----------
    host : str
        Remote host/IP.
    port : int
        Remote port (e.g., CUxD BIN-RPC is typically 8701).
    timeout : float
        Connect/read/write timeout in seconds.
    keep_alive : bool
        If True, reuse a single TCP connection and serialize requests.
    encoding : str
        Encoding for (de)serialization.
    tls : bool | ssl.SSLContext
        If True or an SSLContext is provided, wrap the socket with TLS.
    server_hostname : str | None
        Optional SNI server hostname to use when TLS is enabled.
    tls_verify : bool
        When tls is True (boolean), control certificate verification and hostname checking.

    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        timeout: float,
        keep_alive: bool,
        encoding: str = DEFAULT_ENCODING,
        tls: bool | ssl.SSLContext = False,
        tls_verify: bool = True,
    ):
        """Initialize the transport."""
        self._host = host
        self._port = int(port)
        self._timeout = float(timeout)
        self._keep_alive = bool(keep_alive)
        self._tls = tls
        self._tls_verify = bool(tls_verify)
        self._encoding = encoding
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()

    def _wrap_tls(self, *, s: socket.socket) -> socket.socket:
        if not self._tls:
            return s
        if isinstance(self._tls, ssl.SSLContext):
            ctx = self._tls
        else:
            ctx = ssl.create_default_context()
            # Explicitly only allow TLSv1.2 and higher
            if hasattr(ctx, "minimum_version") and hasattr(ssl, "TLSVersion"):
                ctx.minimum_version = ssl.TLSVersion.TLSv1_2  # Python 3.7+
            # For legacy Python, disable TLS <1.2 if possible
            # Only set ctx.options if the attribute exists on the context
            elif hasattr(ctx, "options"):
                if hasattr(ssl, "OP_NO_TLSv1"):
                    ctx.options |= ssl.OP_NO_TLSv1
                if hasattr(ssl, "OP_NO_TLSv1_1"):
                    ctx.options |= ssl.OP_NO_TLSv1_1
            if not self._tls_verify:
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
        # Determine SNI: None for IP literals, host for names
        server_hostname: str | None = None
        try:
            socket.inet_aton(self._host)
            is_ip = True
        except OSError:
            is_ip = False
        if not is_ip:
            server_hostname = self._host
        return ctx.wrap_socket(s, server_hostname=server_hostname)

    def _ensure_sock(self) -> socket.socket:
        """Ensure a connection is open and return the socket."""
        if not self._keep_alive or self._sock is None:
            base = socket.create_connection((self._host, self._port), timeout=self._timeout)
            s = self._wrap_tls(s=base)
            if not self._keep_alive:
                return s
            self._sock = s
        return self._sock

    def _close(self) -> None:
        """Close the socket if it exists."""
        if self._sock is not None:
            with contextlib.suppress(Exception):
                self._sock.close()
            self._sock = None

    def call(self, method: str, params: list[Any]) -> Any:  # kwonly: disable
        """Send a BIN-RPC request and return the response."""
        _LOGGER.info("CALL: %s(%s)", method, params)
        frame = enc_request(method=method, params=params, encoding=self._encoding)
        if self._keep_alive:
            with self._lock:
                for attempt in range(2):
                    s = self._ensure_sock()
                    try:
                        s.sendall(frame)
                        hdr = recv_exact(sock=s, n=8, timeout=self._timeout)
                        total = struct.unpack(">I", hdr[4:8])[0]
                        body = recv_exact(sock=s, n=total - 8, timeout=self._timeout)
                        return dec_response(frame=hdr + body, encoding=self._encoding)
                    except Exception:
                        # Drop broken keep-alive and retry once with a new connection
                        self._close()
                        if attempt == 0:
                            continue
                        raise
        else:
            for attempt in range(2):
                s = self._ensure_sock()
                try:
                    s.sendall(frame)
                    hdr = recv_exact(sock=s, n=8, timeout=self._timeout)
                    total = struct.unpack(">I", hdr[4:8])[0]
                    body = recv_exact(sock=s, n=total - 8, timeout=self._timeout)
                    return dec_response(frame=hdr + body, encoding=self._encoding)
                except Exception:
                    # close this short‑lived socket and retry once with a fresh connection
                    with contextlib.suppress(Exception):
                        s.close()
                    if attempt == 0:
                        continue
                    raise
                finally:
                    # Ensure the socket is closed if we didn't return successfully in this iteration
                    with contextlib.suppress(Exception):
                        if s is not None:
                            s.close()


class BinRpcServerProxy:
    """
    Synchronous BIN-RPC client modeled after `xmlrpc.client.ServerProxy`.

    Example:
    -------
    >>> proxy = BinRpcServerProxy("192.168.0.10", 8701, timeout=5.0, keep_alive=True)
    >>> proxy.init("xmlrpc_bin://192.168.0.20:9126", "python-iface")
    'OK'  # implementation-dependent
    >>> proxy.system.multicall([{"methodName": "ping", "params": []}])
    ['pong']

    The object supports dotted methods via attribute access just like
    `xmlrpc.client.ServerProxy` (e.g. `proxy.system.multicall([...])`).

    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        encoding: str = DEFAULT_ENCODING,
        keep_alive: bool = True,
        timeout: float = 5.0,
        tls: bool | ssl.SSLContext = False,
        tls_verify: bool = True,
    ):
        """Initialize the transport."""
        # Configure encoding globally for (de)serialization
        self._t = _Transport(
            host=host,
            port=port,
            timeout=timeout,
            keep_alive=keep_alive,
            tls=tls,
            tls_verify=tls_verify,
            encoding=encoding,
        )

    def __getattr__(self, name: str) -> _Method:  # kwonly: disable
        """Return a method proxy for the given name."""
        return _Method(transport=self._t, name=name)

    # Context manager for explicit resource control
    def __enter__(self) -> Self:  # kwonly: disable
        """Enter the context manager."""
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:  # kwonly: disable
        """Exit the context manager."""
        self.close()

    def close(self) -> None:
        """Close the underlying keep-alive connection, if any."""
        self._t._close()  # pylint: disable=protected-access
