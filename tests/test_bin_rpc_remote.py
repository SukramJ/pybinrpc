# SPDX-License-Identifier: MIT
# Copyright (c) 2021-2025 SukramJ
"""
Helper functions used within pybinrpc.

Public API of this module is defined by __all__.
"""

from __future__ import annotations

import os

import pytest

from pybinrpc.client import BinRpcServerProxy

# =============================================================================
# Tests (unittest)
# =============================================================================


async def test_serverproxy_init_set_get_remote() -> None:
    """
    Integration test against a real CUxD server (opt-in via env vars).

    Set environment variables to run this test:
      - CUXD_HOST: hostname or IP of the CUxD BIN-RPC server
      - CUXD_PORT: port number (e.g., 8701)
    Optional overrides:
      - CUXD_CALLBACK (default: xmlrpc_bin://127.0.0.1:19126)
      - CUXD_IFACE (default: iface-test)
      - CUXD_ADDRESS (default: CUX2801001:1)
      - CUXD_DATAPOINT (default: STATE)
    """
    host = os.getenv("CUXD_HOST")
    port = os.getenv("CUXD_PORT")
    if not host or not port:
        pytest.skip("CUXD_HOST/CUXD_PORT not set; skipping external CUxD integration test")

    callback = os.getenv("CUXD_CALLBACK", "xmlrpc_bin://127.0.0.1:19126")
    iface = os.getenv("CUXD_IFACE", "iface-test")
    address = os.getenv("CUXD_ADDRESS", "CUX3901001:1")
    datapoint = os.getenv("CUXD_DATAPOINT", "LEVEL")

    client = BinRpcServerProxy(host=host, port=int(port))
    try:
        ok = client.init(callback, iface)
        # Some CUxD variants may return an empty response to init; accept OK or empty/None
        assert ok in ("OK", "", None)
        client.setValue(address, datapoint, 1)
        val = client.getValue(address, datapoint)
        assert val == 0.8
    finally:
        client.init(callback)
