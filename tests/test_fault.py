# SPDX-License-Identifier: MIT
"""Tests for fault frame encoding/decoding and response format variants."""

from __future__ import annotations

import pytest

from pybinrpc.exceptions import BinRpcFaultError
from pybinrpc.support import dec_response, enc_fault, enc_response


def test_enc_fault_roundtrip() -> None:
    """enc_fault produces a frame that dec_response raises BinRpcFaultError with correct fields."""
    frame = enc_fault(fault_code=42, fault_string="something broke", encoding="utf-8")
    with pytest.raises(BinRpcFaultError) as exc_info:
        dec_response(frame=frame, encoding="utf-8")
    assert exc_info.value.fault_code == 42
    assert exc_info.value.fault_string == "something broke"


def test_dec_response_detects_fault_frame() -> None:
    """A fault frame with 0xFF marker raises BinRpcFaultError."""
    frame = enc_fault(fault_code=-1, fault_string="test error", encoding="utf-8")
    assert frame[3] == 0xFF
    with pytest.raises(BinRpcFaultError) as exc_info:
        dec_response(frame=frame, encoding="utf-8")
    assert exc_info.value.fault_code == -1
    assert exc_info.value.fault_string == "test error"


def test_dec_response_no_status_field() -> None:
    """Response without status field decodes correctly (type tag directly after header)."""
    # enc_response now writes without status field
    frame = enc_response(ret="hello", encoding="utf-8")
    result = dec_response(frame=frame, encoding="utf-8")
    assert result == "hello"


def test_dec_response_with_legacy_status_field() -> None:
    """Response with legacy status=0x00000000 prefix decodes correctly."""
    from pybinrpc.const import HDR_RES
    from pybinrpc.support import _be_u32, enc_data

    payload = enc_data(v="world", encoding="utf-8")
    # Manually construct a legacy frame with 4-byte status=0 prefix
    body = _be_u32(n=0) + payload
    total = 8 + len(body)
    frame = HDR_RES + _be_u32(n=total) + body
    result = dec_response(frame=frame, encoding="utf-8")
    assert result == "world"


def test_dec_response_empty_body() -> None:
    """Response with empty body returns None."""
    from pybinrpc.const import HDR_RES
    from pybinrpc.support import _be_u32

    frame = HDR_RES + _be_u32(n=8)  # total=8 means 0 bytes body
    result = dec_response(frame=frame, encoding="utf-8")
    assert result is None
