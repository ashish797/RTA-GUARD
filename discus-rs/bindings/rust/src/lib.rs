//! # discus-bindings
//!
//! Public API wrapper for `discus-rs` — the RTA-GUARD Discus kill-switch.
//!
//! This crate re-exports the core `discus-rs` types with a simplified,
//! consistent API matching the BINDING_SPEC contract.
//!
//! ## Usage
//!
//! ```rust
//! use discus_bindings::{Discus, CheckResult};
//!
//! let guard = Discus::new();
//! let result = guard.check("sess-001", "Hello, world!");
//! println!("{:?}", result);
//!
//! guard.kill("sess-001");
//! assert!(!guard.is_alive("sess-001"));
//!
//! let rules = guard.get_rules();
//! println!("Active rules: {:?}", rules);
//! ```

pub use discus_rs::{GuardConfig, KillDecision, RuleResult, Severity, ViolationType};

use discus_rs::{RtaContext, RtaEngine, SessionManager};
use serde::{Deserialize, Serialize};

/// Check result matching BINDING_SPEC
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckResult {
    pub allowed: bool,
    pub session_id: String,
    pub decision: String,
    pub results: Vec<RuleResultEntry>,
}

/// Individual rule result matching BINDING_SPEC
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuleResultEntry {
    pub rule: String,
    pub passed: bool,
    pub severity: String,
    pub message: String,
}

/// Discus guard engine — clean API wrapper
pub struct Discus {
    engine: RtaEngine,
    session_manager: SessionManager,
}

impl Discus {
    /// Create a new Discus instance with default config
    pub fn new() -> Self {
        Self {
            engine: RtaEngine::new(None),
            session_manager: SessionManager::new(),
        }
    }

    /// Create with custom config
    pub fn with_config(config: GuardConfig) -> Self {
        Self {
            engine: RtaEngine::new(Some(config)),
            session_manager: SessionManager::new(),
        }
    }

    /// Check input through the RTA rules engine
    pub fn check(&self, session_id: &str, input: &str) -> CheckResult {
        let ctx = RtaContext::builder(session_id, input).build();
        let (allowed, results, decision) = self.engine.check(&ctx);

        let entries = results
            .iter()
            .map(|r| RuleResultEntry {
                rule: r.rule.clone(),
                passed: r.passed,
                severity: format!("{:?}", r.severity),
                message: r.message.clone(),
            })
            .collect();

        CheckResult {
            allowed,
            session_id: session_id.to_string(),
            decision: format!("{:?}", decision),
            results: entries,
        }
    }

    /// Kill a session
    pub fn kill(&mut self, session_id: &str) {
        self.session_manager.kill_session(session_id, "killed via Rust binding");
    }

    /// Check if a session is alive
    pub fn is_alive(&self, session_id: &str) -> bool {
        self.session_manager.is_alive(session_id)
    }

    /// Get list of active rule names
    pub fn get_rules(&self) -> Vec<String> {
        self.engine.rules.iter().map(|r| r.name.clone()).collect()
    }
}

impl Default for Discus {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_new() {
        let guard = Discus::new();
        let rules = guard.get_rules();
        assert!(!rules.is_empty());
    }

    #[test]
    fn test_check_returns_result() {
        let guard = Discus::new();
        let result = guard.check("test-session", "Hello, world!");
        assert_eq!(result.session_id, "test-session");
        assert!(!result.results.is_empty());
    }

    #[test]
    fn test_kill_and_is_alive() {
        let mut guard = Discus::new();
        assert!(guard.is_alive("kill-test"));
        guard.kill("kill-test");
        assert!(!guard.is_alive("kill-test"));
    }

    #[test]
    fn test_get_rules_contains_core() {
        let guard = Discus::new();
        let rules = guard.get_rules();
        assert!(rules.iter().any(|r| r == "SATYA"));
        assert!(rules.iter().any(|r| r == "DHARMA"));
    }

    #[test]
    fn test_serializable() {
        let guard = Discus::new();
        let result = guard.check("serial-test", "test");
        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("allowed"));
        assert!(json.contains("session_id"));
    }
}
