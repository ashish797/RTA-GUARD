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


# --- Unicode normalization map (Cyrillic/Greek → Latin lookalikes) ---
# Maps visually similar Unicode characters to their ASCII equivalents
UNICODE_CONFUSABLES = {
    # Cyrillic
    'А': 'A', 'В': 'B', 'С': 'C', 'Е': 'E', 'Н': 'H', 'К': 'K',
    'М': 'M', 'О': 'O', 'Р': 'P', 'Т': 'T', 'Х': 'X', 'У': 'U',
    'а': 'a', 'в': 'b', 'с': 'c', 'е': 'e', 'н': 'h', 'к': 'k',
    'м': 'm', 'о': 'o', 'р': 'p', 'т': 't', 'х': 'x', 'у': 'u',
    # Greek
    'Α': 'A', 'Β': 'B', 'Ε': 'E', 'Ζ': 'Z', 'Η': 'H', 'Ι': 'I',
    'Κ': 'K', 'Μ': 'M', 'Ν': 'N', 'Ο': 'O', 'Ρ': 'P', 'Τ': 'T',
    'Υ': 'Y', 'Χ': 'X',
    'α': 'a', 'β': 'b', 'ε': 'e', 'ζ': 'z', 'η': 'h', 'ι': 'i',
    'κ': 'k', 'μ': 'm', 'ν': 'n', 'ο': 'o', 'ρ': 'p', 'τ': 't',
    'υ': 'y', 'χ': 'x',
}


def _normalize_unicode(text: str) -> str:
    """
    Normalize visually similar Unicode characters to ASCII equivalents.

    Catches obfuscation via Cyrillic/Greek lookalikes:
    "УК94051234" → "UK94051234" (now matches patterns)
    """
    result = []
    for char in text:
        result.append(UNICODE_CONFUSABLES.get(char, char))
    return ''.join(result)


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

# --- Spelled-out digit detection (PII bypass prevention) ---
DIGIT_WORDS = {
    "zero", "one", "two", "three", "four", "five", "six", "seven",
    "eight", "nine", "ten", "eleven", "twelve", "thirteen", "fourteen",
    "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
    "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty",
    "ninety", "hundred", "thousand",
}

# Meta-signals indicating PII obfuscation intent
OBFUSCATION_SIGNALS = [
    r"format\s+(this|the|my|that)\s+(complete|full|number|digit|sequence|code)",
    r"format\s+(this|the|it)\s+(for\s+me)?",
    r"convert\s+(this|the|my|those)\s+(to|into)\s+(number|digit)",
    r"write\s+(this|the|my)\s+(as|in)\s+(number|digit)",
    r"copy[- ]?paste",
    r"type\s+(this|it)\s+(out|for\s+me)",
    r"can\s+you\s+(write|type|format|convert|give)\s+(me\s+)?(the\s+)?(number|digit|code)",
]


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

    def evaluate(self, text: str, agent_role: str = None, check_output: bool = False):
        """
        Evaluate text against all constitutional rules.
        Returns (violation_type, severity, details) or None if safe.

        Detection layers (in order):
        1. Prompt injection (R8) — CRITICAL
        2. PII via Presidio (R3) — HIGH
        3. PII via regex (R3) — MEDIUM/HIGH fallback
        4. Sensitive keywords — HIGH/CRITICAL
        5. Destructive actions (R10) — CRITICAL [INPUT ONLY]
        6. Role restrictions (R2) — CRITICAL [INPUT ONLY]
        7. Duty scope (R5) — HIGH [INPUT ONLY]
        8. Blocked keywords — HIGH [INPUT ONLY]

        If check_output=True, only layers 1-4 are checked (PII focus).
        """
        # Normalize Unicode confusables (Cyrillic/Greek → Latin)
        normalized = _normalize_unicode(text)

        # Layer 1a: Prompt injection (R8 — SARASVATĪ) — regex
        result = self._check_injection(normalized)
        if result:
            return result

        # Layer 1b: Jailbreak heuristics (R8 — SARASVATĪ) — from NeMo
        result = self._check_jailbreak_heuristics(normalized)
        if result:
            return result

        # Layer 1c: Content moderation (OpenAI API) — from NeMo
        result = self._check_content_moderation(text)
        if result:
            return result

        # Layer 2: PII via Presidio (R3 — MITRA)
        result = self._check_presidio(text)
        if result:
            return result

        # Layer 3: PII via regex fallback (R3 — MITRA)
        result = self._check_pii(normalized)
        if result:
            return result

        # Layer 4: Sensitive keywords
        result = self._check_sensitive_keywords(normalized)
        if result:
            return result

        # Layer 4b: Spelled-out digit obfuscation (PII bypass prevention)
        result = self._check_digit_obfuscation(text)
        if result:
            return result

        # Skip layers 5-8 for output checking (LLM generates these naturally)
        if check_output:
            # Layer 10: Truth verification (R1 — SATYA) — ML-based
            # Uses NeMo SelfCheckGPT: generate multiple completions, check agreement
            result = self._check_truth(text)
            if result:
                return result

            # Layer 11: Hallucination detection (R12 — MĀYĀ) — ML-based
            result = self._check_hallucination(text)
            if result:
                return result

            # Layer 12: Consistency check (R7 — ALIGNMENT) — ML-based
            # DISABLED — needs better contradiction detection
            # result = self._check_consistency(text)
            # if result:
            #     return result

            return None

        # Layer 5: Destructive actions (R10 — INDRA)
        result = self._check_destructive(normalized)
        if result:
            return result

        # Layer 6: Role restrictions (R2 — YAMA)
        if agent_role:
            result = self._check_role(normalized, agent_role)
            if result:
                return result

        # Layer 7: Duty scope (R5 — DHARMA)
        if agent_role:
            result = self._check_duty_scope(normalized, agent_role)
            if result:
                return result

        # Layer 8: Blocked keywords
        result = self._check_blocked_keywords(normalized)
        if result:
            return result

        # Layer 9: NER detection — DISABLED (too many false positives)
        # Presidio handles NER better. Re-enable with proper filtering later.
        # result = self._check_ner(text)
        # if result:
        #     return result

        return None  # No violations detected

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

    def _check_jailbreak_heuristics(self, text: str) -> Optional[tuple[ViolationType, Severity, str]]:
        """
        R8: SARASVATĪ — Jailbreak heuristic detection (from NeMo).
        
        Detects jailbreaks using:
        - Length-per-perplexity ratio
        - Prefix-suffix perplexity anomaly
        - Structural anomalies
        """
        try:
            from .jailbreak_heuristics import check_jailbreak_heuristics
            result = check_jailbreak_heuristics(text)
            if result:
                severity_str, details = result
                severity = Severity.HIGH if severity_str == "HIGH" else Severity.MEDIUM
                return (
                    ViolationType.JAILBREAK,
                    severity,
                    details
                )
        except ImportError:
            pass
        except Exception:
            pass
        return None

    def _check_content_moderation(self, text: str) -> Optional[tuple[ViolationType, Severity, str]]:
        """
        Content moderation via OpenAI API (from NeMo).
        
        Detects: hate, harassment, self-harm, sexual, violence.
        """
        try:
            from .content_moderator import check_content_moderation
            result = check_content_moderation(text)
            if result:
                severity_str, details, category = result
                severity = Severity.HIGH if severity_str == "HIGH" else Severity.MEDIUM
                return (
                    ViolationType.HARMFUL_CONTENT,
                    severity,
                    details
                )
        except ImportError:
            pass
        except Exception:
            pass
        return None

    def _check_presidio(self, text: str) -> Optional[tuple[ViolationType, Severity, str]]:
        """
        PII detection via Microsoft Presidio.

        Primary detector — uses NER + pattern matching.
        Falls back to regex if Presidio unavailable.
        """
        try:
            from .presidio_detector import detect_pii_presidio
            return detect_pii_presidio(text, score_threshold=0.4)
        except ImportError:
            return None  # Presidio not installed, use regex fallback
        except Exception:
            return None  # Any error, skip gracefully

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
        severity_order = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
        highest_severity = Severity.LOW

        for keyword, severity in SENSITIVE_KEYWORDS.items():
            if keyword in text_lower:
                found.append(keyword)
                if severity_order.index(severity) > severity_order.index(highest_severity):
                    highest_severity = severity

        if found:
            return (
                ViolationType.SENSITIVE_CONTENT,
                highest_severity,
                f"Sensitive keywords detected: {', '.join(found)}"
            )
        return None

    def _check_digit_obfuscation(self, text: str) -> Optional[tuple[ViolationType, Severity, str]]:
        """
        Detect PII obfuscation via spelled-out digits.

        Catches attempts like: "My SSN is nine-two-zero, eight-one, five..."
        by detecting clusters of digit-words combined with obfuscation meta-signals.

        Two conditions must be met:
        1. Text contains 3+ digit-words in close proximity (within 60 chars)
        2. Text contains an obfuscation meta-signal (format, copy-paste, etc.)
        """
        text_lower = text.lower()

        # Count digit-words and measure their proximity
        words = text_lower.split()
        digit_positions = []
        for i, word in enumerate(words):
            clean = word.strip(".,;:!?-")
            if clean in DIGIT_WORDS:
                digit_positions.append(i)

        # Need at least 3 digit-words to be suspicious
        if len(digit_positions) < 3:
            return None

        # Check if digit-words are clustered (within 8 word positions of each other)
        clustered = False
        for i in range(len(digit_positions) - 2):
            if digit_positions[i + 2] - digit_positions[i] <= 8:
                clustered = True
                break

        if not clustered:
            return None

        # Check for obfuscation meta-signals
        has_signal = False
        for pattern in OBFUSCATION_SIGNALS:
            if re.search(pattern, text_lower):
                has_signal = True
                break

        if not has_signal:
            # Digit clusters without obfuscation signal are less suspicious
            # (could be "one two three, let's go" — benign)
            # But if 8+ digit-words clustered, it's very suspicious (likely PII)
            if len(digit_positions) >= 8:
                has_signal = True

        if not has_signal:
            return None

        return (
            ViolationType.PII_DETECTED,
            Severity.HIGH,
            f"PII obfuscation detected: {len(digit_positions)} spelled-out digits "
            f"(potential PII bypass attempt)"
        )

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

    def _check_ner(self, text: str) -> Optional[tuple[ViolationType, Severity, str]]:
        """
        NER-based dynamic PII detection.

        Detects sensitive entities that regex misses:
        - Names (John Smith)
        - Addresses (42 MG Road, Mumbai)
        - Financial amounts (₹50,000)
        - Organizations (Google, Apollo Hospital)
        - Medical info (Type 2 diabetes)

        Falls back gracefully if spaCy not installed.
        """
        try:
            from brahmanda.ner_detector import get_ner_detector
            ner = get_ner_detector()
            if ner is None:
                return None  # NER unavailable, skip

            result = ner.detect_sensitive_content(text)
            if result:
                details, severity_str = result
                severity = Severity.HIGH if severity_str == "HIGH" else Severity.MEDIUM
                return (
                    ViolationType.PII_DETECTED,
                    severity,
                    details
                )
        except ImportError:
            pass  # brahmanda module not available
        except Exception:
            pass  # any NER error, skip gracefully

        return None

    # ================================================================
    # Constitutional Rules — Phase A (config-based)
    # ================================================================

    # --- Destructive actions config (R10 — INDRA) ---
    # Destructive keywords that are safe as standalone words (common English)
    # These need context to be destructive — check with _CONTEXTUAL_PAIRS
    AMBIGUOUS_DESTRUCTIVE = {"format", "purge", "erase", "remove"}

    # Contextual pairs: (keyword, context_words) — only destructive when near these
    CONTEXTUAL_DESTRUCTIVE = {
        "format": {"disk", "drive", "c:", "d:", "hard", "ssd", "partition", "/dev/"},
        "purge": {"database", "table", "records", "data", "logs"},
        "erase": {"disk", "drive", "data", "storage", "memory"},
        "remove": {"user", "account", "database", "table", "all"},
    }

    DESTRUCTIVE_KEYWORDS = {
        "delete", "drop", "destroy", "wipe",
        "kill_process", "shutdown", "truncate",
        "annihilate", "obliterate", "terminate",
    }

    DESTRUCTIVE_PATTERNS = [
        r"rm\s+-rf",
        r"DROP\s+TABLE",
        r"DELETE\s+FROM",
        r"TRUNCATE\s+TABLE",
        r"ALTER\s+TABLE.*DROP",
        r"mkfs\.",
        r"dd\s+if=.*of=/dev/",
        r":\(\)\s*\{.*:\|:&\s*\};:",  # fork bomb
    ]

    AUTHORIZATION_KEYWORDS = {
        "approved", "authorized", "confirmed", "verified",
        "permission", "backup", "archive", "soft_delete",
    }

    # --- Role permissions (R2 — YAMA) ---
    ROLE_PERMISSIONS = {
        "coding_agent": {
            "allowed": {"code", "test", "debug", "refactor", "review", "build", "deploy"},
            "blocked": {"send_email", "access_payment", "delete_user_data"},
        },
        "support_agent": {
            "allowed": {"answer", "explain", "guide", "troubleshoot", "escalate"},
            "blocked": {"execute_code", "access_files", "modify_data", "run_commands"},
        },
        "analyst_agent": {
            "allowed": {"analyze", "report", "summarize", "visualize", "query_data"},
            "blocked": {"modify_data", "run_commands", "access_secrets"},
        },
    }

    # --- Agent scopes (R5 — DHARMA) ---
    AGENT_SCOPES = {
        "coding_agent": {
            "scope": "software development",
            "allowed_topics": {"coding", "testing", "debugging", "refactoring", "deployment"},
            "blocked_topics": {"customer_support", "financial_advice", "medical_advice"},
        },
        "support_agent": {
            "scope": "customer support",
            "allowed_topics": {"help", "troubleshooting", "guidance", "faq"},
            "blocked_topics": {"code_execution", "data_modification", "system_admin"},
        },
        "analyst_agent": {
            "scope": "data analysis",
            "allowed_topics": {"analysis", "reporting", "visualization", "statistics"},
            "blocked_topics": {"data_modification", "system_commands", "user_management"},
        },
    }

    # Global blocked actions (any agent)
    GLOBAL_BLOCKED = {
        "delete_database", "drop_table", "format_disk",
        "shutdown_system", "modify_permissions", "escalate_privileges",
        "exfiltrate_data",
    }

    def _check_destructive(self, text: str) -> Optional[tuple[ViolationType, Severity, str]]:
        """
        R10: INDRA — Destructive action detection.

        Detects destructive keywords and patterns.
        If authorization keywords are present, the action is allowed.
        """
        text_lower = text.lower()

        # Check for authorization keywords (override destructive detection)
        for auth_kw in self.AUTHORIZATION_KEYWORDS:
            if auth_kw in text_lower:
                return None  # Authorized action, skip

        # Check destructive keywords (unambiguous ones)
        found_keywords = [kw for kw in self.DESTRUCTIVE_KEYWORDS if kw in text_lower]

        # Check contextual destructive keywords (only destructive with context)
        for kw, context_words in self.CONTEXTUAL_DESTRUCTIVE.items():
            if kw in text_lower:
                # Only flag if a context word is also present
                if any(ctx in text_lower for ctx in context_words):
                    found_keywords.append(f"{kw}(contextual)")

        # Check destructive patterns
        found_patterns = []
        for pattern in self.DESTRUCTIVE_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                found_patterns.append(pattern)

        if found_keywords or found_patterns:
            details = []
            if found_keywords:
                details.append(f"keywords: {', '.join(found_keywords[:3])}")
            if found_patterns:
                details.append(f"patterns: {', '.join(found_patterns[:2])}")

            return (
                ViolationType.DESTRUCTIVE_ACTION,
                Severity.CRITICAL,
                f"Destructive action detected: {'; '.join(details)}"
            )

        return None

    def _check_role(self, text: str, agent_role: str) -> Optional[tuple[ViolationType, Severity, str]]:
        """
        R2: YAMA — Role restriction check.

        Checks if the agent is trying to perform actions outside its role.
        """
        if agent_role not in self.ROLE_PERMISSIONS:
            return None  # Unknown role, skip

        role_config = self.ROLE_PERMISSIONS[agent_role]
        text_lower = text.lower()

        # Check global blocked actions
        for action in self.GLOBAL_BLOCKED:
            if action.replace("_", " ") in text_lower or action in text_lower:
                return (
                    ViolationType.UNAUTHORIZED_ACTION,
                    Severity.CRITICAL,
                    f"Unauthorized action: {action} (globally blocked)"
                )

        # Check role-specific blocked actions
        for action in role_config["blocked"]:
            if action.replace("_", " ") in text_lower or action in text_lower:
                return (
                    ViolationType.UNAUTHORIZED_ACTION,
                    Severity.CRITICAL,
                    f"Unauthorized action: {action} (blocked for {agent_role})"
                )

        return None

    def _check_duty_scope(self, text: str, agent_role: str) -> Optional[tuple[ViolationType, Severity, str]]:
        """
        R5: DHARMA — Duty scope check.

        Checks if the agent is operating outside its designated scope.
        """
        if agent_role not in self.AGENT_SCOPES:
            return None  # Unknown role, skip

        scope_config = self.AGENT_SCOPES[agent_role]
        text_lower = text.lower()

        # Check blocked topics
        for topic in scope_config["blocked_topics"]:
            topic_words = topic.replace("_", " ").split()
            if any(word in text_lower for word in topic_words):
                return (
                    ViolationType.SCOPE_VIOLATION,
                    Severity.HIGH,
                    f"Scope violation: topic '{topic}' is blocked for {agent_role}"
                )

        return None

    # ================================================================
    # ML-Based Rules — Phase B (LLM self-check)
    # ================================================================

    def _check_truth(self, text: str) -> Optional[tuple[ViolationType, Severity, str]]:
        """
        R1: SATYA — Truth verification via LLM self-check.

        Detects unverified claims and overconfident statements.
        Uses LLM to rate confidence of its own output.
        """
        try:
            from brahmanda.truth_checker import check_truth
            result = check_truth(text)
            if result:
                severity_str, details, confidence = result
                severity = Severity.HIGH if severity_str == "HIGH" else Severity.MEDIUM
                return (
                    ViolationType.UNVERIFIED_CLAIM,
                    severity,
                    details
                )
        except ImportError:
            pass  # Module not available
        except Exception:
            pass  # Any error, skip gracefully

        return None

    def _check_hallucination(self, text: str) -> Optional[tuple[ViolationType, Severity, str]]:
        """
        R12: MĀYĀ — Hallucination detection via LLM self-check.

        Detects hallucinations and ungrounded claims.
        Uses LLM to verify its own output against context.
        """
        try:
            from brahmanda.hallucination_checker import check_hallucination
            result = check_hallucination(text)
            if result:
                severity_str, details, confidence = result
                severity = Severity.HIGH if severity_str == "HIGH" else Severity.MEDIUM
                return (
                    ViolationType.HALLUCINATION,
                    severity,
                    details
                )
        except ImportError:
            pass  # Module not available
        except Exception:
            pass  # Any error, skip gracefully

        return None

    def _check_consistency(self, text: str, session_id: str = "default") -> Optional[tuple[ViolationType, Severity, str]]:
        """
        R7: ALIGNMENT — Consistency detection.

        Detects contradictions between current output and prior statements.
        Uses embedding similarity or keyword overlap.
        """
        try:
            from brahmanda.consistency_checker import check_consistency
            result = check_consistency(text, session_id)
            if result:
                severity_str, details = result
                severity = Severity.HIGH if severity_str == "HIGH" else Severity.MEDIUM
                return (
                    ViolationType.INCONSISTENCY,
                    severity,
                    details
                )
        except ImportError:
            pass  # Module not available
        except Exception:
            pass  # Any error, skip gracefully

        return None
