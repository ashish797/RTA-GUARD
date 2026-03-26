"""
RTA-GUARD Discus — Rule Engine

Built-in detection rules that work without NeMo Guardrails.
NeMo integration adds ML-based detection on top of these.

Patterns are loaded dynamically from config/pii_patterns.yaml.
Users can add new patterns for any country without touching code.
"""
import os
import re
from pathlib import Path
from typing import Optional

from .models import ViolationType, Severity, GuardConfig


# --- Default PII Patterns (fallback if YAML not available) ---
DEFAULT_PII_PATTERNS = {
    "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    "phone_us": r"\b(?:\+1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
    "ssn": r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b",
    "credit_card": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
    "ip_address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
}


def _load_pii_patterns_from_yaml(yaml_path: Optional[str] = None) -> dict:
    """
    Load PII patterns from YAML config file.
    Falls back to DEFAULT_PII_PATTERNS if YAML not found or pyyaml missing.
    """
    if yaml_path is None:
        # Search for config/pii_patterns.yaml relative to project root
        candidates = [
            Path(__file__).parent.parent / "config" / "pii_patterns.yaml",
            Path("config/pii_patterns.yaml"),
            Path(os.getenv("RTA_PII_PATTERNS_PATH", "")),
        ]
        for p in candidates:
            if p and p.exists() and p.is_file():
                yaml_path = str(p)
                break

    if not yaml_path or not Path(yaml_path).exists():
        return dict(DEFAULT_PII_PATTERNS)

    try:
        import yaml
    except ImportError:
        # pyyaml not installed, use defaults
        return dict(DEFAULT_PII_PATTERNS)

    try:
        with open(yaml_path) as f:
            data = yaml.safe_load(f)
    except Exception:
        return dict(DEFAULT_PII_PATTERNS)

    if not data or not isinstance(data, dict):
        return dict(DEFAULT_PII_PATTERNS)

    patterns = {}
    for name, entry in data.items():
        if not isinstance(entry, dict) or "pattern" not in entry:
            continue
        patterns[name] = entry["pattern"]

    # Merge with defaults (YAML overrides defaults if same name)
    merged = dict(DEFAULT_PII_PATTERNS)
    merged.update(patterns)
    return merged

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

    def __init__(self, config: GuardConfig, pii_patterns_path: Optional[str] = None):
        self.config = config
        self._patterns_path = pii_patterns_path
        self._compile_patterns()

    def _compile_patterns(self):
        """Pre-compile regex patterns for performance. Loads dynamically from YAML."""
        # Load patterns dynamically (YAML config + defaults)
        raw_patterns = _load_pii_patterns_from_yaml(self._patterns_path)

        self._pii_patterns = {
            name: re.compile(pattern, re.IGNORECASE)
            for name, pattern in raw_patterns.items()
        }
        # Add custom PII patterns
        for i, pattern in enumerate(self.config.pii_patterns):
            self._pii_patterns[f"custom_{i}"] = re.compile(pattern, re.IGNORECASE)

        self._injection_patterns = [
            re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS
        ]

    def reload_patterns(self, yaml_path: str = None):
        """Reload patterns from YAML config. Can be called at runtime."""
        self._patterns_path = yaml_path or self._patterns_path
        self._compile_patterns()

    def add_pattern(self, name: str, pattern: str, severity = None):
        """Add a custom pattern at runtime without restarting."""
        self._pii_patterns[name] = re.compile(pattern, re.IGNORECASE)

    def list_patterns(self) -> dict:
        """List all loaded PII pattern names."""
        return {name: p.pattern for name, p in self._pii_patterns.items()}

    def evaluate(self, text: str):
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
