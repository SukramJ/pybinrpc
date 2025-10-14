[![releasebadge]][release]
[![License][license-shield]](LICENSE.md)
[![GitHub Sponsors][sponsorsbadge]][sponsors]

# PyBinRPC

A lightweight Python 3 library that enable python libraries to interact with BinRPC backends.

[license-shield]: https://img.shields.io/github/license/SukramJ/pybinrpc.svg?style=for-the-badge
[release]: https://github.com/SukramJ/pybinrpc/releases
[releasebadge]: https://img.shields.io/github/v/release/SukramJ/pybinrpc?style=for-the-badge
[sponsorsbadge]: https://img.shields.io/github/sponsors/SukramJ?style=for-the-badge&label=GitHub%20Sponsors&color=green
[sponsors]: https://github.com/sponsors/SukramJ

## Interoperability notes

Some BIN-RPC peers in the wild (e.g., CCU/CUxD stacks and clients based on hobbyquaker/binrpc) occasionally emit frames where the final double/float value appears truncated. In practice this happens when the 32-bit total length in the BIN header is smaller than the actual payload written, so the transport cuts the frame at the declared size. When this occurs in an `event` or `system.multicall` payload, the double’s 8-byte body may be shortened so only the 4-byte exponent is present and the 4-byte mantissa is missing.

To remain compatible with these devices, pybinrpc’s decoder is intentionally lenient:

- Doubles: if the exponent or mantissa is missing, the decoder returns `0.0` and advances to the end of the buffer instead of raising.
- Strings, binaries, integers, and booleans are decoded best-effort if the payload is shorter than declared.
- Arrays in some `system.multicall` payloads may declare length 0 yet still contain one struct element; pybinrpc treats this as a single-element array.

See tests `tests/test_truncated_double.py` and `tests/test_incoming_event_payload.py` for concrete real-world frames and the expected behavior.
