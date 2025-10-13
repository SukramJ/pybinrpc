# SPDX-License-Identifier: MIT
# Copyright (c) 2021-2025 SukramJ
"""Encoding tests for UTF-8."""

from __future__ import annotations

from pybinrpc.client import BinRpcServerProxy
from pybinrpc_support.server import FakeServer


async def test_utf8_roundtrip_in_params_and_values(fake_server: FakeServer) -> None:
    """Ensure UTF-8 multi-byte strings are not shortened or mangled end-to-end."""
    assert fake_server
    client = BinRpcServerProxy(host="127.0.0.1", port=18701, timeout=2.0, keep_alive=True)

    # Use multi-byte strings (umlauts and emoji)
    address = "CUXäöü:1"
    datapoint = "NÄME"
    value = "Grüße 🌍"

    # Round-trip set/get
    client.setValue(address, datapoint, value)
    got = client.getValue(address, datapoint)

    assert got == value


async def test_utf8_struct_and_array(fake_server: FakeServer) -> None:
    """Ensure struct keys and array elements with UTF-8 are handled correctly."""
    assert fake_server
    client = BinRpcServerProxy(host="127.0.0.1", port=18701, timeout=2.0)

    # We'll pack UTF-8 data in a struct via setValue and verify with getValue
    address = "CUXßΩ:2"
    datapoint = "DATÄ🎛"
    complex_value = {
        "schlüssel": "värt",
        "emoji": "🧪",
        "arr": ["eins", "zwei", "drei", "四"],
    }

    client.setValue(address, datapoint, complex_value)
    got = client.getValue(address, datapoint)

    assert isinstance(got, dict)
    assert got == complex_value
