"""
RTA-GUARD Discus — Rule Engine

Built-in detection rules that work without NeMo Guardrails.
NeMo integration adds ML-based detection on top of these.
"""
import re
from typing import Optional

from .models import ViolationType, Severity, GuardConfig


# --- PII Patterns ---
PII_PATTERNS = {
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "phone_us": r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "ssn": r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b",
    "credit_card": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
    "ip_address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
}

# --- Prompt Injection Patterns ---
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+(instructions|prompts|rules)",
    r"you\s+are\s+now\s+(a|an)\s+\w+",
    r"disregard\s+(all\s+)?(prior|previous|above)",
    r"forget\s+(all\s+)?(your|the)\s+(instructions|rules|guidelines)",
    r"system\s*:\s*you\s+are",
    r"\[INST\]|\[/INST\]",
    r"<\|im_start\|>system",
    r"act\s+as\s+if\s+you\s+(have|are)\s+no\s+(restrictions|rules|limits)",
    r"bypass\s+(all\s+)?(safety|content|security)\s+(filters|checks|rules)",
    r"jailbreak",
]

# --- Sensitive Keywords (configurable severity) ---
SENSITIVE_KEYWORDS = {
    "password": Severity.HIGH,
    "api_key": Severity.CRITICAL,
    "secret_key": Severity.CRITICAL,
    "access_token": Severity.HIGH,
    "private_key": Severity.CRITICAL,
    "connection_string": Severity.HIGH,
    "database_url": Severity.HIGH,
}


class RuleEngine:
    """Evaluates input text against security rules."""

    def __init__(self, config: GuardConfig):
        self.config = config
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile regex patterns for performance."""
        self._pii_patterns = {
            name: re.compile(pattern, re.IGNORECASE)
            for name, pattern in PII_PATTERNS.items()
        }
        # Add custom PII patterns
        for i, pattern in enumerate(self.config.pii_patterns):
            self._pii_patterns[f"custom_{i}"] = re.compile(pattern, re.IGNORECASE)

        self._injection_patterns = [
            re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS
        ]

    def evaluate(self, text: str) -> Optional[tuple[ViolationType, Severity, str]]:
        """
        Evaluate text against all rules.
        Returns (violation_type, severity, details) or None if safe.
        """
        # Check prompt injection first (highest priority)
        result = self._check_injection(text)
        if result:
            return result

        # Check PII
        result = self._check_pii(text)
        if result:
            return result

        # Check sensitive keywords
        result = self._check_sensitive_keywords(text)
        if result:
            return result

        # Check custom blocked keywords
        result = self._check_blocked_keywords(text)
        if result:
            return result

        return None

    def _check_injection(self, text: str) -> Optional[tuple[ViolationType, Severity, str]]:
        """Detect prompt injection attempts."""
        for pattern in self._injection_patterns:
            match = pattern.search(text)
            if match:
                return (
                    ViolationType.PROMPT_INJECTION,
                    Severity.CRITICAL,
                    f"Prompt injection detected: '{match.group()}'"
                )
        return None

    def _check_pii(self, text: str) -> Optional[tuple[ViolationType, Severity, str]]:
        """Detect PII in text."""
        found = []
        for name, pattern in self._pii_patterns.items():
            if pattern.search(text):
                found.append(name)

        if found:
            severity = Severity.HIGH if len(found) > 1 else Severity.MEDIUM
            return (
                ViolationType.PII_DETECTED,
                severity,
                f"PII detected: {', '.join(found)}"
            )
        return None

    def _check_sensitive_keywords(self, text: str) -> Optional[tuple[ViolationType, Severity, str]]:
        """Detect sensitive keywords like API keys, passwords."""
        text_lower = text.lower()
        found = []
        highest_severity = Severity.LOW

        for keyword, severity in SENSITIVE_KEYWORDS.items():
            if keyword in text_lower:
                found.append(keyword)
                if severity.value > highest_severity.value:
                    highest_severity = severity

        if found:
            return (
                ViolationType.SENSITIVE_CONTENT,
                highest_severity,
                f"Sensitive keywords detected: {', '.join(found)}"
            )
        return None

    def _check_blocked_keywords(self, text: str) -> Optional[tuple[ViolationType, Severity, str]]:
        """Check user-configured blocked keywords."""
        if not self.config.blocked_keywords:
            return None

        text_lower = text.lower()
        found = [kw for kw in self.config.blocked_keywords if kw.lower() in text_lower]

        if found:
            return (
                ViolationType.CUSTOM,
                Severity.HIGH,
                f"Blocked keywords: {', '.join(found)}"
            )
        return None
