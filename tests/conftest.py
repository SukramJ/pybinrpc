"""Helper functions used within pybinrpc."""

from __future__ import annotations

import threading
import time

import pytest

from pybinrpc_support.server import FakeServer


@pytest.fixture
async def fake_server() -> FakeServer:
    """Start fake CUxD."""
    server = FakeServer("127.0.0.1", 18701)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Give server a moment to start
    time.sleep(0.02)
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
