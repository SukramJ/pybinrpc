# SPDX-License-Identifier: MIT
# Copyright (c) 2021-2025 SukramJ
"""
Helper functions used within pybinrpc.

Public API of this module is defined by __all__.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
import socket
import struct
from typing import Any

from pybinrpc.const import DEFAULT_ENCODING, HDR_REQ, HDR_RES, T_ARRAY, T_BOOL, T_DOUBLE, T_INTEGER, T_STRING, T_STRUCT


def _be_u32(n: int) -> bytes:
    """Encode an unsigned 32-bit integer as big-endian bytes."""
    return struct.pack(">I", n)


def _rd_u32(buf: memoryview, ofs: int) -> tuple[int, int]:
    """Decode an unsigned 32-bit integer from big-endian bytes."""
    return struct.unpack_from(">I", buf, ofs)[0], ofs + 4


def _b(*, s: str, encoding: str) -> bytes:
    """Encode a string as bytes using the configured encoding."""
    return s.encode(encoding=encoding, errors="strict")


# --- encoders


def enc_string(*, s: str, encoding: str) -> bytes:
    """Encode a string as a BIN-RPC string."""
    b = _b(s=s, encoding=encoding)
    return _be_u32(n=T_STRING) + _be_u32(n=len(b)) + b


def enc_bool(*, v: bool) -> bytes:
    """Encode a boolean as a BIN-RPC boolean."""
    return _be_u32(n=T_BOOL) + (b"\x01" if v else b"\x00")


def enc_integer(*, n: int) -> bytes:
    """Encode an integer as a BIN-RPC integer."""
    return _be_u32(n=T_INTEGER) + _be_u32(n=int(n) & 0xFFFFFFFF)


def _enc_double_parts(*, value: float) -> tuple[int, int]:
    """Encode a double as a BIN-RPC double."""
    # value ≈ (mantissa / 2^30) * (2^exponent)
    if value == 0.0:
        return 0, 0

    exponent = int(math.floor(math.log(abs(value), 2)) + 1)
    mantissa = int((value * (2 ** (-exponent))) * (1 << 30))
    return mantissa, exponent


def enc_double(*, v: float) -> bytes:
    """Encode a double as a BIN-RPC double."""
    m, e = _enc_double_parts(value=float(v))
    return _be_u32(T_DOUBLE) + struct.pack(">iI", e, m & 0xFFFFFFFF)


def enc_array(*, a: Sequence[Any], encoding: str) -> bytes:
    """Encode an array as a BIN-RPC array."""
    out = bytearray()
    out += _be_u32(n=T_ARRAY)
    out += _be_u32(n=len(a))
    for el in a:
        out += enc_data(v=el, encoding=encoding)
    return bytes(out)


def enc_struct(*, d: Mapping[str, Any], encoding: str) -> bytes:
    """Encode a struct as a BIN-RPC struct."""
    out = bytearray()
    out += _be_u32(n=T_STRUCT)
    out += _be_u32(n=len(d))
    for k, v in d.items():
        kb = _b(s=str(k), encoding=encoding)
        out += _be_u32(n=len(kb)) + kb
        out += enc_data(v=v, encoding=encoding)
    return bytes(out)


def enc_data(*, v: Any, encoding: str) -> bytes:
    """Encode any data type as a BIN-RPC data type."""
    if isinstance(v, bool):
        return enc_bool(v=v)
    if isinstance(v, int) and not isinstance(v, bool):
        return enc_integer(n=v)
    if isinstance(v, float):
        return enc_double(v=v)
    if isinstance(v, str):
        return enc_string(s=v, encoding=encoding)
    if isinstance(v, (list, tuple)):
        return enc_array(a=list(v), encoding=encoding)
    if isinstance(v, dict):
        return enc_struct(d=v, encoding=encoding)
    return enc_string(s=str(v), encoding=encoding)


def enc_request(*, method: str, params: list[Any], encoding: str) -> bytes:
    """Encode a request frame as a BIN-RPC request frame."""
    body = bytearray()
    m = _b(s=method, encoding=encoding)
    body += _be_u32(n=len(m)) + m
    body += _be_u32(n=len(params))
    for p in params:
        body += enc_data(v=p, encoding=encoding)
    total = 8 + len(body)
    return HDR_REQ + _be_u32(n=total) + body


def enc_response(*, ret: Any, encoding: str) -> bytes:
    """Encode a response frame as a BIN-RPC response frame."""
    payload = enc_string(s="", encoding=encoding) if ret is None else enc_data(v=ret, encoding=encoding)
    body = _be_u32(n=0) + payload
    total = 8 + len(body)
    return HDR_RES + _be_u32(n=total) + body


# --- decoders


def _dec_double(*, buf: memoryview, ofs: int) -> tuple[float, int]:
    """Decode a double from a BIN-RPC double."""
    e, ofs = struct.unpack_from(">i", buf, ofs)[0], ofs + 4
    mu32, ofs = _rd_u32(buf=buf, ofs=ofs)
    return (float(mu32) / float(1 << 30)) * (2**e), ofs


def _dec_string(*, buf: memoryview, ofs: int, encoding: str) -> tuple[str, int]:
    """Decode a string from a BIN-RPC string using the configured encoding."""
    length, ofs = _rd_u32(buf=buf, ofs=ofs)
    s = bytes(buf[ofs : ofs + length]).decode(encoding, errors="replace")
    return s, ofs + length


def _dec_bool(*, buf: memoryview, ofs: int) -> tuple[bool, int]:
    """Decode a boolean from a BIN-RPC boolean."""
    return (buf[ofs] == 1), ofs + 1


def _dec_int(*, buf: memoryview, ofs: int) -> tuple[int, int]:
    """Decode an integer from a BIN-RPC integer."""
    v, ofs = _rd_u32(buf=buf, ofs=ofs)
    if v & 0x80000000:
        v = -((~v + 1) & 0xFFFFFFFF)
    return v, ofs


def dec_data(*, buf: memoryview, encoding: str, ofs: int = 0) -> tuple[Any, int]:
    """Decode data from a BIN-RPC data type."""
    t, ofs = _rd_u32(buf=buf, ofs=ofs)
    if t == T_STRING:
        return _dec_string(buf=buf, ofs=ofs, encoding=encoding)
    if t == T_BOOL:
        return _dec_bool(buf=buf, ofs=ofs)
    if t == T_INTEGER:
        return _dec_int(buf=buf, ofs=ofs)
    if t == T_DOUBLE:
        return _dec_double(buf=buf, ofs=ofs)
    if t == T_ARRAY:
        n, ofs = _rd_u32(buf=buf, ofs=ofs)
        outl: list[Any] = []
        for _ in range(n):
            val, ofs = dec_data(buf=buf, encoding=encoding, ofs=ofs)
            outl.append(val)
        return outl, ofs
    if t == T_STRUCT:
        n, ofs = _rd_u32(buf=buf, ofs=ofs)
        outd: dict[str, Any] = {}
        for _ in range(n):
            key, ofs = _dec_string(buf=buf, ofs=ofs, encoding=encoding)
            val, ofs = dec_data(buf=buf, encoding=encoding, ofs=ofs)
            outd[key] = val
        return outd, ofs
    raise ValueError(f"Unsupported BIN-RPC type 0x{t:08X}")


def dec_request(*, frame: bytes, encoding: str) -> tuple[str, list[Any]]:
    """Decode a request frame as a BIN-RPC request frame."""
    if len(frame) < 8 or frame[:4] != HDR_REQ[:4] or frame[4:8] != _be_u32(len(frame)):
        raise ValueError("Invalid BIN-RPC request frame")
    body = memoryview(frame)[8:]
    ofs = 0
    method, ofs = _dec_string(buf=body, ofs=ofs, encoding=encoding)
    n, ofs = _rd_u32(body, ofs)
    params: list[Any] = []
    for _ in range(n):
        v, ofs = dec_data(buf=body, ofs=ofs, encoding=encoding)
        params.append(v)
    return method, params


def dec_response(*, frame: bytes) -> Any:
    """
    Decode a response frame as a BIN-RPC response frame.

    The response body starts with a 32-bit status code (0 == OK), followed by
    an encoded BIN-RPC value. We ignore non-zero status for now (protocols may
    vary) and always attempt to decode the payload if present.
    """
    if len(frame) < 8 or frame[:4] != HDR_RES[:4] or frame[4:8] != _be_u32(n=len(frame)):
        raise ValueError("Invalid BIN-RPC response frame")
    body = memoryview(frame)[8:]
    ofs = 0
    _status, ofs = _rd_u32(buf=body, ofs=ofs)
    # If there's no payload after the status field, return None
    if ofs >= len(body):
        return None
    v, _ = dec_data(buf=body, ofs=ofs, encoding=DEFAULT_ENCODING)
    return v


def recv_exact(*, sock: socket.socket, n: int, timeout: float) -> bytes:
    """Receive exactly n bytes from the socket, raising IOError if connection closed."""
    sock.settimeout(timeout)
    data = bytearray()
    while len(data) < n:
        if not (chunk := sock.recv(n - len(data))):
            raise OSError("Connection closed while receiving")
        data += chunk
    return bytes(data)
