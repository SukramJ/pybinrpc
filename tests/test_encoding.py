# SPDX-License-Identifier: MIT
"""Tests for integer encoding, double precision, and recv_exact max_size."""

from __future__ import annotations

import struct
from unittest.mock import MagicMock

import pytest

from pybinrpc.const import T_INTEGER
from pybinrpc.support import _enc_double_parts, dec_data, enc_data, enc_integer, recv_exact


def test_enc_integer_negative() -> None:
    """Negative integers are correctly encoded as signed 32-bit."""
    encoded = enc_integer(n=-1)
    # Type tag (4 bytes) + value (4 bytes)
    assert len(encoded) == 8
    type_tag = struct.unpack(">I", encoded[:4])[0]
    assert type_tag == T_INTEGER
    value = struct.unpack(">i", encoded[4:8])[0]
    assert value == -1


def test_enc_integer_negative_roundtrip() -> None:
    """Negative integers roundtrip correctly through encode/decode."""
    for n in [-1, -100, -2147483648]:
        encoded = enc_data(v=n, encoding="utf-8")
        decoded, _ = dec_data(buf=memoryview(encoded), ofs=0, encoding="utf-8")
        assert decoded == n, f"Roundtrip failed for {n}: got {decoded}"


def test_enc_integer_overflow_clamps() -> None:
    """Values beyond signed 32-bit range are clamped."""
    # Value > 2^31-1 should be clamped to 2147483647
    encoded = enc_integer(n=2**32)
    value = struct.unpack(">i", encoded[4:8])[0]
    assert value == 2147483647

    # Value < -2^31 should be clamped to -2147483648
    encoded = enc_integer(n=-(2**32))
    value = struct.unpack(">i", encoded[4:8])[0]
    assert value == -2147483648


def test_double_precision_six_digits() -> None:
    """Values with 5-6 decimal digits roundtrip correctly."""
    for val in [0.123456, 0.999999, 0.000001, 3.141593]:
        m, e = _enc_double_parts(value=val)
        reconstructed = round((float(m) / float(1 << 30)) * (2**e), 6)
        assert reconstructed == round(val, 6), f"Precision loss for {val}: got {reconstructed}"


def test_recv_exact_max_size_rejects() -> None:
    """recv_exact raises ValueError when n exceeds max_size."""
    mock_sock = MagicMock()
    with pytest.raises(ValueError, match="exceeds limit"):
        recv_exact(sock=mock_sock, n=3_000_000, timeout=1.0, max_size=2_000_000)


def test_recv_exact_max_size_zero_unlimited() -> None:
    """recv_exact with max_size=0 does not enforce a limit."""
    mock_sock = MagicMock()
    # Simulate receiving data
    mock_sock.recv.return_value = b"\x00" * 100
    result = recv_exact(sock=mock_sock, n=100, timeout=1.0, max_size=0)
    assert len(result) == 100
