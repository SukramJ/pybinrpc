# SPDX-License-Identifier: MIT
# Copyright (c) 2021-2025 SukramJ
"""
Constants used by pybinrpc.

Public API of this module is defined by __all__.
"""

from __future__ import annotations

import inspect
from typing import Final

VERSION: Final = "2025.10.0"
DEFAULT_ENCODING = "utf-8"

# =============================================================================
# BIN-RPC wire constants & helpers
# =============================================================================

HDR_REQ = b"Bin" + b"\x00"
HDR_RES = b"Bin" + b"\x01"

T_INTEGER = 0x00000001
T_BOOL = 0x00000002
T_STRING = 0x00000003
T_DOUBLE = 0x00000004
T_ARRAY = 0x00000100
T_STRUCT = 0x00000101
T_BINARY = 0x0000000E


# Define public API for this module
__all__ = tuple(
    sorted(
        name
        for name, obj in globals().items()
        if not name.startswith("_")
        and (
            name.isupper()  # constants like VERSION, patterns, defaults
            or inspect.isclass(obj)  # Enums, dataclasses, TypedDicts, NamedTuple classes
            or inspect.isfunction(obj)  # module functions
        )
        and (
            getattr(obj, "__module__", __name__) == __name__
            if not isinstance(obj, int | float | str | bytes | tuple | frozenset | dict)
            else True
        )
    )
)
