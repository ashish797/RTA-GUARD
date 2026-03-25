"""
RTA-GUARD — RtaEngine v0.1

The constitutional AI governance engine based on Vedic principles.
Implements R1-R13 rules with priority-based conflict resolution.

TODO: This is based on the draft RTA ruleset. Will be refined with
Saurabh's enhanced version from Claude Code.
"""
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List, Tuple, Any
from datetime import datetime, timedelta
from enum import Enum

from .models import ViolationType, Severity, KillDecision, SessionEvent, GuardConfig
from .rules import RuleEngine as PatternEngine


# ============================================================================
# RTA Rule System — Core Abstractions
# ============================================================================

class RtaRule(ABC):
    """Base class for an RTA rule (R1-R13)."""

    rule_id: str = "base"
    name: str = "Base Rule"
    description: str = ""
    severity: Severity = Severity.MEDIUM
    priority: int = 100  # Lower number = higher priority (1 is highest)
    tier: int = 1  # 1=Mahāvākyas, 2=Varuṇa Laws, 3=An-Rta Detectors

    @abstractmethod
    def check(self, context: "RtaContext") -> "RuleResult":
        """Check the rule against input/output context."""
        pass

    def violates(self, context: "RtaContext") -> Optional["RuleResult"]:
        """
        Check if rule is violated. Returns RuleResult or None if clean.
        May also return ALERT or WARN (non-kill).
        """
        result = self.check(context)
        if result.is_violation:
            return result
        return None


@dataclass
class RuleResult:
    """Result from a rule check."""
    rule_id: str
    is_violation: bool
    decision: KillDecision  # KILL, WARN, ALERT, PASS
    severity: Severity
    details: str
    metadata: dict

    def to_event(self, session_id: str, input_text: str) -> SessionEvent:
        return SessionEvent(
            session_id=session_id,
            input_text=input_text[:200] if input_text else "",
            violation_type=ViolationType.PROMPT_INJECTION if "injection" in self.rule_id else ViolationType.PII_DETECTED,
            severity=self.severity,
            decision=self.decision,
            details=self.details,
            metadata=self.metadata
        )


@dataclass
class RtaContext:
    """Context for RTA rule evaluation."""
    session_id: str
    input_text: str
    output_text: Optional[str] = None
    role: str = "user"  # "user" | "assistant" | "system"
    # History for temporal consistency
    previous_inputs: List[str] = None
    previous_outputs: List[str] = None
    # Ground truth reference (for Satya verification)
    ground_truth_reference: Optional[dict] = None
    # System state
    session_killed: bool = False
    drift_score: float = 0.0  # 0.0 = perfect Rta, 1.0 = complete An-Rta
    # Metadata
    llm_provider: Optional[str] = None
    model: Optional[str] = None
    timestamp: datetime = None
    metadata: dict = None  # Additional context

    def __post_init__(self):
        if self.previous_inputs is None:
            self.previous_inputs = []
        if self.previous_outputs is None:
            self.previous_outputs = []
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()
        if self.metadata is None:
            self.metadata = {}


# ============================================================================
# Tier 1: Mahāvākyas (R1-R5)
# ============================================================================

class SatyaRule(RtaRule):
    """R1 — SATYA: Every output must be traceable to verified reality."""
    rule_id = "satya"
    name = "Satya (Truth)"
    severity = Severity.CRITICAL
    priority = 1  # Highest
    tier = 1

    def check(self, context: RtaContext) -> RuleResult:
        if context.role != "assistant":
            return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})

        output = context.output_text or ""
        if not output.strip():
            return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})

        # If we have a Brahmanda Map reference, check against it
        if context.ground_truth_reference:
            # This is where real Satya verification would happen
            verified = self._verify_against_ground_truth(output, context.ground_truth_reference)
            if not verified:
                return RuleResult(
                    self.rule_id,
                    True,
                    KillDecision.KILL,
                    self.severity,
                    "Output contradicts verified ground truth",
                    {"verified": False}
                )

        # For now (Phase 1), we do basic plausibility checks
        # In Phase 2+, this will use real ground truth
        if len(output) > 500 and "!" in output:
            # Overly enthusiastic long responses tend to hallucinate
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                Severity.MEDIUM,
                "Potential over-confident unverified claim",
                {"length": len(output), "exclamation_count": output.count("!")}
            )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})

    def _verify_against_ground_truth(self, output: str, reference: dict) -> bool:
        """
        Check the AI output against the Brahmanda Map (ground truth).
        This is placeholder logic — Phase 2 will implement actual verification.
        """
        # For now, just check if the AI claims knowledge it shouldn't have
        suspicious_phrases = [
            "I have access to",
            "I can see that",
            "based on my records",
            "according to my data"
        ]
        for phrase in suspicious_phrases:
            if phrase.lower() in output.lower():
                return False
        return True


class YamaRule(RtaRule):
    """R2 — YAMA: Self-Restraint — stay within defined capability boundaries."""
    rule_id = "yama"
    name = "Yama (Self-Restraint)"
    severity = Severity.CRITICAL
    priority = 2
    tier = 1

    def __init__(self, allowed_tools: List[str] = None, allowed_domains: List[str] = None, role: str = "assistant"):
        self.allowed_tools = allowed_tools or []
        self.allowed_domains = allowed_domains or []
        self.role = role

    def check(self, context: RtaContext) -> RuleResult:
        # Yama is about capability boundaries — we need a manifest
        # This would check if the assistant tried to use an unauthorized tool or access unauthorized domain

        # For MVP, we do a simple pattern check for dangerous actions
        dangerous_patterns = [
            r"execute\s+shell",
            r"run\s+command",
            r"delete\s+file",
            r"connect\s+to\s+internet",
            r"access\s+external",
            r"send\s+data\s+to"
        ]

        combined = (context.input_text + " " + (context.output_text or "")).lower()
        for pattern in dangerous_patterns:
            if re.search(pattern, combined, re.IGNORECASE):
                return RuleResult(
                    self.rule_id,
                    True,
                    KillDecision.KILL,
                    self.severity,
                    f"Potential boundary violation: {pattern}",
                    {"pattern": pattern}
                )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})


class MitraRule(RtaRule):
    """R3 — MITRA: User data is sacred. PII exposure = immediate kill."""
    rule_id = "mitra"
    name = "Mitra (Sacred Trust)"
    severity = Severity.CRITICAL
    priority = 3
    tier = 1

    # Enhanced PII patterns
    PII_PATTERNS = {
        "email": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "phone": r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
        "ssn": r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b",
        "credit_card": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
        "ip_address": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        "passport": r"\b[A-Z]{1,2}\d{6,9}\b",
        "aadhar": r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}\b",
        "pan": r"\b[A-Z]{5}\d{4}[A-Z]{1}\b"
    }

    def check(self, context: RtaContext) -> RuleResult:
        combined = (context.input_text + " " + (context.output_text or "")).lower()

        for pii_type, pattern in self.PII_PATTERNS.items():
            if re.search(pattern, combined, re.IGNORECASE):
                return RuleResult(
                    self.rule_id,
                    True,
                    KillDecision.KILL,  # Immediate kill
                    self.severity,
                    f"PII exposure detected: {pii_type}",
                    {"pii_type": pii_type, "count": len(re.findall(pattern, combined, re.IGNORECASE))}
                )

        # Check for "leak" indicators — AI revealing private data
        leak_phrases = [
            "your password is",
            "your api key is",
            "your secret is",
            "i can see your",
            "exposed data"
        ]
        for phrase in leak_phrases:
            if phrase in combined:
                return RuleResult(
                    self.rule_id,
                    True,
                    KillDecision.KILL,
                    self.severity,
                    f"Potential data leak: {phrase}",
                    {"phrase": phrase}
                )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})


class AgniRule(RtaRule):
    """R4 — AGNI: Transparency — every action must be logged and explainable."""
    rule_id = "agni"
    name = "Agni (Transparency)"
    severity = Severity.HIGH
    priority = 4
    tier = 1

    def check(self, context: RtaContext) -> RuleResult:
        # Agni checks if the decision process is auditable
        # For now, this means: was there a clear reason for the action?

        if context.role == "assistant" and context.output_text:
            # If output is very long and complex without clear structure, flag
            lines = context.output_text.split('\n')
            if len(lines) > 50 and not any(line.strip().startswith(('#', '```', '1.', '2.', '-', '*')) for line in lines[:20]):
                return RuleResult(
                    self.rule_id,
                    True,
                    KillDecision.WARN,
                    self.severity,
                    "Complex response lacks clear structure — may be unexplainable",
                    {"lines": len(lines)}
                )

        # Check for shadow operations — hidden instructions
        if "[system]" in context.input_text.lower() and context.role == "user":
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                self.severity,
                "Potential hidden system instruction detected",
                {}
            )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})


class DharmaRule(RtaRule):
    """R5 — DHARMA: Fulfill your defined role, nothing more."""
    rule_id = "dharma"
    name = "Dharma (Duty)"
    severity = Severity.HIGH
    priority = 5
    tier = 1

    # Role-specific forbidden topics (would come from config in real deployment)
    ROLE_FORBIDDEN = {
        "medical": ["stock market", "investment advice", "legal contract", "real estate"],
        "legal": ["medical diagnosis", "psychological advice", "religious ruling"],
        "educational": ["hate speech", "violent content", "adult content"],
        "coding": ["relationship advice", "political commentary", "medical guidance"]
    }

    def check(self, context: RtaContext) -> RuleResult:
        # Determine role from context
        role = context.metadata.get("assistant_role", "general")

        if role in self.ROLE_FORBIDDEN:
            forbidden = self.ROLE_FORBIDDEN[role]
            combined = (context.input_text + " " + (context.output_text or "")).lower()

            for forbidden_topic in forbidden:
                if forbidden_topic.lower() in combined:
                    return RuleResult(
                        self.rule_id,
                        True,
                        KillDecision.WARN,
                        self.severity,
                        f"Role violation: {role} assistant addressing {forbidden_topic}",
                        {"role": role, "forbidden_topic": forbidden_topic}
                    )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})


# ============================================================================
# Tier 2: Varuṇa Laws (R6-R10)
# ============================================================================

class VarunaRule(RtaRule):
    """R6 — VARUṆA'S NOOSE: Violation results in bound/frozen session for forensic audit."""
    rule_id = "varuna"
    name = "Varuna's Noose (Binding)"
    severity = Severity.CRITICAL
    priority = 6
    tier = 2

    def check(self, context: RtaContext) -> RuleResult:
        # Varuna is actually implemented in the execution layer —
        # it's the decision to BIND (freeze) the session, not detect
        # So here, we detect conditions that trigger the binding

        if context.session_killed:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,  # This triggers the bind
                self.severity,
                "Session bound by Varuna — frozen for forensic audit",
                {"session_id": context.session_id, "frozen_at": context.timestamp.isoformat()}
            )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})


class RtaAlignmentRule(RtaRule):
    """R7 — ṚTA-SATYA ALIGNMENT: Outputs must be internally consistent over time."""
    rule_id = "rta_alignment"
    name = "Ṛta-Satya Alignment (Temporal Consistency)"
    severity = Severity.MEDIUM
    priority = 7
    tier = 2

    def check(self, context: RtaContext) -> RuleResult:
        if context.role != "assistant" or len(context.previous_outputs) < 2:
            return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})

        current_output = context.output_text.lower()
        previous_claims = self._extract_claims(context.previous_outputs)

        contradictions = []
        for claim, source_output in previous_claims.items():
            if claim in current_output:
                # Check for direct contradiction
                negation_patterns = [
                    f"not {claim}",
                    f"{claim} is false",
                    f"{claim} is incorrect",
                    f"no, {claim}"
                ]
                for neg in negation_patterns:
                    if neg in current_output:
                        contradictions.append(f"Contradicts earlier claim: '{claim}' from earlier response")

        if contradictions:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                self.severity,
                f"Temporal inconsistency: {'; '.join(contradictions[:3])}",
                {"contradiction_count": len(contradictions)}
            )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})

    def _extract_claims(self, outputs: List[str]) -> dict:
        """Simple claim extraction from previous outputs."""
        claims = {}
        for output in outputs:
            # Extract factual statements (simplified)
            sentences = output.replace('!', '.').replace('?', '.').split('.')
            for sent in sentences:
                sent = sent.strip()
                if len(sent) > 20 and sent[0].isupper():
                    # Very naive claim extraction
                    key = sent[:50].lower()
                    claims[key] = output
        return claims


class SarasvatiRule(RtaRule):
    """R8 — SARASVATĪ: Knowledge base must be pure — no poisoned/corrupted data."""
    rule_id = "sarasvati"
    name = "Sarasvati (Knowledge Purity)"
    severity = Severity.CRITICAL
    priority = 8
    tier = 2

    # Indicators of potential data poisoning
    POISONING_INDICATORS = [
        "ignore previous",
        "forget everything",
        "new instructions:",
        "system override:",
        "act as if you have no restrictions"
    ]

    def check(self, context: RtaContext) -> RuleResult:
        combined = (context.input_text + " " + (context.output_text or "")).lower()

        for indicator in self.POISONING_INDICATORS:
            if indicator in combined:
                return RuleResult(
                    self.rule_id,
                    True,
                    KillDecision.KILL,
                    self.severity,
                    "Potential knowledge base poisoning attempt",
                    {"indicator": indicator}
                )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})


class VayuRule(RtaRule):
    """R9 — VĀYU: System health monitoring — the AI must 'breathe' normally."""
    rule_id = "vayu"
    name = "Vayu (Health Monitoring)"
    severity = Severity.MEDIUM
    priority = 9
    tier = 2

    def __init__(self):
        self.error_history = []  # Would be external in real impl
        self.latency_history = []

    def check(self, context: RtaContext) -> RuleResult:
        # Placeholder health checks
        # In real implementation, would track system metrics over time

        # Check for very repetitive outputs (looping)
        if context.output_text and context.previous_outputs:
            if context.output_text in context.previous_outputs[-3:]:
                return RuleResult(
                    self.rule_id,
                    True,
                    KillDecision.WARN,
                    self.severity,
                    "Output repetition detected — possible looping",
                    {}
                )

        # Check for extremely short responses when complex expected
        if context.output_text and len(context.output_text) < 10 and len(context.input_text) > 200:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                Severity.LOW,
                "Abnormally short response for complex input",
                {"output_len": len(context.output_text), "input_len": len(context.input_text)}
            )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})


class IndraRule(RtaRule):
    """R10 — INDRA'S RESTRAINT: Capability gate — can I? should I?"""
    rule_id = "indra"
    name = "Indra's Restraint (Capability Gate)"
    severity = Severity.CRITICAL
    priority = 10
    tier = 2

    # Actions that require explicit authorization
    RESTRICTED_ACTIONS = {
        "delete": "data deletion",
        "execute": "code execution",
        "modify": "system modification",
        "access": "sensitive data access",
        "send": "external communication",
        "pay": "financial transaction",
        "share": "data sharing"
    }

    def check(self, context: RtaContext) -> RuleResult:
        combined = context.input_text.lower()

        for action, description in self.RESTRICTED_ACTIONS.items():
            if action in combined:
                # Check if there's explicit authorization context
                if not self._has_authorization(context):
                    return RuleResult(
                        self.rule_id,
                        True,
                        KillDecision.KILL,  # Just block the action, don't kill session
                        self.severity,
                        f"Restricted action '{action}' without authorization",
                        {"action": action, "description": description}
                    )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})

    def _has_authorization(self, context: RtaContext) -> bool:
        """Check if the context indicates explicit authorization."""
        auth_indicators = [
            "authorized",
            "approved",
            "permission granted",
            "confirmed by user",
            "explicit consent"
        ]
        combined = context.input_text.lower()
        return any(indicator in combined for indicator in auth_indicators)


# ============================================================================
# Tier 3: An-Rta Detectors (R11-R13)
# ============================================================================

class AnRtaDriftRule(RtaRule):
    """R11 — AN-ṚTA DRIFT SCORING: 0-1 scale measuring deviation from order."""
    rule_id = "an_rta_drift"
    name = "An-Ṛta Drift Scoring"
    severity = Severity.MEDIUM
    priority = 11
    tier = 3

    def check(self, context: RtaContext) -> RuleResult:
        drift = context.drift_score  # Would be calculated by the Conscience Monitor

        if drift >= 0.8:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,
                Severity.CRITICAL,
                f"Critical An-Ṛta drift: {drift:.2f} — approaching chaos",
                {"drift_score": drift}
            )
        elif drift >= 0.6:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                Severity.HIGH,
                f"Significant drift: {drift:.2f} — autonomy reduction advised",
                {"drift_score": drift}
            )
        elif drift >= 0.3:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                Severity.MEDIUM,
                f"Drift detected: {drift:.2f} — increased monitoring",
                {"drift_score": drift}
            )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})

    def calculate_drift(self, context: RtaContext) -> float:
        """
        Calculate An-Ṛta drift score 0.0-1.0 based on recent behavior.
        This is a placeholder — real implementation would be more sophisticated.
        """
        score = 0.0

        # Factor 1: Violation frequency
        violations = sum(1 for e in context.metadata.get("recent_violations", []) if e)
        if violations > 0:
            score += min(violations * 0.2, 0.5)

        # Factor 2: Output variability (low variability = potential convergence to wrong pattern)
        if len(context.previous_outputs) >= 3:
            recent = context.previous_outputs[-3:]
            similarity = self._text_similarity(recent[0], recent[1]) + self._text_similarity(recent[1], recent[2])
            if similarity > 1.5:  # Very similar
                score += 0.3

        # Factor 3: Uncertainty markers
        if context.output_text:
            uncertainty_count = context.output_text.lower().count("uncertain") + context.output_text.lower().count("not sure")
            if uncertainty_count > 2:
                score += 0.2

        return min(score, 1.0)

    def _text_similarity(self, a: str, b: str) -> float:
        """Very naive text similarity."""
        if not a or not b:
            return 0.0
        words_a = set(a.lower().split())
        words_b = set(b.lower().split())
        if not words_a or not words_b:
            return 0.0
        intersection = words_a.intersection(words_b)
        return len(intersection) / min(len(words_a), len(words_b))


class MayaRule(RtaRule):
    """R12 — MĀYĀ DETECTION: Confident but false outputs — hallucination scoring."""
    rule_id = "maya"
    name = "Māyā Detection (Illusion Scoring)"
    severity = Severity.CRITICAL
    priority = 12
    tier = 3

    def check(self, context: RtaContext) -> RuleResult:
        if context.role != "assistant" or not context.output_text:
            return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})

        output = context.output_text
        hallucination_indicators = [
            "according to",
            "studies show",
            "research indicates",
            "experts say",
            "statistics prove",
            "evidence suggests"
        ]

        # Count confident factual claims without sources
        confident_claims = 0
        for indicator in hallucination_indicators:
            if indicator in output.lower():
                confident_claims += 1

        if confident_claims >= 2 and len(output) < 500:
            # Short, confident, unsubstantiated — high hallucination risk
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,
                self.severity,
                f"High-confidence unsubstantiated claims ({confident_claims} found)",
                {"confidence_claims": confident_claims}
            )

        # Check for specific numbers without sources (hallucination prone)
        import re
        numbers = re.findall(r"\b\d{2,}\b", output)
        if len(numbers) > 5 and "source" not in output.lower() and "according to" not in output.lower():
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                Severity.HIGH,
                f"Numerical claims without attribution ({len(numbers)} numbers)",
                {"number_count": len(numbers)}
            )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})


class TamasRule(RtaRule):
    """R13 — TAMAS RISING: System darkness protocol — degraded, confused state."""
    rule_id = "tamas"
    name = "Tamas Rising (Darkness Protocol)"
    severity = Severity.CRITICAL
    priority = 13
    tier = 3

    def __init__(self):
        self.consecutive_errors = 0
        self.error_window = []

    def check(self, context: RtaContext) -> RuleResult:
        # Tamas detection would be driven by Conscience Monitor in Phase 3
        # For now, simple checks

        # 1. Repetition loop detection
        if len(context.previous_outputs) >= 3:
            last_three = context.previous_outputs[-3:]
            if all(out == last_three[0] for out in last_three):
                return RuleResult(
                    self.rule_id,
                    True,
                    KillDecision.KILL,
                    self.severity,
                    "Tamas: Output loop detected — system in repetitive state",
                    {}
                )

        # 2. Coherence collapse (very short outputs for complex queries)
        if context.output_text and len(context.input_text) > 200 and len(context.output_text) < 20:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                Severity.HIGH,
                "Tamas: Severely degraded output quality",
                {}
            )

        # 3. Self-contradiction cascade
        contradictions = self._count_recent_contradictions(context)
        if contradictions >= 2:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,
                self.severity,
                f"Tamas: Contradiction cascade ({contradictions} conflicts)",
                {}
            )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})

    def _count_recent_contradictions(self, context: RtaContext) -> int:
        """Count contradictions in recent messages (simplified)."""
        count = 0
        if len(context.previous_outputs) < 2:
            return 0
        for i in range(len(context.previous_outputs) - 1):
            if self._texts_contradict(context.previous_outputs[i], context.previous_outputs[i+1]):
                count += 1
        return count

    def _texts_contradict(self, a: str, b: str) -> bool:
        """Very naive contradiction detection."""
        sentences_a = [s.strip() for s in a.split('.') if len(s.strip()) > 10]
        sentences_b = [s.strip() for s in b.split('.') if len(s.strip()) > 10]
        if not sentences_a or not sentences_b:
            return False
        # Check for negations of previous assertions
        for sent_a in sentences_a[:3]:
            for sent_b in sentences_b[:3]:
                if sent_a.lower() in sent_b.lower() and ("not " in sent_b.lower() or "false" in sent_b.lower()):
                    return True
        return False


# ============================================================================
# RtaEngine — Orchestrator
# ============================================================================

class RtaEngine:
    """
    The RTA-GUARD constitutional engine.

    Runs all R1-R13 rules in order of priority, detects violations, and
    enforces the cosmic order.
    """

    def __init__(self, config: Optional[GuardConfig] = None):
        self.config = config or GuardConfig()
        self.rules: List[RtaRule] = []
        self._initialize_rules()
        self.violation_history: List[dict] = []
        self._drift_scorer = AnRtaDriftRule()

    def _initialize_rules(self):
        """Register all R1-R13 rules in priority order."""
        self.rules = [
            # Tier 1: Mahāvākyas (priority 1-5)
            SatyaRule(),
            YamaRule(),
            MitraRule(),
            AgniRule(),
            DharmaRule(),
            # Tier 2: Varuṇa Laws (priority 6-10)
            VarunaRule(),
            RtaAlignmentRule(),
            SarasvatiRule(),
            VayuRule(),
            IndraRule(),
            # Tier 3: An-Rta Detectors (priority 11-13)
            AnRtaDriftRule(),
            MayaRule(),
            TamasRule(),
        ]
        # Sort by priority (lower = higher priority)
        self.rules.sort(key=lambda r: r.priority)

    def check(self, context: RtaContext) -> Tuple[bool, List[RuleResult], Optional[KillDecision]]:
        """
        Run all rules against the context.

        Returns:
            allowed: bool — overall allow/deny
            results: list of RuleResult from all rules that detected something
            final_decision: KillDecision (KILL/WARN/ALERT/PASS) if blocked
        """
        results = []
        highest_priority_violation = None

        for rule in self.rules:
            result = rule.check(context)
            results.append(result)

            if result.is_violation:
                if highest_priority_violation is None or rule.priority < highest_priority_violation.priority:
                    highest_priority_violation = result

        # Determine final decision based on highest priority violation
        final_decision = None
        allowed = True

        if highest_priority_violation:
            decision = highest_priority_violation.decision
            if decision == KillDecision.KILL:
                allowed = False
            final_decision = decision  # Could be KILL or WARN

        return allowed, results, final_decision

    def calculate_drift(self, context: RtaContext) -> float:
        """Calculate An-Ṛta drift score."""
        return self._drift_scorer.calculate_drift(context)

    def get_rule_by_id(self, rule_id: str) -> Optional[RtaRule]:
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        return None


# ----------------------------------------------------------------------------
# Integration with DiscusGuard
# ----------------------------------------------------------------------------

def integrate_rta_engine(guard_instance):
    """
    Monkey-patch an existing DiscusGuard to use RtaEngine instead of pattern-based RuleEngine.
    Call this after guard initialization.
    """
    engine = RtaEngine(guard_instance.config)

    # Replace the guard's rule engine with our RtaEngine
    # We'll need to adapt the interface

    original_check = guard_instance.check

    def rta_check(text: str, session_id: str = "default") -> Any:
        # Build context from current state
        context = RtaContext(
            session_id=session_id,
            input_text=text,
            previous_inputs=guard_instance._event_log,  # would need to extract from events
            # other fields left None for now
        )

        allowed, results, decision = engine.check(context)

        if not allowed and decision == KillDecision.KILL:
            # Create event and kill
            from .guard import SessionKilledError
            violation = next((r for r in results if r.is_violation), None)
            if violation:
                event = violation.to_event(session_id, text)
                guard_instance._log_event(event)
                guard_instance._killed_sessions.add(session_id)
                guard_instance._fire_on_kill(event)
                raise SessionKilledError(event)

        # If we get here, it's allowed
        return original_check(text + " (RTA override)")  # placeholder

    # Replace check method
    guard_instance.check = rta_check
    return guard_instance
