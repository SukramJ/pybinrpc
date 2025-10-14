# SPDX-License-Identifier: MIT
# Copyright (c) 2021-2025 SukramJ
"""
Helper functions used within pybinrpc.

Public API of this module is defined by __all__.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import logging
import math
import socket
import struct
from typing import Any, Final

from pybinrpc.const import HDR_REQ, HDR_RES, T_ARRAY, T_BINARY, T_BOOL, T_DOUBLE, T_INTEGER, T_STRING, T_STRUCT

_LOGGER: Final = logging.getLogger(__name__)


def _be_u32(n: int) -> bytes:
    """Encode an unsigned 32-bit integer as big-endian bytes."""
    return struct.pack(">I", n)


def _rd_u32(buf: memoryview, ofs: int) -> tuple[int, int]:
    """Decode an unsigned 32-bit integer from big-endian bytes with bounds check."""
    if ofs + 4 > len(buf):
        raise ValueError(f"Truncated BIN-RPC buffer (need 4 bytes at {ofs}, have {len(buf)})")
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


def enc_binary(*, v: bytes) -> bytes:
    """Encode raw bytes as a BIN-RPC binary value (T_BINARY)."""
    return _be_u32(n=T_BINARY) + _be_u32(n=len(v)) + v


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
    if isinstance(v, (bytes, bytearray, memoryview)):
        return enc_binary(v=bytes(v))
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
    """
    Decode a double from a BIN-RPC double.

    Compatible with hobbyquaker/binrpc protocol.js: exponent and mantissa are
    32-bit signed integers; value = (mantissa / 2^30) * 2^exponent.

    Be lenient with truncated payloads (e.g., from some CCU/CuxD frames): if the
    exponent or mantissa is incomplete, return 0.0 and advance to the end of the
    buffer instead of raising, to avoid noisy server warnings.
    Additionally, normalize minor floating point noise by rounding to a
    reasonable precision so that common values like 0.8 round-trip cleanly.
    """
    # Need 4 bytes for exponent (signed 32-bit)
    if ofs + 4 > len(buf):
        _LOGGER.debug(
            "Truncated BIN-RPC buffer while reading double exponent (available=%d)",
            max(0, len(buf) - ofs),
        )
        return 0.0, len(buf)
    e, ofs = struct.unpack_from(">i", buf, ofs)[0], ofs + 4
    # Need 4 bytes for mantissa (signed 32-bit)
    if ofs + 4 > len(buf):
        _LOGGER.debug(
            "Truncated BIN-RPC buffer while reading double mantissa (available=%d)",
            max(0, len(buf) - ofs),
        )
        return 0.0, len(buf)
    m, ofs = struct.unpack_from(">i", buf, ofs)[0], ofs + 4
    val = (float(m) / float(1 << 30)) * (2**e)
    # Enforce small rounding to mitigate fixed-point conversion noise.
    return round(val, 4), ofs


def _dec_string(*, buf: memoryview, ofs: int, encoding: str) -> tuple[str, int]:
    """
    Decode a string from a BIN-RPC string using the configured encoding.

    Be lenient with peers that sometimes advertise a length larger than the
    remaining buffer (observed with some CCU/CuxD implementations). In that
    case, decode the available bytes and advance to the end of the buffer
    instead of raising, to avoid noisy server warnings.
    """
    length, ofs = _rd_u32(buf=buf, ofs=ofs)
    # If the payload is truncated, decode what we have and advance to the end.
    if (end := ofs + length) > len(buf):
        avail = max(0, len(buf) - ofs)
        s = bytes(buf[ofs : ofs + avail]).decode(encoding, errors="replace")
        _LOGGER.debug(
            "Truncated BIN-RPC string payload (declared=%d, available=%d) — decoding available bytes",
            length,
            avail,
        )
        return s, len(buf)
    s = bytes(buf[ofs:end]).decode(encoding, errors="replace")
    return s, end


def _dec_bool(*, buf: memoryview, ofs: int) -> tuple[bool, int]:
    """
    Decode a boolean from a BIN-RPC boolean.

    Be lenient with truncated payloads: if the single byte is missing, return
    False and advance to the end of the buffer instead of raising, to avoid
    noisy server warnings.
    """
    if ofs >= len(buf):
        _LOGGER.debug("Truncated BIN-RPC buffer while reading boolean (available=0)")
        return False, len(buf)
    return (buf[ofs] == 1), ofs + 1


def _dec_binary(*, buf: memoryview, ofs: int) -> tuple[bytes, int]:
    """
    Decode raw bytes from a BIN-RPC binary value (T_BINARY).

    Be lenient with truncated payloads:
    - If the 4-byte length field itself is truncated, return empty bytes and
      advance to the end of the buffer.
    - If the declared payload is longer than the remaining buffer, return the
      available bytes and advance to the end of the buffer instead of raising.
    """
    # Ensure we have the 4-byte length field
    if ofs + 4 > len(buf):
        _LOGGER.debug(
            "Truncated BIN-RPC buffer while reading binary length (available=%d)",
            max(0, len(buf) - ofs),
        )
        return b"", len(buf)
    length, ofs = _rd_u32(buf=buf, ofs=ofs)  # 4-byte length
    if (end := ofs + length) > len(buf):
        avail = max(0, len(buf) - ofs)
        data = bytes(buf[ofs : ofs + avail])
        _LOGGER.debug(
            "Truncated BIN-RPC binary payload (declared=%d, available=%d) — returning available bytes",
            length,
            avail,
        )
        return data, len(buf)
    data = bytes(buf[ofs:end])  # raw bytes
    return data, end


def _dec_int(*, buf: memoryview, ofs: int) -> tuple[int, int]:
    """
    Decode an integer from a BIN-RPC integer.

    Be lenient with truncated payloads: if fewer than 4 bytes remain, return 0
    and advance to the end of the buffer instead of raising, to avoid noisy
    server warnings.
    """
    if ofs + 4 > len(buf):
        _LOGGER.debug(
            "Truncated BIN-RPC buffer while reading integer (available=%d)",
            max(0, len(buf) - ofs),
        )
        return 0, len(buf)
    v, ofs = _rd_u32(buf=buf, ofs=ofs)
    if v & 0x80000000:
        v = -((~v + 1) & 0xFFFFFFFF)
    return v, ofs


def dec_data(*, buf: memoryview, ofs: int, encoding: str) -> tuple[Any, int]:
    """Decode data from a BIN-RPC data type."""
    # If there is no room for a 4-byte type tag, be lenient and return an empty string
    # and advance to the end of the buffer instead of raising.
    if ofs + 4 > len(buf):
        _LOGGER.debug(
            "Truncated BIN-RPC buffer while reading type tag (available=%d)",
            max(0, len(buf) - ofs),
        )
        return "", len(buf)
    t, ofs = _rd_u32(buf=buf, ofs=ofs)
    if t == T_STRING:
        return _dec_string(buf=buf, ofs=ofs, encoding=encoding)
    if t == T_BOOL:
        return _dec_bool(buf=buf, ofs=ofs)
    if t == T_BINARY:
        return _dec_binary(buf=buf, ofs=ofs)
    if t == T_INTEGER:
        return _dec_int(buf=buf, ofs=ofs)
    if t == T_DOUBLE:
        return _dec_double(buf=buf, ofs=ofs)
    if t == T_ARRAY:
        n, ofs = _rd_u32(buf=buf, ofs=ofs)
        outl: list[Any] = []
        # Leniency: some peers have been observed to emit a zero length here while
        # actually providing a single element array (e.g., system.multicall payloads).
        # If n == 0 but data remains and the next element decodes into a struct with
        # 'methodName' and 'params', treat it as a single-element array.
        if n == 0 and ofs < len(buf):
            try:
                probe_val, probe_ofs = dec_data(buf=buf, ofs=ofs, encoding=encoding)
                if isinstance(probe_val, dict) and "methodName" in probe_val and "params" in probe_val:
                    return [probe_val], probe_ofs
            except Exception:  # best-effort leniency only
                pass
        for _ in range(n):
            val, ofs = dec_data(buf=buf, ofs=ofs, encoding=encoding)
            outl.append(val)
        return outl, ofs
    if t == T_STRUCT:
        n, ofs = _rd_u32(buf=buf, ofs=ofs)
        outd: dict[str, Any] = {}
        for _ in range(n):
            key, ofs = _dec_string(buf=buf, ofs=ofs, encoding=encoding)
            val, ofs = dec_data(buf=buf, ofs=ofs, encoding=encoding)
            outd[key] = val
        return outd, ofs
    if t not in (T_STRING, T_BOOL, T_BINARY, T_INTEGER, T_DOUBLE, T_ARRAY, T_STRUCT):
        _LOGGER.warning("Unknown BIN-RPC type 0x%08X, treating as string", t)
        val, ofs = _dec_string(buf=buf, ofs=ofs, encoding=encoding)  # or skip a known number of bytes
        return val, ofs
    raise ValueError(f"Unsupported BIN-RPC type 0x{t:08X}")


def dec_request(*, frame: bytes, encoding: str) -> tuple[str, list[Any]]:
    """
    Decode a request frame as a BIN-RPC request frame.

    Be lenient to accommodate variations from different implementations
    (e.g., mdzio/go-hmccu). Accept any frame that starts with b"Bin" and has
    at least an 8-byte header; rely on the transport layer to have framed
    the message to the declared size.
    """
    if len(frame) < 8 or frame[:3] != b"Bin":
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


def dec_response(*, frame: bytes, encoding: str) -> Any:
    """
    Decode a response frame as a BIN-RPC response frame.

    The response body starts with a 32-bit status code (0 == OK), followed by
    an encoded BIN-RPC value. Some peers may omit the status and/or payload.
    We therefore validate sizes defensively and return None for an empty body.
    """
    # Be lenient with peer variations: accept any frame starting with b"Bin"
    if len(frame) < 8 or frame[:3] != b"Bin":
        raise ValueError("Invalid BIN-RPC response frame")
    body = memoryview(frame)[8:]
    # If there's no body at all, return None (some implementations send header-only frames)
    if len(body) == 0:
        return None
    ofs = 0
    # If there is not enough data for a status field, treat entire body as payload
    if len(body) < 4:
        v, _ = dec_data(buf=body, ofs=0, encoding=encoding)
        return v
    _status, ofs = _rd_u32(buf=body, ofs=ofs)
    # If there's no payload after the status field, return None
    if ofs >= len(body):
        return None
    v, _ = dec_data(buf=body, ofs=ofs, encoding=encoding)
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
