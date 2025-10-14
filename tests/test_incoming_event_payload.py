# SPDX-License-Identifier: MIT
"""Regression test for issue: Unable to handle incoming event with given body and hdr."""

from __future__ import annotations

from pybinrpc.support import dec_request

# Provided header and body from the issue report
_BAD_HDR = b"Bin\x00\x00\x00\x00\xa3"
_BAD_BODY = (
    b"\x00\x00\x00\x10system.multicall"
    b"\x00\x00\x00\x01"
    b"\x00\x00\x01\x00"
    b"\x00\x00\x00\x01"
    b"\x00\x00\x01\x01"
    b"\x00\x00\x00\x02"
    b"\x00\x00\x00\nmethodName"
    b"\x00\x00\x00\x03"
    b"\x00\x00\x00\x05event"
    b"\x00\x00\x00\x06params"
    b"\x00\x00\x01\x00\x00\x00\x00\x04"
    b"\x00\x00\x00\x03\x00\x00\x00\x19Kearney-Dev-Remote-1-CUxD"
    b"\x00\x00\x00\x03\x00\x00\x00\x0cCUX3901001:1"
    b"\x00\x00\x00\x03\x00\x00\x00\x05LEVEL"
    b"\x00\x00\x00\x04"
)

_GOOD_HDR = b"Bin\x00\x00\x00\x00T"
_GOOD_BODY = (
    b"\x00\x00\x00\x05event"
    b"\x00\x00\x00\x04\x00\x00\x00\x03\x00\x00\x00\niface-test"
    b"\x00\x00\x00\x03\x00\x00\x00\x0cCUX2801001:1"
    b"\x00\x00\x00\x03\x00\x00\x00\x05LEVEL"
    b"\x00\x00\x00\x04\xff\xff\xff\xfb=p\xa3\xd7"
)

_GOOD_HDR_2 = b"Bin\x00\x00\x00\x00\xa2"
_GOOD_BODY_2 = (
    b"\x00\x00\x00\x10system.multicall"
    b"\x00\x00\x00\x01"
    b"\x00\x00\x01\x00"
    b"\x00\x00\x00\x01"
    b"\x00\x00\x01\x01"
    b"\x00\x00\x00\x02"
    b"\x00\x00\x00\nmethodName"
    b"\x00\x00\x00\x03"
    b"\x00\x00\x00\x05event"
    b"\x00\x00\x00\x06params"
    b"\x00\x00\x01\x00\x00\x00\x00\x04"
    b"\x00\x00\x00\x03\x00\x00\x00\x19Kearney-Dev-Remote-1-CUxD"
    b"\x00\x00\x00\x03\x00\x00\x00\x07CENTRAL"
    b"\x00\x00\x00\x03\x00\x00\x00\x04PONG"
    b"\x00\x00\x00\x03\x00\x00\x00\tC"
)


def test_incoming_event_bad_payload_decodes_without_exception() -> None:
    """Ensure that truncated doubles are handled gracefully."""
    # Use exactly the size declared in the provided header (as from real device)
    declared_total = int.from_bytes(_BAD_HDR[4:8], "big")
    declared_body_len = declared_total - 8
    frame = _BAD_HDR + _BAD_BODY[:declared_body_len]
    method, params = dec_request(frame=frame, encoding="utf-8")
    # It is a system.multicall; ensure no exception and basic structure
    assert method == "system.multicall"
    assert isinstance(params, list)
    assert len(params) == 1


def test_incoming_event_good_payload_decodes_without_exception() -> None:
    """Ensure that truncated doubles are handled gracefully."""
    # Use exactly the size declared in the provided header (as from real device)
    declared_total = int.from_bytes(_GOOD_HDR[4:8], "big")
    declared_body_len = declared_total - 8
    frame = _GOOD_HDR + _GOOD_BODY[:declared_body_len]
    method, params = dec_request(frame=frame, encoding="utf-8")
    # It is a system.multicall; ensure no exception and basic structure
    assert method == "event"
    assert isinstance(params, list)
    assert params == ["iface-test", "CUX2801001:1", "LEVEL", 0.03]
    assert len(params) == 4


def test_incoming_event_good_payload_2_decodes_without_exception() -> None:
    """Ensure that truncated doubles are handled gracefully."""
    # Use exactly the size declared in the provided header (as from real device)
    declared_total = int.from_bytes(_GOOD_HDR_2[4:8], "big")
    declared_body_len = declared_total - 8
    frame = _GOOD_HDR_2 + _GOOD_BODY_2[:declared_body_len]
    method, params = dec_request(frame=frame, encoding="utf-8")
    # It is a system.multicall; ensure no exception and basic structure
    assert method == "system.multicall"
    assert isinstance(params, list)
    assert params == [[{"methodName": "event", "params": ["Kearney-Dev-Remote-1-CUxD", "CENTRAL", "PONG", "C"]}]]
    assert len(params[0][0].get("params")) == 4
