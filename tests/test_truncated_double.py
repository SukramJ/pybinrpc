# SPDX-License-Identifier: MIT
# Copyright (c) 2021-2025 SukramJ
"""
Regression test: ensure truncated BIN-RPC double payloads do not crash decoder.

This simulates a CUxD event frame where the double value is truncated so that
only the exponent is present and the mantissa is missing. The decoder should be
lenient, returning 0.0 for the value and not raising struct errors.
"""

from __future__ import annotations

import struct

from pybinrpc.const import HDR_REQ, T_DOUBLE
from pybinrpc.support import _be_u32, dec_request, enc_string  # type: ignore[attr-defined]


def build_truncated_double_event_frame(encoding: str = "utf-8") -> bytes:
    """Build a BIN-RPC request frame with a truncated double value."""
    # Build body: method "event" + 4 params (iface, address, datapoint, value)
    body = bytearray()
    # method name
    body += _be_u32(len(b"event")) + b"event"
    # number of params
    body += _be_u32(4)
    # iface, address, datapoint as proper strings
    body += enc_string(s="iface-test", encoding=encoding)
    body += enc_string(s="CUX2801001:1", encoding=encoding)
    body += enc_string(s="LEVEL", encoding=encoding)
    # Now append a truncated double: type tag + exponent only (no mantissa)
    body += _be_u32(T_DOUBLE)
    body += struct.pack(">i", 0)  # exponent present
    # Intentionally omit the 4-byte mantissa to simulate truncation
    total = 8 + len(body)
    frame = HDR_REQ + _be_u32(total) + bytes(body)
    assert frame
    return frame


def test_truncated_double_decoding_does_not_crash() -> None:
    """Ensure that truncated doubles are handled gracefully."""
    frame = build_truncated_double_event_frame()
    method, params = dec_request(frame=frame, encoding="utf-8")
    assert method == "event"
    # We expect 4 params, with the last one decoded as 0.0 due to truncation leniency
    # Depending on how the decoder advances at the end, it should either deliver 0.0
    # or, in worst case, an empty string if the type tag itself were missing. Here,
    # we provided the type tag and exponent, so 0.0 is expected.
    assert len(params) == 4
    assert params[-1] == 0.0
