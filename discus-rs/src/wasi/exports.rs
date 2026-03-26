// WASM Exports for WASI Runtime
// These are the exported functions callable from WASI host environments
//
// Target: wasm32-wasip1 (wasi_snapshot_preview1)
// Unlike wasm.rs (wasm-bindgen for browsers), these use raw WASI exports

use crate::wasi::host::WasiHost;
use std::sync::{Mutex, OnceLock};

// Global WASI host instance
static WASI_HOST: OnceLock<Mutex<WasiHost>> = OnceLock::new();

fn get_host() -> &'static Mutex<WasiHost> {
    WASI_HOST.get_or_init(|| {
        // In WASI runtimes, the sandbox root is typically fd 3 (pre-opened ".")
        // Runtimes like wasmtime and wasmer pre-open "." as fd 3
        Mutex::new(WasiHost::new(3))
    })
}

/// Initialize WASI host — sets up audit log, data directory
/// Call this before any other WASI export
#[no_mangle]
pub extern "C" fn wasi_initialize() -> i32 {
    let host = get_host();
    match host.lock() {
        Ok(mut h) => {
            match h.initialize() {
                Ok(_) => 0,
                Err(e) => {
                    let _ = h.log_stderr(&format!("Init failed: {}", e));
                    -1
                }
            }
        }
        Err(_) => -2,
    }
}

/// Check input text through the RTA engine via WASI
/// Returns JSON result as a string written to stdout
///
/// # Safety
/// input_ptr must point to input_len valid UTF-8 bytes
#[no_mangle]
pub unsafe extern "C" fn wasi_check(input_ptr: *const u8, input_len: u32) -> i32 {
    let input = match std::str::from_utf8(std::slice::from_raw_parts(input_ptr, input_len as usize)) {
        Ok(s) => s,
        Err(_) => return -1,
    };

    let host = get_host();
    match host.lock() {
        Ok(mut h) => {
            match h.check("wasi-session", input) {
                Ok(result) => {
                    let _ = h.log_stdout(&result);
                    0
                }
                Err(e) => {
                    let _ = h.log_stderr(&format!("Check failed: {}", e));
                    -1
                }
            }
        }
        Err(_) => -2,
    }
}

/// Check with a specific session ID
///
/// # Safety
/// session_ptr and input_ptr must point to valid UTF-8
#[no_mangle]
pub unsafe extern "C" fn wasi_check_session(
    session_ptr: *const u8,
    session_len: u32,
    input_ptr: *const u8,
    input_len: u32,
) -> i32 {
    let session_id = match std::str::from_utf8(std::slice::from_raw_parts(session_ptr, session_len as usize)) {
        Ok(s) => s,
        Err(_) => return -1,
    };
    let input = match std::str::from_utf8(std::slice::from_raw_parts(input_ptr, input_len as usize)) {
        Ok(s) => s,
        Err(_) => return -1,
    };

    let host = get_host();
    match host.lock() {
        Ok(mut h) => {
            match h.check(session_id, input) {
                Ok(result) => {
                    let _ = h.log_stdout(&result);
                    0
                }
                Err(e) => {
                    let _ = h.log_stderr(&format!("Check failed: {}", e));
                    -1
                }
            }
        }
        Err(_) => -2,
    }
}

/// Kill a session by ID
///
/// # Safety
/// session_ptr must point to session_len valid UTF-8 bytes
#[no_mangle]
pub unsafe extern "C" fn wasi_kill(session_ptr: *const u8, session_len: u32) -> i32 {
    let session_id = match std::str::from_utf8(std::slice::from_raw_parts(session_ptr, session_len as usize)) {
        Ok(s) => s,
        Err(_) => return -1,
    };

    let host = get_host();
    match host.lock() {
        Ok(mut h) => {
            match h.kill(session_id, "Killed via WASI") {
                Ok(result) => {
                    let _ = h.log_stdout(&result);
                    0
                }
                Err(e) => {
                    let _ = h.log_stderr(&format!("Kill failed: {}", e));
                    -1
                }
            }
        }
        Err(_) => -2,
    }
}

/// Kill a session with a reason
///
/// # Safety
/// session_ptr and reason_ptr must point to valid UTF-8
#[no_mangle]
pub unsafe extern "C" fn wasi_kill_with_reason(
    session_ptr: *const u8,
    session_len: u32,
    reason_ptr: *const u8,
    reason_len: u32,
) -> i32 {
    let session_id = match std::str::from_utf8(std::slice::from_raw_parts(session_ptr, session_len as usize)) {
        Ok(s) => s,
        Err(_) => return -1,
    };
    let reason = match std::str::from_utf8(std::slice::from_raw_parts(reason_ptr, reason_len as usize)) {
        Ok(s) => s,
        Err(_) => return -1,
    };

    let host = get_host();
    match host.lock() {
        Ok(mut h) => {
            match h.kill(session_id, reason) {
                Ok(result) => {
                    let _ = h.log_stdout(&result);
                    0
                }
                Err(e) => {
                    let _ = h.log_stderr(&format!("Kill failed: {}", e));
                    -1
                }
            }
        }
        Err(_) => -2,
    }
}

/// Export session state as JSON to stdout
#[no_mangle]
pub extern "C" fn wasi_export_state() -> i32 {
    let host = get_host();
    match host.lock() {
        Ok(h) => {
            match h.export_state() {
                Ok(state) => {
                    let _ = h.log_stdout(&state);
                    0
                }
                Err(e) => {
                    let _ = h.log_stderr(&format!("Export failed: {}", e));
                    -1
                }
            }
        }
        Err(_) => -2,
    }
}

/// Create a new session, returns 0 on success
#[no_mangle]
pub extern "C" fn wasi_create_session() -> i32 {
    let host = get_host();
    match host.lock() {
        Ok(mut h) => {
            match h.create_session() {
                Ok(sid) => {
                    let _ = h.log_stdout(&format!("Session created: {}", sid));
                    0
                }
                Err(e) => {
                    let _ = h.log_stderr(&format!("Create session failed: {}", e));
                    -1
                }
            }
        }
        Err(_) => -2,
    }
}

/// Save session state to disk
///
/// # Safety
/// session_ptr must point to session_len valid UTF-8 bytes
#[no_mangle]
pub unsafe extern "C" fn wasi_save_session(session_ptr: *const u8, session_len: u32) -> i32 {
    let session_id = match std::str::from_utf8(std::slice::from_raw_parts(session_ptr, session_len as usize)) {
        Ok(s) => s,
        Err(_) => return -1,
    };

    let host = get_host();
    match host.lock() {
        Ok(mut h) => {
            match h.save_session_state(session_id) {
                Ok(_) => 0,
                Err(e) => {
                    let _ = h.log_stderr(&format!("Save session failed: {}", e));
                    -1
                }
            }
        }
        Err(_) => -2,
    }
}

/// Read audit log to stdout
#[no_mangle]
pub extern "C" fn wasi_read_audit_log() -> i32 {
    let host = get_host();
    match host.lock() {
        Ok(h) => {
            match h.read_audit_log() {
                Ok(log) => {
                    let _ = h.log_stdout(&log);
                    0
                }
                Err(e) => {
                    let _ = h.log_stderr(&format!("Read audit log failed: {}", e));
                    -1
                }
            }
        }
        Err(_) => -2,
    }
}

/// Simple greeting / health check
#[no_mangle]
pub extern "C" fn wasi_hello() -> i32 {
    let host = get_host();
    match host.lock() {
        Ok(h) => {
            let _ = h.log_stdout("RTA-GUARD Discus WASI module v0.1.0");
            0
        }
        Err(_) => -2,
    }
}

// ============================================================================
// Memory allocator for host → WASM string passing
// ============================================================================

/// Allocate memory in WASM linear memory
/// Host calls this to get a pointer, then writes data, then calls wasi_check etc.
#[no_mangle]
pub extern "C" fn alloc(size: u32) -> *mut u8 {
    let layout = std::alloc::Layout::from_size_align(size as usize, 1).unwrap();
    unsafe { std::alloc::alloc(layout) }
}

/// Deallocate memory allocated by alloc()
#[no_mangle]
pub extern "C" fn dealloc(ptr: *mut u8, size: u32) {
    let layout = std::alloc::Layout::from_size_align(size as usize, 1).unwrap();
    unsafe { std::alloc::dealloc(ptr, layout) }
}
