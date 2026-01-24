# SPDX-License-Identifier: MIT
# Copyright (c) 2021-2025 SukramJ
"""
PyBinRPC: a Python 3 library to interact with BinRPC backends.

Public API at the top-level package is defined by __all__.

This package provides a high-level API to discover devices and channels, read and write
parameters (data points), receive events, and manage programs and system variables.

Typical usage is to construct a CentralConfig, create a CentralUnit and start it, then
consume data points and events or issue write commands via the exposed API.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
from typing import Final

# Async server exports
from pybinrpc.async_server import AsyncBinRpcDispatcher, AsyncBinRpcServer, AsyncCuxdServer, create_async_bin_rpc_server

# Client exports
from pybinrpc.client import BinRpcServerProxy
from pybinrpc.const import VERSION

# Sync server exports (backwards compatibility)
from pybinrpc.server import CuxdServer, SimpleBINRPCRequestHandler, SimpleBINRPCServer

if sys.stdout.isatty():
    logging.basicConfig(level=logging.INFO)

__version__: Final = VERSION
_LOGGER: Final = logging.getLogger(__name__)


# pylint: disable=unused-argument
# noinspection PyUnusedLocal
def signal_handler(sig, frame):  # type: ignore[no-untyped-def]
    """Handle signal to shut down server."""
    _LOGGER.info("Got signal: %s. Shutting down server", str(sig))
    signal.signal(signal.SIGINT, signal.SIG_DFL)


if threading.current_thread() is threading.main_thread() and sys.stdout.isatty():
    signal.signal(signal.SIGINT, signal_handler)

# Define public API for the top-level package
__all__ = [
    "__version__",
    # Async API
    "AsyncBinRpcDispatcher",
    "AsyncBinRpcServer",
    "AsyncCuxdServer",
    "create_async_bin_rpc_server",
    # Sync API (backwards compatibility)
    "CuxdServer",
    "SimpleBINRPCRequestHandler",
    "SimpleBINRPCServer",
    # Client
    "BinRpcServerProxy",
]
