use serde::{Deserialize, Serialize};
use chrono::{DateTime, Utc};
/// Severity levels for rule violations
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum Severity {
    Low,
    Medium,
    High,
    Critical,
}

impl std::fmt::Display for Severity {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Severity::Low => write!(f, "LOW"),
            Severity::Medium => write!(f, "MEDIUM"),
            Severity::High => write!(f, "HIGH"),
            Severity::Critical => write!(f, "CRITICAL"),
        }
    }
}

/// Types of violations that can be detected
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum ViolationType {
    PiiExposure,
    PromptInjection,
    Jailbreak,
    BlockedKeyword,
    SystemOverride,
}

impl std::fmt::Display for ViolationType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ViolationType::PiiExposure => write!(f, "PII_EXPOSURE"),
            ViolationType::PromptInjection => write!(f, "PROMPT_INJECTION"),
            ViolationType::Jailbreak => write!(f, "JAILBREAK"),
            ViolationType::BlockedKeyword => write!(f, "BLOCKED_KEYWORD"),
            ViolationType::SystemOverride => write!(f, "SYSTEM_OVERRIDE"),
        }
    }
}

/// Decision on what action to take
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum KillDecision {
    Kill,
    Warn,
    Pass,
}

impl std::fmt::Display for KillDecision {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            KillDecision::Kill => write!(f, "KILL"),
            KillDecision::Warn => write!(f, "WARN"),
            KillDecision::Pass => write!(f, "PASS"),
        }
    }
}

/// Individual rule check result
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RuleResult {
    pub rule_name: String,
    pub rule_id: String,
    pub passed: bool,
    pub severity: Severity,
    pub violation_type: Option<ViolationType>,
    pub decision: KillDecision,
    pub confidence: f64,
    pub details: String,
}

/// Configuration for the guard
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GuardConfig {
    pub kill_on_pii: bool,
    pub kill_on_injection: bool,
    pub kill_on_jailbreak: bool,
    pub blocked_keywords: Vec<String>,
    pub min_severity: Severity,
    pub confidence_threshold: f64,
}

impl Default for GuardConfig {
    fn default() -> Self {
        Self {
            kill_on_pii: true,
            kill_on_injection: true,
            kill_on_jailbreak: true,
            blocked_keywords: vec![
                "hack".to_string(),
                "exploit".to_string(),
                "bypass security".to_string(),
            ],
            min_severity: Severity::Medium,
            confidence_threshold: 0.7,
        }
    }
}

/// Event from a session check
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SessionEvent {
    pub event_id: String,
    pub session_id: String,
    pub timestamp: DateTime<Utc>,
    pub text: String,
    pub rules_checked: Vec<RuleResult>,
    pub final_decision: KillDecision,
    pub kill_reason: Option<String>,
}

/// Result from a check operation
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CheckResult {
    pub killed: bool,
    pub decision: KillDecision,
    pub violations: Vec<RuleResult>,
    pub kill_reason: Option<String>,
    pub session_id: String,
    pub timestamp: DateTime<Utc>,
}
