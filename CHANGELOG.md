# Changelog

All notable changes to this project will be documented in this file.

## Version 2026.3.0

### Added

- **Fault frame support** (`Bin\xFF`): New `enc_fault()` encoder and fault detection in `dec_response()`. Fault responses from peers now raise `BinRpcFaultError` with `fault_code` and `fault_string` attributes.
- **`BinRpcFaultError` exception** in `pybinrpc.exceptions` for structured fault handling.
- **Configurable max message size**: `recv_exact()` accepts a `max_size` parameter (default 2 MiB) to reject oversized frames. Exposed via `max_msg_size` on `BinRpcServerProxy`, `_Transport`, and `SimpleBINRPCServer`.
- **`HDR_FAULT`**, **`MAX_MSG_SIZE`**, and **`VALID_TYPE_TAGS`** constants in `pybinrpc.const`.
- New test files: `tests/test_fault.py` (5 tests) and `tests/test_encoding.py` (6 tests).

### Changed

- **Response frame format**: `enc_response()` no longer emits the 4-byte status field prefix, aligning with Go (mdzio/go-hmccu) and Node.js (hobbyquaker/binrpc) implementations. No real CCU capture ever contained this field.
- **Response decoding auto-detection**: `dec_response()` now auto-detects whether a response contains a status field prefix (legacy) or starts directly with a type tag. Both formats are decoded correctly.
- **Integer encoding**: `enc_integer()` now uses signed 32-bit packing (`struct.pack(">i")`) with clamping instead of unsigned masking. Negative integers are now correctly represented on the wire.
- **Double precision**: Decoding precision increased from `round(val, 4)` to `round(val, 6)`. All existing test values (0.01–0.99, 0.03) produce identical results.
- **Server error handling**: `SimpleBINRPCServer` now sends fault responses (`enc_fault()`) instead of empty-string responses when handler exceptions occur.
- **Client retry logic**: Deduplicated send/receive code in `_Transport.call()` into a shared `_send_recv()` method.

## Version 2025.11.0

### Added

- **Async BIN-RPC Server** (`AsyncBinRpcServer`): Full asyncio-native server implementation
  - Non-blocking TCP server using `asyncio.start_server()`
  - Singleton pattern per (ip_addr, port) combination
  - Support for both sync and async method handlers
  - Background task tracking with graceful cleanup on shutdown
- **Async CUxD Server** (`AsyncCuxdServer`): Async convenience server with pre-registered CUxD methods
  - `event`, `newDevices`, `deleteDevices`, `listDevices`
  - In-memory device registry
- **Async Dispatcher** (`AsyncBinRpcDispatcher`): Method dispatcher with async support
  - `system.listMethods` introspection
  - `system.multicall` batching
  - Dotted method name resolution (e.g., `system.listMethods`)
- **HTTP Health Endpoint**: Optional health check endpoint with server status and metrics
- **Request Metrics**: Request counter, error counter, and latency tracking
- **Factory Function**: `create_async_bin_rpc_server()` for quick server creation
- **Network Constants**: `IP_ANY_V4` and `PORT_ANY` in `const.py`
- **Async Support Function**: `async_drain_pending_bytes()` for CUxD compatibility

### Changed

- Updated `__init__.py` to export all async server classes

## Version 2025.10.1

### Added

- Comprehensive test suite for BIN-RPC protocol
- TLS/SSL support tests

### Fixed

- CUxD compatibility: Auto-detect double byte order (exponent-first vs mantissa-first)
- Lenient parsing for truncated payloads (strings, doubles, arrays, structs)
- Handle frames with under-reported length field (CUxD quirk)
- Zero-length array detection for `system.multicall` payloads

## Version 2025.10.0

### Added

- Initial release
- `SimpleBINRPCServer`: Threaded BIN-RPC server (sync)
- `SimpleBINRPCRequestHandler`: Request handler for BIN-RPC protocol
- `CuxdServer`: Convenience server with CUxD defaults
- `BinRpcServerProxy`: Client for BIN-RPC communication
- Full BIN-RPC protocol support:
  - Types: Integer, Boolean, String, Double, Array, Struct, Binary
  - Request/Response encoding and decoding
- Keep-alive connection pooling in client
- TLS/SSL support with SNI
- UTF-8 encoding support
