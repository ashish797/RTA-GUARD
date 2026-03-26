// discus-rs WASI System Integration
// Phase 5.4 — WASI System Integration
//
// Provides wasi_snapshot_preview1 bindings for:
// - Logging (fd_write to stdout/stderr)
// - File I/O (path_open, fd_read, fd_write) sandboxed to configurable dir
// - Session persistence (save/load session state to disk)
// - Audit logging (append-only event log)

pub mod wasi_bindings;
pub mod host;
pub mod exports;

pub use host::WasiHost;
pub use exports::*;
