// WASI Snapshot Preview1 Bindings
// Low-level WASI syscall interfaces for discus-rs
//
// These raw WASI imports are used when running under WASI-compliant runtimes
// (wasmtime, wasmer, wamr, etc.) instead of wasm-bindgen/browser environments.

/// WASI errno codes (wasi_snapshot_preview1)
#[repr(u16)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WasiErrno {
    Success = 0,
    Badf = 8,
    Inval = 28,
    Noent = 44,
    Io = 29,
    Nospc = 51,
    Perm = 63,
    Unknown(u16),
}

impl WasiErrno {
    pub fn from_raw(val: u16) -> Self {
        match val {
            0 => WasiErrno::Success,
            8 => WasiErrno::Badf,
            28 => WasiErrno::Inval,
            44 => WasiErrno::Noent,
            29 => WasiErrno::Io,
            51 => WasiErrno::Nospc,
            63 => WasiErrno::Perm,
            other => WasiErrno::Unknown(other),
        }
    }

    pub fn is_ok(self) -> bool {
        matches!(self, WasiErrno::Success)
    }
}

/// WASI file descriptor type
pub type Fd = u32;

/// WASI file open flags
pub const O_CREAT: u16 = 1 << 0;
pub const O_TRUNC: u16 = 1 << 1;
pub const O_APPEND: u16 = 1 << 2;
pub const O_EXCL: u16 = 1 << 3;

/// WASI rights — capabilities granted to a file descriptor
pub const RIGHT_FD_WRITE: u64 = 1 << 6;
pub const RIGHT_FD_READ: u64 = 1 << 1;
pub const RIGHT_PATH_OPEN: u64 = 1 << 13;

/// Standard file descriptors
pub const FD_STDIN: Fd = 0;
pub const FD_STDOUT: Fd = 1;
pub const FD_STDERR: Fd = 2;

/// WASI ciovec: pointer + length for scatter/gather I/O
#[repr(C)]
pub struct Ciovec {
    pub buf: *const u8,
    pub buf_len: u32,
}

/// WASI iovec: pointer + length for scatter/gather I/O
#[repr(C)]
pub struct Iovec {
    pub buf: *mut u8,
    pub buf_len: u32,
}

// ============================================================================
// Raw WASI Snapshot Preview1 Imports
// These map directly to wasi_snapshot_preview1 module imports
// ============================================================================

#[cfg(all(target_arch = "wasm32", target_os = "wasi"))]
#[link(wasm_import_module = "wasi_snapshot_preview1")]
extern "C" {
    /// Write to a file descriptor
    /// https://github.com/WebAssembly/WASI/blob/main/legacy/preview1/docs.md#fd_write
    #[link_name = "fd_write"]
    pub fn wasi_fd_write(fd: Fd, iovs: *const Ciovec, iovs_len: u32, nwritten: *mut u32) -> u16;

    /// Read from a file descriptor
    /// https://github.com/WebAssembly/WASI/blob/main/legacy/preview1/docs.md#fd_read
    #[link_name = "fd_read"]
    pub fn wasi_fd_read(fd: Fd, iovs: *const Iovec, iovs_len: u32, nread: *mut u32) -> u16;

    /// Close a file descriptor
    #[link_name = "fd_close"]
    pub fn wasi_fd_close(fd: Fd) -> u16;

    /// Open/create a file or directory
    /// https://github.com/WebAssembly/WASI/blob/main/legacy/preview1/docs.md#path_open
    #[link_name = "path_open"]
    pub fn wasi_path_open(
        fd: Fd,
        dirflags: u32,
        path_ptr: *const u8,
        path_len: u32,
        oflags: u16,
        fs_rights_base: u64,
        fs_rights_inheriting: u64,
        fdflags: u16,
        opened_fd: *mut Fd,
    ) -> u16;

    /// Get current timestamp in nanoseconds
    #[link_name = "clock_time_get"]
    pub fn wasi_clock_time_get(clock_id: u32, precision: u64, timestamp: *mut u64) -> u16;

    /// Terminate the process
    #[link_name = "proc_exit"]
    pub fn wasi_proc_exit(code: u32);

    /// Get environment variables
    #[link_name = "environ_get"]
    pub fn wasi_environ_get(environ: *mut *mut u8, environ_buf: *mut u8) -> u16;

    /// Get sizes of environment variables
    #[link_name = "environ_sizes_get"]
    pub fn wasi_environ_sizes_get(count: *mut u32, buf_size: *mut u32) -> u16;

    /// Get random bytes
    #[link_name = "random_get"]
    pub fn wasi_random_get(buf: *mut u8, buf_len: u32) -> u16;

    /// Seek in a file descriptor
    #[link_name = "fd_seek"]
    pub fn wasi_fd_seek(fd: Fd, offset: i64, whence: u8, newoffset: *mut u64) -> u16;

    /// Get file descriptor attributes
    #[link_name = "fd_filestat_get"]
    pub fn wasi_fd_filestat_get(fd: Fd, buf: *mut u8) -> u16;

    /// Read directory entries
    #[link_name = "fd_readdir"]
    pub fn wasi_fd_readdir(
        fd: Fd,
        buf: *mut u8,
        buf_len: u32,
        cookie: u64,
        nread: *mut u32,
    ) -> u16;

    /// Create a directory
    #[link_name = "path_create_directory"]
    pub fn wasi_path_create_directory(
        fd: Fd,
        path_ptr: *const u8,
        path_len: u32,
    ) -> u16;

    /// Unlink a file
    #[link_name = "path_unlink_file"]
    pub fn wasi_path_unlink_file(
        fd: Fd,
        path_ptr: *const u8,
        path_len: u32,
    ) -> u16;
}

// ============================================================================
// Safe wrappers — called from host.rs
// ============================================================================

#[cfg(all(target_arch = "wasm32", target_os = "wasi"))]
pub mod safe {
    use super::*;

    /// Write bytes to a WASI file descriptor (stdout/stderr)
    pub fn fd_write(fd: Fd, data: &[u8]) -> Result<u32, WasiErrno> {
        let ciovec = Ciovec {
            buf: data.as_ptr(),
            buf_len: data.len() as u32,
        };
        let mut nwritten: u32 = 0;
        let errno = unsafe { wasi_fd_write(fd, &ciovec, 1, &mut nwritten) };
        let e = WasiErrno::from_raw(errno);
        if e.is_ok() {
            Ok(nwritten)
        } else {
            Err(e)
        }
    }

    /// Read bytes from a WASI file descriptor
    pub fn fd_read(fd: Fd, buf: &mut [u8]) -> Result<u32, WasiErrno> {
        let iovec = Iovec {
            buf: buf.as_mut_ptr(),
            buf_len: buf.len() as u32,
        };
        let mut nread: u32 = 0;
        let errno = unsafe { wasi_fd_read(fd, &iovec, 1, &mut nread) };
        let e = WasiErrno::from_raw(errno);
        if e.is_ok() {
            Ok(nread)
        } else {
            Err(e)
        }
    }

    /// Close a file descriptor
    pub fn fd_close(fd: Fd) -> Result<(), WasiErrno> {
        let errno = unsafe { wasi_fd_close(fd) };
        let e = WasiErrno::from_raw(errno);
        if e.is_ok() {
            Ok(())
        } else {
            Err(e)
        }
    }

    /// Open a file relative to a directory fd
    pub fn path_open(
        dir_fd: Fd,
        path: &[u8],
        oflags: u16,
        rights_base: u64,
    ) -> Result<Fd, WasiErrno> {
        let mut opened_fd: Fd = 0;
        let errno = unsafe {
            wasi_path_open(
                dir_fd,
                0, // no dirflags
                path.as_ptr(),
                path.len() as u32,
                oflags,
                rights_base,
                rights_base, // inheriting = same
                0,           // no fdflags
                &mut opened_fd,
            )
        };
        let e = WasiErrno::from_raw(errno);
        if e.is_ok() {
            Ok(opened_fd)
        } else {
            Err(e)
        }
    }

    /// Get current time in nanoseconds
    pub fn clock_time_get() -> Result<u64, WasiErrno> {
        let mut timestamp: u64 = 0;
        let errno = unsafe { wasi_clock_time_get(0, 1, &mut timestamp) };
        let e = WasiErrno::from_raw(errno);
        if e.is_ok() {
            Ok(timestamp)
        } else {
            Err(e)
        }
    }

    /// Get random bytes
    pub fn random_get(buf: &mut [u8]) -> Result<(), WasiErrno> {
        let errno = unsafe { wasi_random_get(buf.as_mut_ptr(), buf.len() as u32) };
        let e = WasiErrno::from_raw(errno);
        if e.is_ok() {
            Ok(())
        } else {
            Err(e)
        }
    }

    /// Seek in a file descriptor
    pub fn fd_seek(fd: Fd, offset: i64, whence: u8) -> Result<u64, WasiErrno> {
        let mut newoffset: u64 = 0;
        let errno = unsafe { wasi_fd_seek(fd, offset, whence, &mut newoffset) };
        let e = WasiErrno::from_raw(errno);
        if e.is_ok() {
            Ok(newoffset)
        } else {
            Err(e)
        }
    }

    /// Create a directory
    pub fn path_create_directory(dir_fd: Fd, path: &[u8]) -> Result<(), WasiErrno> {
        let errno = unsafe { wasi_path_create_directory(dir_fd, path.as_ptr(), path.len() as u32) };
        let e = WasiErrno::from_raw(errno);
        if e.is_ok() {
            Ok(())
        } else {
            Err(e)
        }
    }

    /// Unlink a file
    pub fn path_unlink_file(dir_fd: Fd, path: &[u8]) -> Result<(), WasiErrno> {
        let errno = unsafe { wasi_path_unlink_file(dir_fd, path.as_ptr(), path.len() as u32) };
        let e = WasiErrno::from_raw(errno);
        if e.is_ok() {
            Ok(())
        } else {
            Err(e)
        }
    }
}

// ============================================================================
// Non-WASI stubs — compile on non-WASI targets (tests, native builds)
// ============================================================================

#[cfg(not(all(target_arch = "wasm32", target_os = "wasi")))]
pub mod safe {
    use super::*;

    pub fn fd_write(_fd: Fd, _data: &[u8]) -> Result<u32, WasiErrno> {
        Ok(_data.len() as u32)
    }
    pub fn fd_read(_fd: Fd, _buf: &mut [u8]) -> Result<u32, WasiErrno> {
        Ok(0)
    }
    pub fn fd_close(_fd: Fd) -> Result<(), WasiErrno> {
        Ok(())
    }
    pub fn path_open(_dir_fd: Fd, _path: &[u8], _oflags: u16, _rights: u64) -> Result<Fd, WasiErrno> {
        Ok(100)
    }
    pub fn clock_time_get() -> Result<u64, WasiErrno> {
        Ok(0)
    }
    pub fn random_get(_buf: &mut [u8]) -> Result<(), WasiErrno> {
        Ok(())
    }
    pub fn fd_seek(_fd: Fd, _offset: i64, _whence: u8) -> Result<u64, WasiErrno> {
        Ok(0)
    }
    pub fn path_create_directory(_dir_fd: Fd, _path: &[u8]) -> Result<(), WasiErrno> {
        Ok(())
    }
    pub fn path_unlink_file(_dir_fd: Fd, _path: &[u8]) -> Result<(), WasiErrno> {
        Ok(())
    }
}
