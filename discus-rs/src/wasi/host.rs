// WASI Host-Side Interface
// Implements high-level WASI operations on top of raw bindings
//
// WasiHost provides:
// - Logging to stdout/stderr
// - File I/O sandboxed to a configurable directory
// - Session persistence (save/load)
// - Audit log (append-only file with timestamps)

use crate::engine::RtaEngine;
use crate::context::RtaContext;
use crate::session::SessionManager;
use crate::types::*;
use crate::wasi::wasi_bindings::{safe as wasi, Fd, RIGHT_FD_WRITE, RIGHT_FD_READ, O_CREAT, O_APPEND, FD_STDOUT, FD_STDERR};
use std::collections::HashMap;

/// Audit event types
#[derive(Debug, Clone, PartialEq)]
pub enum AuditEvent {
    Initialize,
    Check { session_id: String, allowed: bool },
    Kill { session_id: String, reason: String },
    SessionCreate { session_id: String },
    SessionLoad { session_id: String },
    SessionSave { session_id: String },
    Error { message: String },
}

impl AuditEvent {
    pub fn event_type(&self) -> &'static str {
        match self {
            AuditEvent::Initialize => "INITIALIZE",
            AuditEvent::Check { .. } => "CHECK",
            AuditEvent::Kill { .. } => "KILL",
            AuditEvent::SessionCreate { .. } => "SESSION_CREATE",
            AuditEvent::SessionLoad { .. } => "SESSION_LOAD",
            AuditEvent::SessionSave { .. } => "SESSION_SAVE",
            AuditEvent::Error { .. } => "ERROR",
        }
    }

    pub fn to_json(&self) -> String {
        match self {
            AuditEvent::Initialize => {
                r#"{"event":"INITIALIZE","timestamp":0}"#.to_string()
            }
            AuditEvent::Check { session_id, allowed } => {
                format!(
                    r#"{{"event":"CHECK","session_id":"{}","allowed":{}}}"#,
                    session_id, allowed
                )
            }
            AuditEvent::Kill { session_id, reason } => {
                format!(
                    r#"{{"event":"KILL","session_id":"{}","reason":"{}"}}"#,
                    session_id, reason.replace('"', "\\\"")
                )
            }
            AuditEvent::SessionCreate { session_id } => {
                format!(
                    r#"{{"event":"SESSION_CREATE","session_id":"{}"}}"#,
                    session_id
                )
            }
            AuditEvent::SessionLoad { session_id } => {
                format!(
                    r#"{{"event":"SESSION_LOAD","session_id":"{}"}}"#,
                    session_id
                )
            }
            AuditEvent::SessionSave { session_id } => {
                format!(
                    r#"{{"event":"SESSION_SAVE","session_id":"{}"}}"#,
                    session_id
                )
            }
            AuditEvent::Error { message } => {
                format!(
                    r#"{{"event":"ERROR","message":"{}"}}"#,
                    message.replace('"', "\\\"")
                )
            }
        }
    }
}

/// WASI Host — high-level interface to WASI syscalls
pub struct WasiHost {
    /// Root file descriptor for sandboxed directory (pre-opened by runtime)
    root_fd: Fd,
    /// Session manager (in-memory, backed by WASI file I/O)
    session_mgr: SessionManager,
    /// Audit log file descriptor
    audit_fd: Option<Fd>,
    /// Configuration
    config: GuardConfig,
    /// Whether initialized
    initialized: bool,
    /// In-memory session state cache (serialized JSON)
    session_states: HashMap<String, String>,
}

impl WasiHost {
    /// Create a new WasiHost with the given root directory fd
    /// In WASI runtimes, the sandbox root is typically fd 3 (pre-opened ".")
    pub fn new(root_fd: Fd) -> Self {
        WasiHost {
            root_fd,
            session_mgr: SessionManager::new(),
            audit_fd: None,
            config: GuardConfig::default(),
            initialized: false,
            session_states: HashMap::new(),
        }
    }

    /// Create with custom config
    pub fn with_config(root_fd: Fd, config: GuardConfig) -> Self {
        WasiHost {
            root_fd,
            session_mgr: SessionManager::new(),
            audit_fd: None,
            config,
            initialized: false,
            session_states: HashMap::new(),
        }
    }

    /// Initialize: open audit log, set up directories
    pub fn initialize(&mut self) -> Result<(), String> {
        // Create data directory if it doesn't exist
        let _ = wasi::path_create_directory(self.root_fd, b"data");

        // Open audit log for append
        match wasi::path_open(
            self.root_fd,
            b"data/audit.log",
            O_CREAT | O_APPEND,
            RIGHT_FD_WRITE,
        ) {
            Ok(fd) => {
                self.audit_fd = Some(fd);
            }
            Err(e) => {
                self.log_stderr(&format!("Failed to open audit log: {:?}", e))?;
            }
        }

        self.initialized = true;
        self.write_audit(AuditEvent::Initialize)?;
        self.log_stdout("RTA-GUARD WASI initialized")?;

        Ok(())
    }

    /// Log a message to stdout
    pub fn log_stdout(&self, msg: &str) -> Result<(), String> {
        let formatted = format!("[RTA-GUARD] {}\n", msg);
        wasi::fd_write(FD_STDOUT, formatted.as_bytes())
            .map_err(|e| format!("stdout write failed: {:?}", e))?;
        Ok(())
    }

    /// Log a message to stderr
    pub fn log_stderr(&self, msg: &str) -> Result<(), String> {
        let formatted = format!("[RTA-GUARD ERROR] {}\n", msg);
        wasi::fd_write(FD_STDERR, formatted.as_bytes())
            .map_err(|e| format!("stderr write failed: {:?}", e))?;
        Ok(())
    }

    /// Write an audit event to the append-only audit log
    pub fn write_audit(&self, event: AuditEvent) -> Result<(), String> {
        if let Some(fd) = self.audit_fd {
            let ts = wasi::clock_time_get().unwrap_or(0);
            let entry = format!("{}|{}\n", ts, event.to_json());
            wasi::fd_write(fd, entry.as_bytes())
                .map_err(|e| format!("audit write failed: {:?}", e))?;
        }
        Ok(())
    }

    /// Check an input through the engine
    pub fn check(&mut self, session_id: &str, input: &str) -> Result<String, String> {
        if !self.initialized {
            return Err("WasiHost not initialized".into());
        }

        let ctx = RtaContext::builder(session_id, input).build();
        let engine = RtaEngine::new(Some(self.config.clone()));
        let (allowed, results, decision) = engine.check(&ctx);

        // Count violations
        let violations = results.iter().filter(|r| r.is_violation).count();
        if !allowed {
            self.session_mgr.kill_session(session_id, "Killed by rule violation");
        }

        self.write_audit(AuditEvent::Check {
            session_id: session_id.to_string(),
            allowed,
        })?;

        // Serialize result
        let response = serde_json::json!({
            "allowed": allowed,
            "session_id": session_id,
            "decision": format!("{:?}", decision),
            "violations": violations,
            "results": results,
        });

        serde_json::to_string(&response).map_err(|e| e.to_string())
    }

    /// Kill a session
    pub fn kill(&mut self, session_id: &str, reason: &str) -> Result<String, String> {
        if !self.initialized {
            return Err("WasiHost not initialized".into());
        }

        self.session_mgr.kill_session(session_id, reason);

        self.write_audit(AuditEvent::Kill {
            session_id: session_id.to_string(),
            reason: reason.to_string(),
        })?;

        let response = serde_json::json!({
            "killed": true,
            "session_id": session_id,
            "reason": reason,
        });

        serde_json::to_string(&response).map_err(|e| e.to_string())
    }

    /// Create a new session
    pub fn create_session(&mut self) -> Result<String, String> {
        let sid = self.session_mgr.new_session();

        self.write_audit(AuditEvent::SessionCreate {
            session_id: sid.clone(),
        })?;

        Ok(sid)
    }

    /// Get session status
    pub fn session_status(&self, session_id: &str) -> String {
        let info = self.session_mgr.get_session_info(session_id);
        if info.alive {
            "alive".to_string()
        } else {
            "killed".to_string()
        }
    }

    /// Export session state as JSON
    pub fn export_state(&self) -> Result<String, String> {
        let sessions: Vec<serde_json::Value> = self.session_mgr.list_sessions()
            .iter()
            .map(|s| {
                serde_json::json!({
                    "session_id": s.session_id,
                    "alive": s.alive,
                    "violation_count": s.violation_count,
                    "kill_reason": s.kill_reason,
                })
            })
            .collect();

        let state = serde_json::json!({
            "exported_at": wasi::clock_time_get().unwrap_or(0),
            "initialized": self.initialized,
            "session_count": sessions.len(),
            "sessions": sessions,
            "config": {
                "max_drift_score": self.config.max_drift_score,
                "health_threshold_warn": self.config.health_threshold_warn,
                "health_threshold_kill": self.config.health_threshold_kill,
                "indirect_pii_threshold": self.config.indirect_pii_threshold,
            }
        });

        serde_json::to_string_pretty(&state).map_err(|e| e.to_string())
    }

    /// Save session state to a file (WASI file I/O)
    pub fn save_session_state(&mut self, session_id: &str) -> Result<(), String> {
        if !self.initialized {
            return Err("WasiHost not initialized".into());
        }

        let info = self.session_mgr.get_session_info(session_id);
        let state = serde_json::json!({
            "session_id": info.session_id,
            "alive": info.alive,
            "violation_count": info.violation_count,
            "kill_reason": info.kill_reason,
        });
        let json = serde_json::to_string(&state).map_err(|e| e.to_string())?;

        let filename = format!("data/session_{}.json", session_id);

        // Open file for write (create + truncate)
        let fd = wasi::path_open(
            self.root_fd,
            filename.as_bytes(),
            O_CREAT | 1, // O_CREAT | O_TRUNC
            RIGHT_FD_WRITE,
        ).map_err(|e| format!("Failed to open session file: {:?}", e))?;

        wasi::fd_write(fd, json.as_bytes())
            .map_err(|e| format!("Failed to write session state: {:?}", e))?;

        wasi::fd_close(fd).ok();

        self.session_states.insert(session_id.to_string(), json);
        self.write_audit(AuditEvent::SessionSave {
            session_id: session_id.to_string(),
        })?;

        Ok(())
    }

    /// Load session state from a file
    pub fn load_session_state(&mut self, session_id: &str) -> Result<String, String> {
        if !self.initialized {
            return Err("WasiHost not initialized".into());
        }

        // Check cache first
        if let Some(cached) = self.session_states.get(session_id) {
            self.write_audit(AuditEvent::SessionLoad {
                session_id: session_id.to_string(),
            })?;
            return Ok(cached.clone());
        }

        let filename = format!("data/session_{}.json", session_id);
        let fd = wasi::path_open(
            self.root_fd,
            filename.as_bytes(),
            0, // no oflags (read only)
            RIGHT_FD_READ,
        ).map_err(|e| format!("Failed to open session file: {:?}", e))?;

        let mut buf = vec![0u8; 4096];
        let nread = wasi::fd_read(fd, &mut buf)
            .map_err(|e| format!("Failed to read session state: {:?}", e))?;

        wasi::fd_close(fd).ok();

        let json = String::from_utf8_lossy(&buf[..nread as usize]).to_string();

        self.write_audit(AuditEvent::SessionLoad {
            session_id: session_id.to_string(),
        })?;

        Ok(json)
    }

    /// Read the audit log
    pub fn read_audit_log(&self) -> Result<String, String> {
        let fd = wasi::path_open(
            self.root_fd,
            b"data/audit.log",
            0,
            RIGHT_FD_READ,
        ).map_err(|e| format!("Failed to open audit log: {:?}", e))?;

        let mut buf = vec![0u8; 65536];
        let nread = wasi::fd_read(fd, &mut buf)
            .map_err(|e| format!("Failed to read audit log: {:?}", e))?;

        wasi::fd_close(fd).ok();

        Ok(String::from_utf8_lossy(&buf[..nread as usize]).to_string())
    }

    /// Get the root fd
    pub fn root_fd(&self) -> Fd {
        self.root_fd
    }

    /// Check if initialized
    pub fn is_initialized(&self) -> bool {
        self.initialized
    }
}
