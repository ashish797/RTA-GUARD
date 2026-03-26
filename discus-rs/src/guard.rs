use std::collections::HashSet;
use crate::models::*;
use crate::rta_engine::RtaEngine;
use crate::error::{DiscusResult, DiscusError};

/// Discus Guard — the kill-switch orchestrator
pub struct DiscusGuard {
    engine: RtaEngine,
    killed_sessions: HashSet<String>,
}

impl DiscusGuard {
    pub fn new(config: GuardConfig) -> Self {
        Self {
            engine: RtaEngine::new(config),
            killed_sessions: HashSet::new(),
        }
    }

    /// Check text for violations, returns result
    pub fn check(&mut self, text: &str, session_id: &str) -> DiscusResult<CheckResult> {
        // Check if session is already killed
        if self.killed_sessions.contains(session_id) {
            return Err(DiscusError::SessionKilled {
                session_id: session_id.to_string(),
            });
        }

        let mut result = self.engine.check(text)?;
        result.session_id = session_id.to_string();

        // If killed, record session
        if result.killed {
            self.killed_sessions.insert(session_id.to_string());
        }

        Ok(result)
    }

    /// Check text without session tracking
    pub fn check_text(&self, text: &str) -> DiscusResult<CheckResult> {
        self.engine.check(text)
    }

    /// Manually kill a session
    pub fn kill_session(&mut self, session_id: &str) -> bool {
        self.killed_sessions.insert(session_id.to_string())
    }

    /// Check if session is alive
    pub fn is_session_alive(&self, session_id: &str) -> bool {
        !self.killed_sessions.contains(session_id)
    }

    /// Reset a killed session
    pub fn reset_session(&mut self, session_id: &str) -> bool {
        self.killed_sessions.remove(session_id)
    }

    /// Get list of killed sessions
    pub fn get_killed_sessions(&self) -> Vec<String> {
        self.killed_sessions.iter().cloned().collect()
    }
}
