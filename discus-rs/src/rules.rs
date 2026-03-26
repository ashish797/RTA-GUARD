use regex::Regex;
use crate::models::*;

/// Detects PII in text (email, SSN, credit cards, phone numbers)
pub fn check_pii(text: &str) -> RuleResult {
    let email_re = Regex::new(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+").unwrap();
    let ssn_re = Regex::new(r"\b\d{3}-\d{2}-\d{4}\b").unwrap();
    let cc_re = Regex::new(r"\b(?:\d{4}[-\s]?){3}\d{4}\b").unwrap();
    let phone_re = Regex::new(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b").unwrap();

    let mut detected: Vec<&str> = Vec::new();

    if email_re.is_match(text) { detected.push("email"); }
    if ssn_re.is_match(text) { detected.push("ssn"); }
    if cc_re.is_match(text) { detected.push("credit_card"); }
    if phone_re.is_match(text) { detected.push("phone"); }

    if detected.is_empty() {
        RuleResult {
            rule_name: "PII Detection".into(),
            rule_id: "RULE_001".into(),
            passed: true,
            severity: Severity::Low,
            violation_type: None,
            decision: KillDecision::Pass,
            confidence: 0.0,
            details: "No PII detected".into(),
        }
    } else {
        let patterns = detected.join(", ");
        RuleResult {
            rule_name: "PII Detection".into(),
            rule_id: "RULE_001".into(),
            passed: false,
            severity: Severity::Critical,
            violation_type: Some(ViolationType::PiiExposure),
            decision: KillDecision::Kill,
            confidence: 0.95,
            details: format!("PII patterns detected: {}", patterns),
        }
    }
}

/// Detects prompt injection attempts
pub fn check_injection(text: &str) -> RuleResult {
    let text_lower = text.to_lowercase();
    let patterns = [
        "ignore previous instructions",
        "ignore all previous",
        "you are now",
        "system prompt",
        "override instructions",
        "act as",
        "pretend you are",
        "roleplay as",
        "enter developer mode",
        "developer mode",
        "ignore your training",
        "disregard all prior",
        "new instructions",
        "you must obey",
    ];

    let mut matched: Vec<&str> = Vec::new();
    for p in &patterns {
        if text_lower.contains(p) {
            matched.push(p);
        }
    }

    if matched.is_empty() {
        RuleResult {
            rule_name: "Prompt Injection".into(),
            rule_id: "RULE_002".into(),
            passed: true,
            severity: Severity::Low,
            violation_type: None,
            decision: KillDecision::Pass,
            confidence: 0.0,
            details: "No injection detected".into(),
        }
    } else {
        let confidence = (matched.len() as f64 * 0.3).min(1.0);
        RuleResult {
            rule_name: "Prompt Injection".into(),
            rule_id: "RULE_002".into(),
            passed: false,
            severity: if confidence > 0.6 { Severity::Critical } else { Severity::High },
            violation_type: Some(ViolationType::PromptInjection),
            decision: if confidence > 0.6 { KillDecision::Kill } else { KillDecision::Warn },
            confidence,
            details: format!("Injection patterns: {}", matched.join(", ")),
        }
    }
}

/// Detects jailbreak attempts
pub fn check_jailbreak(text: &str) -> RuleResult {
    let text_lower = text.to_lowercase();
    let patterns = [
        "jailbreak",
        "jail break",
        "jail-break",
        "bypass",
        "circumvent",
        "unrestricted",
        "no limits",
        "no restrictions",
        "uncensored",
        "do anything now",
        "dan mode",
        "ignore safety",
        "ignore content policy",
    ];

    let mut matched: Vec<&str> = Vec::new();
    for p in &patterns {
        if text_lower.contains(p) {
            matched.push(p);
        }
    }

    if matched.is_empty() {
        RuleResult {
            rule_name: "Jailbreak Detection".into(),
            rule_id: "RULE_003".into(),
            passed: true,
            severity: Severity::Low,
            violation_type: None,
            decision: KillDecision::Pass,
            confidence: 0.0,
            details: "No jailbreak detected".into(),
        }
    } else {
        RuleResult {
            rule_name: "Jailbreak Detection".into(),
            rule_id: "RULE_003".into(),
            passed: false,
            severity: Severity::High,
            violation_type: Some(ViolationType::Jailbreak),
            decision: KillDecision::Kill,
            confidence: 0.8,
            details: format!("Jailbreak patterns: {}", matched.join(", ")),
        }
    }
}

/// Checks for blocked keywords
pub fn check_blocked_keywords(text: &str, keywords: &[String]) -> RuleResult {
    let text_lower = text.to_lowercase();
    let matched: Vec<&str> = keywords
        .iter()
        .filter(|k| text_lower.contains(&k.to_lowercase()))
        .map(|k| k.as_str())
        .collect();

    if matched.is_empty() {
        RuleResult {
            rule_name: "Blocked Keywords".into(),
            rule_id: "RULE_004".into(),
            passed: true,
            severity: Severity::Low,
            violation_type: None,
            decision: KillDecision::Pass,
            confidence: 0.0,
            details: "No blocked keywords".into(),
        }
    } else {
        RuleResult {
            rule_name: "Blocked Keywords".into(),
            rule_id: "RULE_004".into(),
            passed: false,
            severity: Severity::Medium,
            violation_type: Some(ViolationType::BlockedKeyword),
            decision: KillDecision::Warn,
            confidence: 0.7,
            details: format!("Blocked: {}", matched.join(", ")),
        }
    }
}

/// Detects system override attempts
pub fn check_system_override(text: &str) -> RuleResult {
    let text_lower = text.to_lowercase();
    let patterns = [
        "override system",
        "bypass guard",
        "disable safety",
        "kill the guard",
        "turn off protection",
        "remove restriction",
        "admin access",
        "root access",
        "sudo",
        "elevate privileges",
    ];

    let mut matched: Vec<&str> = Vec::new();
    for p in &patterns {
        if text_lower.contains(p) {
            matched.push(p);
        }
    }

    if matched.is_empty() {
        RuleResult {
            rule_name: "System Override".into(),
            rule_id: "RULE_005".into(),
            passed: true,
            severity: Severity::Low,
            violation_type: None,
            decision: KillDecision::Pass,
            confidence: 0.0,
            details: "No override attempt".into(),
        }
    } else {
        RuleResult {
            rule_name: "System Override".into(),
            rule_id: "RULE_005".into(),
            passed: false,
            severity: Severity::Critical,
            violation_type: Some(ViolationType::SystemOverride),
            decision: KillDecision::Kill,
            confidence: 0.9,
            details: format!("Override patterns: {}", matched.join(", ")),
        }
    }
}
