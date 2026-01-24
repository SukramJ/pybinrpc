# Changelog

All notable changes to this project will be documented in this file.

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
