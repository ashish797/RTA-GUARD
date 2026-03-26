use thiserror::Error;

#[derive(Error, Debug)]
pub enum DiscusError {
    #[error("Session already killed: {session_id}")]
    SessionKilled { session_id: String },

    #[error("Session not found: {session_id}")]
    SessionNotFound { session_id: String },

    #[error("Invalid configuration: {0}")]
    InvalidConfig(String),

    #[error("JSON serialization error: {0}")]
    JsonError(#[from] serde_json::Error),

    #[error("Rule check failed: {rule_name} — {reason}")]
    RuleCheckFailed { rule_name: String, reason: String },

    #[error("PII detected in {field}: {patterns}")]
    PiiDetected { field: String, patterns: String },

    #[error("Prompt injection detected: {patterns}")]
    InjectionDetected { patterns: String },

    #[error("Jailbreak attempt: {patterns}")]
    JailbreakDetected { patterns: String },
}

pub type DiscusResult<T> = Result<T, DiscusError>;
