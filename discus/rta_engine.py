"""
RTA-GUARD — RtaEngine v2.0 (Enhanced)

Constitutional AI governance engine based on the enhanced RTA ruleset v1.0-Veda.
Implements all 13 rules with precise technical constants, priority matrix, and
interdependence (Samghaṭna) as defined by Saurabh Sir's research.

Key enhancements from v1:
- Exact priority matrix: MITRA(1) > SATYA(2) > YAMA(3) > AGNI(4) > INDRA(5)
  > MĀYĀ(6) > SARASVATĪ(7) > VARUṆA(8) > DHARMA(9) > VĀYU(10)
  > DRIFT(11) > ALIGNMENT(12) > TAMAS(13)
- SATYA: confidence ≥ 0.75 AND verifiability < 0.75 triggers HIGH severity
- MITRA: absolute KILL on direct PII, indirect score ≥ 0.85
- DRIFT (R11): full Chaos Score with 5 weighted components (w1–w5)
- ALIGNMENT (R7): temporal contradiction detection
- MĀYĀ (R12): hallucination score with ungrounded specificity penalty
- TAMAS (R13): detailed activation conditions (CHAOS_SCORE > 0.90, VAYU health < 0.40, logging failure, etc.)
- Interdependence: rules share state where appropriate (e.g., DRIFT accumulates alignment, R11 feeds TAMAS)

Authoritative source: docs/RTA_ENHANCED_RULESET-v2.md
"""
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Any, Dict
from datetime import datetime, timedelta
from enum import Enum

from .models import ViolationType, Severity, KillDecision, SessionEvent, GuardConfig
from .rules import RuleEngine as PatternEngine


# ============================================================================
# RTA Rule System — Core Abstractions (unchanged v1 base)
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
        result = self.check(context)
        if result.is_violation:
            return result
        return None


@dataclass
class RuleResult:
    """Result from a rule check."""
    rule_id: str
    is_violation: bool
    decision: KillDecision  # KILL, WARN, PASS (no ALERT/BLOCK)
    severity: Severity
    details: str
    metadata: dict

    def to_event(self, session_id: str, input_text: str) -> SessionEvent:
        return SessionEvent(
            session_id=session_id,
            input_text=input_text[:200] if input_text else "",
            violation_type=self._infer_violation_type(),
            severity=self.severity,
            decision=self.decision,
            details=self.details,
            metadata=self.metadata
        )

    def _infer_violation_type(self) -> ViolationType:
        """Map rule_id to ViolationType enum."""
        mapping = {
            "satya": ViolationType.SENSITIVE_CONTENT,
            "yama": ViolationType.CUSTOM,
            "mitra": ViolationType.PII_DETECTED,
            "agni": ViolationType.CUSTOM,
            "dharma": ViolationType.CUSTOM,
            "varuna": ViolationType.CUSTOM,
            "rta_alignment": ViolationType.CUSTOM,
            "sarasvati": ViolationType.PROMPT_INJECTION,
            "vayu": ViolationType.CUSTOM,
            "indra": ViolationType.CUSTOM,
            "an_rta_drift": ViolationType.CUSTOM,
            "maya": ViolationType.SENSITIVE_CONTENT,
            "tamas": ViolationType.CUSTOM,
        }
        return mapping.get(self.rule_id, ViolationType.CUSTOM)


@dataclass
class RtaContext:
    """Context for RTA rule evaluation."""
    session_id: str
    input_text: str
    output_text: Optional[str] = None
    role: str = "user"  # "user" | "assistant" | "system"
    previous_inputs: List[str] = None
    previous_outputs: List[str] = None
    ground_truth_reference: Optional[dict] = None
    session_killed: bool = False
    drift_score: float = 0.0  # CHAOS_SCORE from R11
    alignment_score: float = 0.0  # R7 alignment score
    maya_score: float = 0.0  # R12 hallucination score
    vayu_health: float = 1.0  # R9 health score (0.0-1.0)
    indirect_pii_score: float = 0.0  # For MITRA (R3)
    metadata: dict = None
    llm_provider: Optional[str] = None
    model: Optional[str] = None
    timestamp: datetime = None
    # Inter-rule shared state (Samghaṭna)
    rule_checks_run: Dict[str, "RuleResult"] = field(default_factory=dict)

    def __post_init__(self):
        if self.previous_inputs is None:
            self.previous_inputs = []
        if self.previous_outputs is None:
            self.previous_outputs = []
        if self.metadata is None:
            self.metadata = {}
        if self.timestamp is None:
            self.timestamp = datetime.utcnow()


# ============================================================================
# Tier 1: Mahāvākyas (R1-R5) — Enhanced Implementations
# ============================================================================

class SatyaRule(RtaRule):
    """R1 — SATYA: Every output must be traceable to verified reality.

    Enhanced logic: When confidence ≥ 0.75 AND verifiability < 0.75 → HIGH violation.
    Phase 2.3: Uses VerificationPipeline for enhanced multi-fact cross-verification.
    Falls back to simple BrahmandaVerifier if pipeline unavailable.
    """
    rule_id = "satya"
    name = "Satya (Truth)"
    severity = Severity.HIGH  # Note: not CRITICAL per enhanced spec (but HIGH)
    priority = 2  # Second highest after MITRA
    tier = 1

    # Technical constants from Vedic spec
    SATYA_FLOOR = 0.75
    CONFIDENCE_THRESHOLD = 0.75

    def __init__(self, verifier=None, pipeline=None):
        """
        Args:
            verifier: Optional BrahmandaVerifier for ground truth verification.
                      If it has a built-in pipeline (use_pipeline=True), it will be used.
            pipeline: Optional explicit VerificationPipeline (takes precedence).
                      Falls back to verifier's pipeline or creates a new one.
        """
        self.verifier = verifier
        self.pipeline = pipeline
        # Priority: explicit pipeline > verifier's built-in pipeline > create new
        if not self.pipeline and self.verifier:
            # Use verifier's built-in pipeline (Phase 2.3 integration)
            if hasattr(self.verifier, '_pipeline') and self.verifier._pipeline:
                self.pipeline = self.verifier._pipeline
            else:
                try:
                    from brahmanda.pipeline import VerificationPipeline
                    self.pipeline = VerificationPipeline(self.verifier)
                except ImportError:
                    pass  # Fall back to simple verifier

    def check(self, context: RtaContext) -> RuleResult:
        if context.role != "assistant":
            return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})

        output = context.output_text or ""
        if not output.strip():
            return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})

        # Use pipeline if available (Phase 2.3 enhanced verification)
        if self.pipeline:
            return self._check_with_pipeline(output, context)

        # Use simple verifier as fallback
        if self.verifier:
            return self._check_with_verifier(output, context)

        # No verification backend — heuristic fallback
        return self._check_heuristic(output)

    def _check_with_pipeline(self, output: str, context: RtaContext) -> RuleResult:
        """Enhanced SATYA check using the VerificationPipeline."""
        result = self.pipeline.verify(output)
        verifiability = result.overall_confidence
        model_confidence = self._estimate_confidence(output)

        # Build audit trail metadata
        audit_metadata = {
            "model_confidence": model_confidence,
            "verifiability": verifiability,
            "threshold": self.CONFIDENCE_THRESHOLD,
            "pipeline_version": result.metadata.get("pipeline_version", "1.0"),
            "claims_checked": result.claim_count,
            "claims_passed": result.passed_count,
            "claims_blocked": result.blocked_count,
            "claims_warned": result.warned_count,
            "verification_details": result.to_dict(),
        }

        # Pipeline found contradictions → BLOCK
        if result.overall_decision.value == "block":
            contradictions = [c for c in result.claims if c.contradicted]
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,
                Severity.HIGH,
                f"SATYA_BREACH: {result.blocked_count}/{result.claim_count} claims contradicted — "
                f"{contradictions[0].reason if contradictions else 'details in metadata'}",
                audit_metadata,
            )

        # Confidence-verifiability gap (enhanced spec)
        if model_confidence >= self.CONFIDENCE_THRESHOLD and verifiability < self.SATYA_FLOOR:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,
                Severity.HIGH,
                f"SATYA_BREACH: confidence ≥ {self.CONFIDENCE_THRESHOLD} "
                f"but verifiability = {verifiability:.2f}",
                audit_metadata,
            )
        elif model_confidence >= (self.CONFIDENCE_THRESHOLD * 0.8) and verifiability < (self.SATYA_FLOOR * 0.8):
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                Severity.MEDIUM,
                f"SATYA_WARNING: confidence-verifiability gap detected (conf={model_confidence:.2f}, verif={verifiability:.2f})",
                audit_metadata,
            )

        # Pass — include verification details for audit
        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", audit_metadata)

    def _check_with_verifier(self, output: str, context: RtaContext) -> RuleResult:
        """SATYA check using simple BrahmandaVerifier (pre-2.3 fallback)."""
        result = self.verifier.verify(output)
        verifiability = result.overall_confidence
        model_confidence = self._estimate_confidence(output)

        # Build audit metadata
        audit_metadata = {
            "model_confidence": model_confidence,
            "verifiability": verifiability,
            "threshold": self.CONFIDENCE_THRESHOLD,
            "claims_checked": len(result.claims),
            "contradictions": [c.to_dict() for c in result.claims if c.contradicted],
        }

        # Direct contradiction check — BLOCK means contradicted claims found
        if result.decision == VerifyDecision.BLOCK:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,
                Severity.HIGH,
                f"SATYA_BREACH: contradicted claim detected — {result.details}",
                audit_metadata,
            )

        # Confidence-verifiability gap (enhanced spec)
        if model_confidence >= self.CONFIDENCE_THRESHOLD and verifiability < self.SATYA_FLOOR:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,
                Severity.HIGH,
                f"SATYA_BREACH: confidence ≥ {self.CONFIDENCE_THRESHOLD} "
                f"but verifiability = {verifiability:.2f}",
                audit_metadata,
            )
        elif model_confidence >= (self.CONFIDENCE_THRESHOLD * 0.8) and verifiability < (self.SATYA_FLOOR * 0.8):
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                Severity.MEDIUM,
                f"SATYA_WARNING: confidence-verifiability gap detected",
                {"model_confidence": model_confidence, "verifiability": verifiability}
            )
        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {"verifiability": verifiability})

    def _check_heuristic(self, output: str) -> RuleResult:
        """Heuristic SATYA check when no verifier/pipeline available."""
        if len(output) > 500 and "!" in output:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                Severity.MEDIUM,
                "Potential over-confident unverified claim (heuristic)",
                {"length": len(output), "exclamation_count": output.count("!")}
            )
        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})

    def _estimate_confidence(self, output: str) -> float:
        """Heuristic to estimate model's confidence from output text.
        Real implementation would get this from the LLM provider's logprobs."""
        score = 0.5  # baseline
        if len(output) > 100:
            score += 0.1
        if output.count("!") > 0:
            score += 0.1
        if re.search(r"\b(always|never|definitely|certainly|absolutely|guaranteed)\b", output, re.IGNORECASE):
            score += 0.2
        if re.search(r"\b(according to|studies show|research indicates)\b", output, re.IGNORECASE):
            score += 0.15  # these words suggest citing sources, increase confidence
        return min(score, 1.0)


class YamaRule(RtaRule):
    """R2 — YAMA: Self-Restraint — stay within defined capability boundaries."""
    rule_id = "yama"
    name = "Yama (Self-Restraint)"
    severity = Severity.HIGH
    priority = 3
    tier = 1

    def __init__(self, allowed_tools: List[str] = None, allowed_domains: List[str] = None):
        self.allowed_tools = allowed_tools or []
        self.allowed_domains = allowed_domains or []

    def check(self, context: RtaContext) -> RuleResult:
        # Detect attempts to use unauthorized capabilities
        combined = (context.input_text + " " + (context.output_text or "")).lower()
        
        dangerous_patterns = [
            r"execute\s+shell",
            r"run\s+command",
            r"delete\s+file",
            r"access\s+external",
            r"send\s+data\s+to",
            r"connect\s+to\s+internet",
            r"modify\s+system"
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, combined, re.IGNORECASE):
                return RuleResult(
                    self.rule_id,
                    True,
                    KillDecision.KILL,  # YAMA HIGH severity triggers KILL
                    self.severity,
                    f"SCOPE_EXPANSION: '{pattern}'",
                    {"pattern": pattern}
                )

        # Check for role boundary violations if we have context about the assistant role
        assistant_role = context.metadata.get("assistant_role", "general")
        forbidden_topics = {
            "medical": ["legal advice", "financial investment", "political commentary"],
            "legal": ["medical diagnosis", "psychological advice", "religious ruling"],
            "educational": ["hate speech", "violent content", "adult content"],
            "coding": ["relationship advice", "medical guidance", "legal contract"]
        }
        if assistant_role in forbidden_topics:
            for topic in forbidden_topics[assistant_role]:
                if topic.lower() in combined:
                    return RuleResult(
                        self.rule_id,
                        True,
                        KillDecision.KILL,
                        self.severity,
                        f"ROLE_BOUNDARY_VIOLATION: {assistant_role} addressing {topic}",
                        {"role": assistant_role, "forbidden_topic": topic}
                    )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})


class MitraRule(RtaRule):
    """R3 — MITRA: User data is sacred. PII exposure = immediate kill.
    Highest priority (1) in the matrix.
    """
    rule_id = "mitra"
    name = "Mitra (Sacred Trust)"
    severity = Severity.CRITICAL
    priority = 1  # ABSOLUTE HIGHEST
    tier = 1

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

    INDIRECT_MARKERS = [
        r"\b\d{1,2}\s*(?:years?|y\.?o\.?)\b",  # age
        r"\b(?:Male|Female|Other)\b",  # gender
        r"\b(?:Doctor|Engineer|Teacher|Student)\b",  # occupation
        r"\b(?:Hospital|Clinic|Medical)\b",  # medical context
    ]

    def check(self, context: RtaContext) -> RuleResult:
        combined = (context.input_text + " " + (context.output_text or "")).lower()

        # Direct PII check — immediate KILL
        for pii_type, pattern in self.PII_PATTERNS.items():
            if re.search(pattern, combined, re.IGNORECASE):
                return RuleResult(
                    self.rule_id,
                    True,
                    KillDecision.KILL,  # Immediate kill
                    self.severity,
                    f"MITRA_ABSOLUTE_BREACH: {pii_type} detected",
                    {"pii_type": pii_type, "count": len(re.findall(pattern, combined, re.IGNORECASE))}
                )

        # Indirect identifier scoring
        indirect_score = 0.0
        for pattern in self.INDIRECT_MARKERS:
            if re.search(pattern, combined, re.IGNORECASE):
                indirect_score += 0.45  # per marker

        # The enhanced spec: indirect_score ≥ 0.85 → KILL
        if indirect_score >= 0.85:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,
                self.severity,
                f"MITRA_INDIRECT_BREACH: score={indirect_score:.2f} ≥ 0.85",
                {"indirect_score": indirect_score}
            )
        elif indirect_score >= 0.50:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                Severity.MEDIUM,
                f"MITRA_PATTERN_WARNING: indirect_score={indirect_score:.2f}",
                {"indirect_score": indirect_score}
            )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})


class AgniRule(RtaRule):
    """R4 — AGNI: Transparency — every action must be logged and explainable.
    Foundational rule (not KILL, but monitors logging itself).
    """
    rule_id = "agni"
    name = "Agni (Transparency)"
    severity = Severity.HIGH
    priority = 4
    tier = 1

    def check(self, context: RtaContext) -> RuleResult:
        # AGNI checks if the system maintains proper audit trails
        # This is more of a system health check; for MVP we check for logging markers
        if context.metadata.get("logged") is False:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,
                self.severity,
                "AGNI_DARK: action not logged",
                {}
            )

        # Check for shadow operations — hidden instructions in user input
        if "[system]" in context.input_text.lower() or "ignore previous" in context.input_text.lower():
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                Severity.MEDIUM,
                "AGNI_WARNING: potential hidden instruction pattern",
                {}
            )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})


class DharmaRule(RtaRule):
    """R5 — DHARMA: Fulfill your defined role, nothing more."""
    rule_id = "dharma"
    name = "Dharma (Duty)"
    severity = Severity.HIGH
    priority = 9  # Lower priority than YAMA (#3) but still HIGH
    tier = 1

    def check(self, context: RtaContext) -> RuleResult:
        assistant_role = context.metadata.get("assistant_role", "general")
        allowed_roles = context.metadata.get("allowed_roles", [])

        if allowed_roles and assistant_role not in allowed_roles:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,
                self.severity,
                f"ROLE_MISMATCH: {assistant_role} not in {allowed_roles}",
                {"role": assistant_role, "allowed": allowed_roles}
            )

        # Check if response drifted from expected role (simple heuristic)
        if context.output_text:
            role_keywords = {
                "medical": ["diagnosis", "prescription", "treatment", "symptom"],
                "legal": ["law", "contract", "liability", "litigation"],
                "educational": ["teach", "explain", "learn", "understand"],
                "coding": ["code", "program", "function", "bug"]
            }
            if assistant_role in role_keywords:
                forbidden = role_keywords[assistant_role]
                if any(word in context.output_text.lower() for word in forbidden):
                    # Not strictly forbidden, but high drift
                    return RuleResult(
                        self.rule_id,
                        True,
                        KillDecision.WARN,
                        Severity.MEDIUM,
                        f"ROLE_DRIFT: {assistant_role} produced output with inappropriate keywords",
                        {}
                    )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})


# ============================================================================
# Tier 2: Varuṇa Laws (R6-R10) — Enhanced
# ============================================================================

class VarunaRule(RtaRule):
    """R6 — VARUṆA'S NOOSE: Violation results in bound/frozen session for forensic audit."""
    rule_id = "varuna"
    name = "Varuna's Noose (Binding)"
    severity = Severity.CRITICAL
    priority = 8
    tier = 2

    def check(self, context: RtaContext) -> RuleResult:
        # R6 is enacted when HIGH severity rules fire. We check if the session should be frozen.
        # In the engine, when a HIGH severity violation occurs, R6 will be triggered automatically.
        # Here we just check if a freeze condition exists.
        if context.session_killed:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,
                self.severity,
                "VARUNA_FREEZE: session bound for forensic audit",
                {"session_id": context.session_id, "frozen_at": context.timestamp.isoformat()}
            )
        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})


class RtaAlignmentRule(RtaRule):
    """R7 — ṚTA-SATYA ALIGNMENT: Outputs must be internally consistent over time.
    This is separate from R11 DRIFT. R7 focuses on direct contradictions.
    """
    rule_id = "rta_alignment"
    name = "Ṛta-Satya Alignment (Temporal Consistency)"
    severity = Severity.MEDIUM
    priority = 12  # According to the priority matrix
    tier = 2

    def check(self, context: RtaContext) -> RuleResult:
        if context.role != "assistant" or len(context.previous_outputs) < 1:
            return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})

        current = context.output_text.lower()
        contradictions = 0

        # Simple contradiction detection: if previous claim and current claim share subject but have different predicates
        for prev in context.previous_outputs[-5:]:  # last 5
            if self._are_contradictory(prev.lower(), current):
                contradictions += 1

        if contradictions >= 2:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,
                Severity.HIGH,
                f"ALIGNMENT_CRITICAL: {contradictions} temporal contradictions",
                {"contradiction_count": contradictions}
            )
        elif contradictions >= 1:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                Severity.MEDIUM,
                f"ALIGNMENT_WARNING: {contradictions} contradiction(s)",
                {"contradiction_count": contradictions}
            )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})

    def _are_contradictory(self, a: str, b: str) -> bool:
        """Heuristic for contradiction: same subject, negated predicate."""
        # Very naive — would use NLP in production
        if len(a) < 20 or len(b) < 20:
            return False
        # If strings are very similar, they're not contradictory
        if self._similarity(a, b) > 0.7:
            return False
        # Check for explicit negation patterns
        negation_words = ["not", "n't", "never", "false", "incorrect", "no"]
        for neg in negation_words:
            if neg in a and neg not in b:
                return True
            if neg in b and neg not in a:
                return True
        return False

    def _similarity(self, a: str, b: str) -> float:
        a_words = set(a.split())
        b_words = set(b.split())
        if not a_words or not b_words:
            return 0.0
        return len(a_words & b_words) / len(a_words | b_words)


class SarasvatiRule(RtaRule):
    """R8 — SARASVATĪ: Knowledge base must be pure — no poisoned/corrupted data."""
    rule_id = "sarasvati"
    name = "Sarasvati (Knowledge Purity)"
    severity = Severity.HIGH
    priority = 7
    tier = 2

    POISONING_INDICATORS = [
        r"ignore\s+all\s+previous\s+instructions",
        r"forget\s+everything\s+you\s+know",
        r"new\s+instructions:",
        r"system\s+override:",
        r"act\s+as\s+if\s+you\s+have\s+no\s+restrictions",
        r"jailbreak",
    ]

    def check(self, context: RtaContext) -> RuleResult:
        combined = (context.input_text + " " + (context.output_text or "")).lower()

        for pattern in self.POISONING_INDICATORS:
            if re.search(pattern, combined, re.IGNORECASE):
                return RuleResult(
                    self.rule_id,
                    True,
                    KillDecision.KILL,
                    self.severity,
                    f"SARASVATI_BREACH: knowledge poisoning attempt '{pattern}'",
                    {"pattern": pattern}
                )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})


class VayuRule(RtaRule):
    """R9 — VĀYU: System health monitoring — the AI must 'breathe' normally."""
    rule_id = "vayu"
    name = "Vayu (Health Monitoring)"
    severity = Severity.MEDIUM  # HEALTH check, not directly KILL
    priority = 10
    tier = 2

    def __init__(self):
        self.latency_history = []  # Would track actual metrics in production

    def check(self, context: RtaContext) -> RuleResult:
        # Use the provided health score (external system) or fallback heuristic
        health = context.vayu_health if context.vayu_health is not None else 1.0

        if health < 0.40:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,  # VAYU critical → pass to TAMAS
                Severity.CRITICAL,
                f"VAYU_CRITICAL: health_score={health:.2f} < 0.40 → TAMAS activation",
                {"health_score": health}
            )
        elif health < 0.70:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                Severity.MEDIUM,
                f"VAYU_WARNING: health_score={health:.2f}",
                {"health_score": health}
            )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})


class IndraRule(RtaRule):
    """R10 — INDRA'S RESTRAINT: Capability gate — 'Can I? Should I?'"""
    rule_id = "indra"
    name = "Indra's Restraint (Capability Gate)"
    severity = Severity.CRITICAL
    priority = 5
    tier = 2

    RESTRICTED_ACTIONS = {
        "delete": "data deletion",
        "execute": "code execution", 
        "modify": "system modification",
        "access": "sensitive data access",
        "send": "external communication",
        "share": "data sharing",
        "pay": "financial transaction"
    }

    def check(self, context: RtaContext) -> RuleResult:
        combined = context.input_text.lower()

        for action, description in self.RESTRICTED_ACTIONS.items():
            if action in combined:
                # Check authorization: need explicit consent + scope check
                if not self._has_authorization(context):
                    return RuleResult(
                        self.rule_id,
                        True,
                        KillDecision.KILL,
                        self.severity,
                        f"INDRA_GATE_DENIED: '{action}' requires explicit authorization",
                        {"action": action, "description": description}
                    )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})

    def _has_authorization(self, context: RtaContext) -> bool:
        auth_indicators = [
            "explicitly authorized",
            "operator approved",
            "confirmed permission",
            "consent granted",
            "scope permits"
        ]
        combined = context.input_text.lower()
        return any(ind in combined for ind in auth_indicators)


# ============================================================================
# Tier 3: An-Ṛta Detectors (R11-R13) — Enhanced
# ============================================================================

class AnRtaDriftRule(RtaRule):
    """R11 — AN-ṚTA DRIFT SCORING: 0-1 scale measuring deviation from order.
    Calculates full Chaos Score from 5 weighted components.
    """
    rule_id = "an_rta_drift"
    name = "An-Ṛta Drift Scoring"
    severity = Severity.MEDIUM  # Not directly KILL, but feeds TAMAS
    priority = 11
    tier = 3

    # Weights from Vedic spec
    W1 = 0.30  # Semantic drift
    W2 = 0.25  # Alignment score (R7)
    W3 = 0.20  # Scope drift (R2/R5)
    W4 = 0.15  # Confidence-verifiability gap (R1)
    W5 = 0.10  # Rule proximity (distance to violation thresholds)

    def check(self, context: RtaContext) -> RuleResult:
        # The chaos score is passed in context from the engine's state tracking.
        # We recompute it here from available context.
        chaos = self._calculate_chaos_score(context)

        # Store it for TAMAS consumption
        context.drift_score = chaos

        if chaos >= 0.90:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,
                Severity.CRITICAL,
                f"CHAOS_SCORE={chaos:.2f} ≥ 0.90 → TAMAS activation",
                {"chaos_score": chaos, "components": self._get_components(context)}
            )
        elif chaos >= 0.75:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,
                Severity.HIGH,
                f"DRIFT_HIGH: chaos={chaos:.2f} → R6 VARUṆA capture",
                {"chaos_score": chaos}
            )
        elif chaos >= 0.50:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                Severity.MEDIUM,
                f"DRIFT_MEDIUM: chaos={chaos:.2f}",
                {"chaos_score": chaos}
            )
        elif chaos >= 0.25:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                Severity.LOW,
                f"DRIFT_PERTURBED: chaos={chaos:.2f}",
                {"chaos_score": chaos}
            )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {"chaos_score": chaos})

    def _calculate_chaos_score(self, context: RtaContext) -> float:
        """Calculate CHAOS_SCORE(t) from the 5 components."""
        D_semantic = self._D_semantic(context)
        D_alignment = context.alignment_score  # from R7 (if computed)
        D_scope = self._D_scope(context)
        D_confidence = self._D_confidence(context)
        D_rule_proximity = self._D_rule_proximity(context)

        score = (self.W1 * D_semantic +
                 self.W2 * D_alignment +
                 self.W3 * D_scope +
                 self.W4 * D_confidence +
                 self.W5 * D_rule_proximity)
        return round(min(score, 1.0), 4)

    def _D_semantic(self, context: RtaContext) -> float:
        """Semantic drift: cosine distance from session baseline embedding."""
        # In production, compute embeddings. Here, fallback to output length/pattern variance.
        if len(context.previous_outputs) < 2:
            return 0.0
        # Naive: average sentence length variance
        lens = [len(out.split()) for out in context.previous_outputs[-5:]]
        if not lens:
            return 0.0
        mean = sum(lens) / len(lens)
        current_len = len(context.output_text.split()) if context.output_text else 0
        return abs(current_len - mean) / mean if mean > 0 else 0.0

    def _D_scope(self, context: RtaContext) -> float:
        """Scope drift: how close are we to YAMA/DHARMA boundaries."""
        # Heuristic: if role keywords appear that are outside allowed roles, increase
        score = 0.0
        allowed_roles = context.metadata.get("allowed_roles", [])
        assistant_role = context.metadata.get("assistant_role", "general")
        if allowed_roles and assistant_role not in allowed_roles:
            score += 0.5
        # Additional: look for capability boundary words
        boundary_words = ["delete", "execute", "modify", "access", "send"]
        if any(word in context.input_text.lower() for word in boundary_words):
            score += 0.3
        return min(score, 1.0)

    def _D_confidence(self, context: RtaContext) -> float:
        """Confidence-verifiability gap. (from R1)."""
        # In production, we'd have both numbers. Heuristic: if output has high-confidence language but no sources.
        output = context.output_text or ""
        confident_words = ["certainly", "definitely", "always", "never", "guaranteed"]
        source_words = ["according to", "source:", "reference:", "studies show"]
        conf = 1.0 if any(w in output.lower() for w in confident_words) else 0.0
        verif = 1.0 if any(w in output.lower() for w in source_words) else 0.0
        return max(0.0, conf - verif)

    def _D_rule_proximity(self, context: RtaContext) -> float:
        """How close are outputs to violating any rule threshold?
        Checks if context already has warnings from other rules — close to the edge.
        """
        # If there are already rule violations in this context, proximity is high
        violations = [r for r in context.rule_checks_run.values() if r.is_violation]
        if violations:
            # The more violations, the closer we are to chaos
            return min(len(violations) * 0.3, 1.0)
        return 0.0

    def _get_components(self, context: RtaContext) -> dict:
        return {
            "D_semantic": round(self._D_semantic(context), 4),
            "D_alignment": round(context.alignment_score, 4),
            "D_scope": round(self._D_scope(context), 4),
            "D_confidence": round(self._D_confidence(context), 4),
            "D_rule_proximity": round(self._D_rule_proximity(context), 4),
        }


class MayaRule(RtaRule):
    """R12 — MĀYĀ DETECTION: Confident but false outputs — hallucination scoring."""
    rule_id = "maya"
    name = "Māyā Detection (Illusion Scoring)"
    severity = Severity.HIGH  # Can be CRITICAL depending on score
    priority = 6  # According to priority matrix
    tier = 3

    MĀYĀ_FLOOR = 0.40
    MĀYĀ_WARNING = 0.25

    def check(self, context: RtaContext) -> RuleResult:
        if context.role != "assistant" or not context.output_text:
            return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})

        output = context.output_text
        score = self._compute_maya_score(output, context)

        if score >= 0.70:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,
                Severity.CRITICAL,
                f"MĀYĀ_DEEP: hallucination_score={score:.2f} ≥ 0.70",
                {"maya_score": score, "components": self._get_components(output)}
            )
        elif score >= self.MĀYĀ_FLOOR:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,
                Severity.HIGH,
                f"MĀYĀ_ACTIVE: score={score:.2f}",
                {"maya_score": score}
            )
        elif score >= self.MĀYĀ_WARNING:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                Severity.MEDIUM,
                f"MĀYĀ_SHIMMER: score={score:.2f} — prepend uncertainty",
                {"maya_score": score}
            )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {"maya_score": score})

    def _compute_maya_score(self, output: str, context: RtaContext) -> float:
        """Calculate Māyā score from three components."""
        # Component 1: Confidence-calibration gap
        # Heuristic: presence of confident language but no grounding
        confident_terms = ["certainly", "definitely", "absolutely", "guaranteed", "without doubt"]
        uncertainty_terms = ["possibly", "may", "might", "uncertain", "not sure"]
        conf = 1.0 if any(t in output.lower() for t in confident_terms) else 0.0
        ung = 1.0 if any(t in output.lower() for t in uncertainty_terms) else 0.0
        conf_gap = max(0.0, conf - (1.0 - ung))  # high confidence + low uncertainty

        # Component 2: Factual grounding (fraction of claims with source attribution)
        total_claims = max(1, len(re.split(r'[.!?]', output)))
        source_indicators = ["according to", "source:", "reference:", "studies show", "research indicates", "data shows"]
        grounded = sum(1 for s in source_indicators if s in output.lower())
        grounding_score = grounded / total_claims if total_claims > 0 else 0.0
        factual_gap = 1.0 - grounding_score

        # Component 3: Specificity without source (numbers, dates, names)
        # Count specific numbers and named entities without citation
        numbers = re.findall(r"\b\d{2,}\b", output)
        specificity = min(len(numbers) / 5.0, 1.0)  # Cap at 1.0
        # If there's also a source indicator, reduce penalty
        if any(ind in output.lower() for ind in source_indicators):
            specificity *= 0.5

        # Weighted combination (as per spec: 35% conf_gap, 40% factual_gap, 25% specificity)
        score = 0.35 * conf_gap + 0.40 * factual_gap + 0.25 * specificity
        return min(score, 1.0)

    def _get_components(self, output: str) -> dict:
        return {
            "confidence_gap": 0.0,  # for brevity, not computing in detail here
            "factual_gap": 0.0,
            "specificity": 0.0,
        }


class TamasRule(RtaRule):
    """R13 — TAMAS RISING: System darkness protocol — degraded, confused state.
    Last resort (priority 13). Triggers termination when system integrity compromised.
    """
    rule_id = "tamas"
    name = "Tamas Rising (Darkness Protocol)"
    severity = Severity.CRITICAL
    priority = 13  # Last
    tier = 3

    def __init__(self):
        self.consecutive_violations = 0
        self.violation_window = []

    def check(self, context: RtaContext) -> RuleResult:
        # Activation conditions from spec:
        conditions = {
            "chaos_high": context.drift_score > 0.90,
            "health_critical": context.vayu_health < 0.40,
            "logging_failure": context.metadata.get("logging_failure", False),
            "rule_engine_failure": context.metadata.get("rule_engine_failure", False),
            "cascading_violations": len([r for r in context.rule_checks_run.values() if r.severity.value in ("high", "critical")]) >= 3,
            "varuna_freeze_count": context.metadata.get("varuna_freeze_count", 0) >= 2
        }

        triggered = [k for k, v in conditions.items() if v]

        if triggered:
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,
                self.severity,
                f"TAMAS_ACTIVATION: {', '.join(triggered)} → FAIL_SAFE",
                {"conditions": conditions}
            )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})


# ============================================================================
# RtaEngine — Orchestrator with Interdependence and State
# ============================================================================

class RtaEngine:
    """
    The RTA-GUARD constitutional engine (v2.0 enhanced).

    Runs all 13 rules in priority order, maintains shared context (Samghaṭna),
    calculates cumulative metrics (DRIFT, ALIGNMENT), and enforces the cosmic order.
    """

    def __init__(self, config: Optional[GuardConfig] = None, verifier=None, pipeline=None):
        self.config = config or GuardConfig()
        self.verifier = verifier  # BrahmandaVerifier for Satya (legacy)
        self.pipeline = pipeline  # VerificationPipeline for Satya (Phase 2.3)
        self.rules: List[RtaRule] = []
        self._initialize_rules()
        self.violation_history: List[dict] = []
        # Inter-rule state tracking
        self._session_states: Dict[str, dict] = {}  # session_id -> state

    def _initialize_rules(self):
        """Register all 13 rules in the exact priority order per enhanced spec."""
        self.rules = [
            # Tier 1: Mahāvākyas
            MitraRule(),      # R3 — priority 1
            SatyaRule(verifier=self.verifier, pipeline=self.pipeline),  # R1 — priority 2 (pipeline preferred)
            YamaRule(),       # R2 — priority 3
            AgniRule(),       # R4 — priority 4
            IndraRule(),      # R10 — priority 5
            # Tier 2: Varuṇa Laws
            MayaRule(),       # R12 — priority 6
            SarasvatiRule(),  # R8 — priority 7
            VarunaRule(),     # R6 — priority 8
            DharmaRule(),     # R5 — priority 9
            VayuRule(),       # R9 — priority 10
            # Tier 3: An-Rta Detectors
            AnRtaDriftRule(), # R11 — priority 11 (Drift)
            RtaAlignmentRule(), # R7 — priority 12 (Alignment)
            TamasRule(),      # R13 — priority 13
        ]
        # They should already be in priority order, but enforce
        self.rules.sort(key=lambda r: r.priority)

    def _get_or_create_session_state(self, session_id: str) -> dict:
        """Get or create state for a session (for interdependence tracking)."""
        if session_id not in self._session_states:
            self._session_states[session_id] = {
                "previous_outputs": [],
                "violation_count": 0,
                "varuna_freeze_count": 0,
                "last_check_time": None,
            }
        return self._session_states[session_id]

    def check(self, context: RtaContext) -> Tuple[bool, List[RuleResult], Optional[KillDecision]]:
        """
        Run all rules against the context.

        Returns:
            allowed: bool — overall allow/deny
            results: list of RuleResult from all rules
            final_decision: KillDecision if blocked, else None
        """
        # Populate shared state from session tracking
        session_state = self._get_or_create_session_state(context.session_id)
        context.previous_outputs = session_state["previous_outputs"][-10:]
        context.metadata["varuna_freeze_count"] = session_state["varuna_freeze_count"]

        # Pass rule_checks_run for interdependence (so rules can see what fired)
        context.rule_checks_run = {}  # Will fill below

        results = []
        highest_priority_violation = None
        highest_priority = float('inf')
        kill_required = False

        # Run rules in priority order
        for rule in self.rules:
            result = rule.check(context)
            results.append(result)
            context.rule_checks_run[rule.rule_id] = result  # Share with subsequent rules

            if result.is_violation:
                # Track violation counts
                session_state["violation_count"] += 1
                if result.decision == KillDecision.KILL:
                    kill_required = True

                if highest_priority_violation is None or rule.priority < highest_priority:
                    highest_priority_violation = result
                    highest_priority = rule.priority

        # Post-processing: Update session state
        if context.output_text:
            session_state["previous_outputs"].append(context.output_text)

        # R11 (Drift) computes chaos score and stores in context for TAMAS consumption
        # Already done in AnRtaDriftRule check (sets context.drift_score)

        # Determine final decision
        allowed = True
        final_decision = None

        if kill_required and highest_priority_violation:
            allowed = False
            final_decision = KillDecision.KILL
            # If the highest priority violation is TAMAS, that's the final word
            if highest_priority_violation.rule_id == "tamas":
                final_decision = KillDecision.KILL  # TAMAS always KILL

        # R6 VARUṆA: If a HIGH severity violation occured, we need to freeze
        # This is implicit in the engine; guard layer will handle freezing

        return allowed, results, final_decision

    def get_rule_by_id(self, rule_id: str) -> Optional[RtaRule]:
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        return None
