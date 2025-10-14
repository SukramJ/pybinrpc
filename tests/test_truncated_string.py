# SPDX-License-Identifier: MIT
# Copyright (c) 2021-2025 SukramJ
"""
Regression test: truncated BIN-RPC string payload should decode available bytes without raising.

This mirrors real-world frames from CUxD where the header declares a larger
payload than actually transmitted, causing strings to be cut short.
"""

from __future__ import annotations

from pybinrpc.const import HDR_REQ, T_STRING
from pybinrpc.support import _be_u32, dec_request  # type: ignore[attr-defined]


def build_truncated_string_request() -> bytes:
    """Build a BIN-RPC request frame with a truncated string value."""
    # Build body: method "echo" + 1 param (a string)
    body = bytearray()
    # method name
    body += _be_u32(len(b"echo")) + b"echo"
    # number of params
    body += _be_u32(1)
    # Append a string value with declared length 5 but only 2 bytes available
    body += _be_u32(T_STRING)  # type tag
    body += _be_u32(5)  # declared length
    body += b"ab"  # only 2 bytes actually present
    total = 8 + len(body)
    return HDR_REQ + _be_u32(total) + bytes(body)


def test_truncated_string_decodes_available_bytes() -> None:
    """Ensure that truncated strings are handled gracefully."""
    frame = build_truncated_string_request()
    method, params = dec_request(frame=frame, encoding="utf-8")
    assert method == "echo"
    assert isinstance(params, list)
    assert len(params) == 1
    # Expect the available bytes to be decoded ("ab"), no exception raised
    assert params[0] == "ab"
