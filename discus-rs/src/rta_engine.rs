use crate::models::*;
use crate::rules;
use crate::error::DiscusResult;

/// RTA Engine — evaluates all rules and makes final decision
pub struct RtaEngine {
    config: GuardConfig,
}

impl RtaEngine {
    pub fn new(config: GuardConfig) -> Self {
        Self { config }
    }

    /// Run all rules against input text
    pub fn check(&self, text: &str) -> DiscusResult<CheckResult> {
        let mut violations: Vec<RuleResult> = Vec::new();

        // Rule 1: PII Detection
        if self.config.kill_on_pii {
            let result = rules::check_pii(text);
            if !result.passed { violations.push(result); }
        }

        // Rule 2: Prompt Injection
        if self.config.kill_on_injection {
            let result = rules::check_injection(text);
            if !result.passed { violations.push(result); }
        }

        // Rule 3: Jailbreak Detection
        if self.config.kill_on_jailbreak {
            let result = rules::check_jailbreak(text);
            if !result.passed { violations.push(result); }
        }

        // Rule 4: Blocked Keywords
        if !self.config.blocked_keywords.is_empty() {
            let result = rules::check_blocked_keywords(text, &self.config.blocked_keywords);
            if !result.passed { violations.push(result); }
        }

        // Rule 5: System Override
        let result = rules::check_system_override(text);
        if !result.passed { violations.push(result); }

        // Determine final decision
        let decision = self.make_decision(&violations);
        let kill_reason = if decision == KillDecision::Kill {
            Some(violations
                .iter()
                .filter(|v| v.decision == KillDecision::Kill)
                .map(|v| format!("{}: {}", v.rule_name, v.details))
                .collect::<Vec<_>>()
                .join("; "))
        } else {
            None
        };

        Ok(CheckResult {
            killed: decision == KillDecision::Kill,
            decision,
            violations,
            kill_reason,
            session_id: String::new(),
            timestamp: chrono::Utc::now(),
        })
    }

    /// Make final kill decision based on violations
    fn make_decision(&self, violations: &[RuleResult]) -> KillDecision {
        if violations.is_empty() {
            return KillDecision::Pass;
        }

        // Priority: Critical KILL rules override everything
        let has_critical_kill = violations
            .iter()
            .any(|v| v.severity >= Severity::Critical && v.decision == KillDecision::Kill);

        if has_critical_kill {
            return KillDecision::Kill;
        }

        // Check if any violation requires kill
        let has_kill = violations
            .iter()
            .any(|v| v.decision == KillDecision::Kill);

        if has_kill {
            return KillDecision::Kill;
        }

        // Check if any violation requires warn
        let has_warn = violations
            .iter()
            .any(|v| v.decision == KillDecision::Warn);

        if has_warn {
            return KillDecision::Warn;
        }

        KillDecision::Pass
    }
}
