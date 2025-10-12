# SPDX-License-Identifier: MIT
# Copyright (c) 2021-2025 SukramJ
"""
TLS-related tests for BinRpcServerProxy transport.

We avoid spinning up a real TLS server by unit-testing the internal
_transport TLS wrapping logic with monkeypatched ssl.create_default_context.
"""

from __future__ import annotations

import ssl
from typing import Any

import pytest

from pybinrpc.client import _Transport


class _FakeSocket:
    pass


class _FakeSSLContext:
    def __init__(self) -> None:
        """Initialize the SSL context."""
        # mimic defaults of ssl.create_default_context
        self.check_hostname: bool = True
        self.verify_mode: ssl.VerifyMode = ssl.CERT_REQUIRED
        self.wrap_calls: list[dict[str, Any]] = []

    def wrap_socket(self, sock: Any, server_hostname: str | None = None):  # noqa: D401
        """Wrap the socket."""
        # Record the call and return a sentinel object
        self.wrap_calls.append({"sock": sock, "server_hostname": server_hostname})
        return (sock, server_hostname)  # simple sentinel to identify wrapping


@pytest.mark.asyncio
async def test_transport_no_tls_does_not_wrap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that when tls=False, the socket is returned unmodified."""
    calls = {"created": 0}

    def _fake_create_default_context(*args: Any, **kwargs: Any) -> _FakeSSLContext:  # noqa: ARG001
        calls["created"] += 1
        return _FakeSSLContext()

    monkeypatch.setattr(ssl, "create_default_context", _fake_create_default_context)

    t = _Transport(host="127.0.0.1", port=1234, timeout=1.0, keep_alive=False, tls=False)
    sock = _FakeSocket()
    out = t._wrap_tls(s=sock)  # pylint: disable=protected-access
    assert out is sock
    assert calls["created"] == 0  # no SSLContext constructed when TLS is disabled


@pytest.mark.asyncio
async def test_transport_tls_verify_false_disables_verification_and_sets_sni(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that when tls=True and tls_verify=False, the SSL context disables verification and sets SNI."""
    ctx = _FakeSSLContext()

    def _fake_create_default_context(*args: Any, **kwargs: Any) -> _FakeSSLContext:  # noqa: ARG001
        return ctx

    monkeypatch.setattr(ssl, "create_default_context", _fake_create_default_context)

    t = _Transport(host="example.com", port=1234, timeout=1.0, keep_alive=False, tls=True, tls_verify=False)
    sock = _FakeSocket()
    wrapped = t._wrap_tls(s=sock)  # pylint: disable=protected-access

    # TLS context adjusted
    assert ctx.check_hostname is False
    assert ctx.verify_mode == ssl.CERT_NONE

    # wrap_socket was called once with SNI set to host (since it's not an IP)
    assert wrapped == (sock, "example.com")
    assert len(ctx.wrap_calls) == 1
    assert ctx.wrap_calls[0]["server_hostname"] == "example.com"


@pytest.mark.asyncio
async def test_transport_tls_verify_true_keeps_verification_and_sets_sni(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that when tls=True and tls_verify=True, the SSL context keeps verification and sets SNI."""
    ctx = _FakeSSLContext()

    def _fake_create_default_context(*args: Any, **kwargs: Any) -> _FakeSSLContext:  # noqa: ARG001
        return ctx

    monkeypatch.setattr(ssl, "create_default_context", _fake_create_default_context)

    t = _Transport(host="my.server.local", port=1234, timeout=1.0, keep_alive=False, tls=True, tls_verify=True)
    sock = _FakeSocket()
    wrapped = t._wrap_tls(s=sock)  # pylint: disable=protected-access

    # TLS context should keep defaults
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED

    # wrap_socket called with SNI set to host
    assert wrapped == (sock, "my.server.local")
    assert len(ctx.wrap_calls) == 1
    assert ctx.wrap_calls[0]["server_hostname"] == "my.server.local"


@pytest.mark.asyncio
async def test_transport_tls_with_ip_disables_sni(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that when tls=True and host is an IP literal, SNI is disabled."""
    ctx = _FakeSSLContext()

    def _fake_create_default_context(*args: Any, **kwargs: Any) -> _FakeSSLContext:  # noqa: ARG001
        return ctx

    monkeypatch.setattr(ssl, "create_default_context", _fake_create_default_context)

    t = _Transport(host="127.0.0.1", port=1234, timeout=1.0, keep_alive=False, tls=True, tls_verify=True)
    sock = _FakeSocket()
    wrapped = t._wrap_tls(s=sock)  # pylint: disable=protected-access

    # For IP literals, SNI must be None
    assert wrapped == (sock, None)
    assert len(ctx.wrap_calls) == 1
    assert ctx.wrap_calls[0]["server_hostname"] is None
