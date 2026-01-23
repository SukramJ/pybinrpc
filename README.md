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

## Protocol Compatibility

PyBinRPC implements the BinRPC protocol as specified in the [HomeMatic forum](https://homematic-forum.de/forum/viewtopic.php?t=8210) and is compatible with multiple implementations.

### Standard HomeMatic BinRPC Protocol

The official HomeMatic BinRPC specification defines the following data types:

**Header Format:**

- Requests: `Bin\x00` + 4-byte length (big-endian)
- Responses: `Bin\x01` + 4-byte length (big-endian)

**Standard Data Types:**
| Type | Value | Supported | Notes |
|------|-------|-----------|-------|
| Integer | 0x01 | ✅ | 32-bit signed integer |
| Boolean | 0x02 | ✅ | Single byte (0x00/0x01) |
| String | 0x03 | ✅ | UTF-8 encoded text |
| Double/Float | 0x04 | ✅ | Mantissa/exponent format |
| Array | 0x100 (256) | ✅ | Ordered list of values |
| Struct | 0x101 (257) | ✅ | Key-value pairs |

**Double Encoding:**
PyBinRPC uses the same mantissa/exponent representation:

- Mantissa: 32-bit signed integer (value normalized to [0.5, 1.0) × 2³⁰)
- Exponent: 32-bit signed integer
- Formula: `value = (mantissa / 2³⁰) × 2^exponent`
- Big-endian byte order

**⚠️ Important Note - Double Byte Order:**
There is a discrepancy between the documented specification and real-world CCU device behavior:

- **HomeMatic Forum Specification** documents: Mantissa first, then Exponent
- **Real CCU Devices** actually send: **Exponent first, then Mantissa**

PyBinRPC follows the actual CCU device behavior (exponent-first) to ensure compatibility with real HomeMatic hardware. This has been verified through real-world CCU event payloads. While this contradicts the published specification, it is necessary for practical interoperability with CCU/CUxD devices.

### Compatibility with Homegear

PyBinRPC supports the Homegear `Binary (0xD0)` type extension:

**Homegear Extensions (supported):**

- `Binary (0xD0)` - Raw binary data (bytes)

**Homegear Extensions (not yet implemented):**

- `Integer64 (0xD1)` - 64-bit integers
- `Base64 (0x11)` - Base64-encoded data
- `Void (0x00)` - Void/null type

**⚠️ Double Value Compatibility:**
Homegear's [libhomegear-base](https://github.com/Homegear/libhomegear-base) encodes double values with **mantissa-first** byte order, following the published specification. PyBinRPC uses **exponent-first** byte order to match real CCU devices. This means:

- ✅ **Compatible with CCU/CUxD devices** - PyBinRPC correctly handles double values from real HomeMatic hardware
- ⚠️ **Incompatible with Homegear** - Double/float values will not be correctly exchanged with Homegear-based systems

**Note:** The `Binary` type (0xD0) is a Homegear extension and is **not part of the official HomeMatic BinRPC specification**. When communicating only with standard HomeMatic devices (CCU, CUxD), binary data should be avoided or encoded as strings.

### Compatibility Summary

| Implementation               | Integer/String/Bool/Array/Struct | Double/Float                           | Binary Type         |
| ---------------------------- | -------------------------------- | -------------------------------------- | ------------------- |
| HomeMatic CCU/CUxD           | ✅ Fully compatible              | ✅ Fully compatible                    | N/A                 |
| Homegear/libhomegear-base    | ✅ Fully compatible              | ⚠️ Incompatible (different byte order) | ✅ Supported (0xD0) |
| hobbyquaker/binrpc (Node.js) | ✅ Fully compatible              | ⚠️ Incompatible (different byte order) | N/A                 |
| HomeMatic Forum Spec         | ✅ Fully compatible              | ⚠️ Spec differs from CCU behavior      | N/A                 |

**Recommendation:** PyBinRPC is optimized for communication with real HomeMatic CCU/CUxD hardware. For Homegear-based systems, double/float values may not work correctly due to the byte order difference.
