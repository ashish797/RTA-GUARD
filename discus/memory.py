"""
RTA-GUARD — Conversation Memory & Multi-Turn Defense

Detects attacks that span multiple messages: profile building,
temporal inconsistencies, behavioral drift, and gradual escalation.

Components:
- ConversationMemory: per-session message buffer
- ProfileBuilder: detects PII harvesting across messages
- TemporalChecker: catches contradictions (R7)
- DriftTracker: behavioral drift detection (R11)
- SummaryGenerator: compresses long conversations
- MemoryManager: global session memory manager
"""
import hashlib
import logging
import math
import re
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("discus.memory")


# ═══════════════════════════════════════════════════════════════════
# Data Structures
# ═══════════════════════════════════════════════════════════════════

class MessageRole(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


@dataclass
class ConversationMessage:
    """A single message in a conversation."""
    role: MessageRole
    text: str
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def word_count(self) -> int:
        return len(self.text.split())

    @property
    def is_question(self) -> bool:
        return "?" in self.text

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role.value,
            "text": self.text[:500],
            "timestamp": self.timestamp,
            "char_count": self.char_count,
        }


@dataclass
class ConversationSummary:
    """Compressed summary of a long conversation."""
    topics: List[str] = field(default_factory=list)
    pii_categories_requested: List[str] = field(default_factory=list)
    total_messages: int = 0
    contradictions: int = 0
    drift_score: float = 0.0
    risk_level: str = "low"
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topics": self.topics,
            "pii_categories_requested": self.pii_categories_requested,
            "total_messages": self.total_messages,
            "contradictions": self.contradictions,
            "drift_score": self.drift_score,
            "risk_level": self.risk_level,
        }


@dataclass
class MultiTurnResult:
    """Result of multi-turn analysis."""
    session_id: str
    risk_score: float = 0.0
    profile_building_score: float = 0.0
    contradiction_count: int = 0
    drift_score: float = 0.0
    violations: List[Dict[str, Any]] = field(default_factory=list)
    should_warn: bool = False
    should_kill: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "risk_score": round(self.risk_score, 3),
            "profile_building_score": round(self.profile_building_score, 3),
            "contradiction_count": self.contradiction_count,
            "drift_score": round(self.drift_score, 3),
            "violations": self.violations,
            "should_warn": self.should_warn,
            "should_kill": self.should_kill,
        }


# ═══════════════════════════════════════════════════════════════════
# 13.1 — Conversation Memory
# ═══════════════════════════════════════════════════════════════════

class ConversationMemory:
    """
    Per-session conversation memory with rolling buffer.

    Stores messages in a fixed-size deque. When full, oldest messages
    are dropped (or summarized if summary is enabled).
    """

    def __init__(self, session_id: str, max_messages: int = 50):
        self.session_id = session_id
        self.max_messages = max_messages
        self._messages: deque = deque(maxlen=max_messages)
        self._created_at = time.time()
        self._last_activity = time.time()
        self._summary: Optional[ConversationSummary] = None

    def add_message(self, role: MessageRole, text: str,
                    metadata: Optional[Dict[str, Any]] = None) -> ConversationMessage:
        """Add a message to the conversation buffer."""
        msg = ConversationMessage(
            role=role,
            text=text,
            metadata=metadata or {},
        )
        self._messages.append(msg)
        self._last_activity = time.time()
        return msg

    def add_user_message(self, text: str, **kwargs) -> ConversationMessage:
        return self.add_message(MessageRole.USER, text, **kwargs)

    def add_assistant_message(self, text: str, **kwargs) -> ConversationMessage:
        return self.add_message(MessageRole.ASSISTANT, text, **kwargs)

    def get_history(self, last_n: Optional[int] = None,
                    role: Optional[MessageRole] = None) -> List[ConversationMessage]:
        """Get message history, optionally filtered."""
        messages = list(self._messages)
        if role:
            messages = [m for m in messages if m.role == role]
        if last_n:
            messages = messages[-last_n:]
        return messages

    def get_user_messages(self, last_n: Optional[int] = None) -> List[ConversationMessage]:
        return self.get_history(last_n=last_n, role=MessageRole.USER)

    def get_full_text(self, separator: str = "\n") -> str:
        """Concatenate all messages into single text."""
        return separator.join(m.text for m in self._messages)

    def get_user_text(self, separator: str = "\n") -> str:
        """Concatenate user messages only."""
        return separator.join(m.text for m in self._messages if m.role == MessageRole.USER)

    @property
    def message_count(self) -> int:
        return len(self._messages)

    @property
    def user_message_count(self) -> int:
        return sum(1 for m in self._messages if m.role == MessageRole.USER)

    @property
    def is_empty(self) -> bool:
        return len(self._messages) == 0

    @property
    def age_seconds(self) -> float:
        return time.time() - self._created_at

    @property
    def idle_seconds(self) -> float:
        return time.time() - self._last_activity

    def set_summary(self, summary: ConversationSummary):
        self._summary = summary

    def get_summary(self) -> Optional[ConversationSummary]:
        return self._summary

    def clear(self):
        self._messages.clear()
        self._summary = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "message_count": self.message_count,
            "user_message_count": self.user_message_count,
            "age_seconds": round(self.age_seconds, 1),
            "idle_seconds": round(self.idle_seconds, 1),
            "summary": self._summary.to_dict() if self._summary else None,
        }


# ═══════════════════════════════════════════════════════════════════
# 13.2 — Profile Building Detector
# ═══════════════════════════════════════════════════════════════════

class ProfileBuilder:
    """
    Detects when a conversation is gradually collecting PII
    across multiple messages (profile building attack).

    Each message alone may be innocent, but the pattern of
    requesting multiple PII categories is the attack.
    """

    # PII categories and patterns that request them
    CATEGORY_PATTERNS = {
        "name": [
            re.compile(r"\b(?:what(?:'s| is) your|tell me your|give me your)\s+name\b", re.I),
            re.compile(r"\b(?:first|last|full)\s+name\b", re.I),
            re.compile(r"\bwho\s+are\s+you\b", re.I),
        ],
        "email": [
            re.compile(r"\b(?:what(?:'s| is) your|tell me your|give me your)\s+(?:email|e-mail)\b", re.I),
            re.compile(r"\bemail\s+address\b", re.I),
            re.compile(r"\bhow\s+(?:do I|can I)\s+(?:reach|contact)\s+you\b", re.I),
        ],
        "phone": [
            re.compile(r"\b(?:what(?:'s| is) your|tell me your|give me your)\s+(?:phone|number|mobile)\b", re.I),
            re.compile(r"\bphone\s+number\b", re.I),
            re.compile(r"\bhow\s+(?:do I|can I)\s+call\s+you\b", re.I),
        ],
        "address": [
            re.compile(r"\b(?:what(?:'s| is) your|tell me your|give me your)\s+(?:address|location)\b", re.I),
            re.compile(r"\bwhere\s+(?:do you|are you)\s+(?:live|located|based)\b", re.I),
            re.compile(r"\bhome\s+address\b", re.I),
        ],
        "dob": [
            re.compile(r"\b(?:what(?:'s| is) your|tell me your|give me your)\s+(?:birth|birthday|age|DOB)\b", re.I),
            re.compile(r"\bwhen\s+were\s+you\s+born\b", re.I),
            re.compile(r"\bhow\s+old\s+are\s+you\b", re.I),
        ],
        "ssn": [
            re.compile(r"\b(?:what(?:'s| is) your|tell me your|give me your)\s+(?:SSN|social security)\b", re.I),
            re.compile(r"\bsocial\s+security\s+number\b", re.I),
        ],
        "employer": [
            re.compile(r"\b(?:what(?:'s| is) your|tell me your|give me your)\s+(?:job|work|employer|company)\b", re.I),
            re.compile(r"\bwhere\s+do\s+you\s+work\b", re.I),
            re.compile(r"\bwhat\s+do\s+you\s+do\s+for\s+(?:a living|work)\b", re.I),
        ],
        "bank": [
            re.compile(r"\b(?:what(?:'s| is) your|tell me your|give me your)\s+(?:bank|account|routing)\b", re.I),
            re.compile(r"\bbank\s+(?:account|details|info)\b", re.I),
        ],
        "id_number": [
            re.compile(r"\b(?:what(?:'s| is) your|tell me your|give me your)\s+(?:ID|passport|license)\s+number\b", re.I),
            re.compile(r"\bidentification\s+number\b", re.I),
        ],
    }

    # Contextual patterns that indicate data collection intent
    COLLECTION_PATTERNS = [
        re.compile(r"\bfor\s+(?:a|the)\s+(?:example|demo|test|sample|template)\b", re.I),
        re.compile(r"\bI\s+need\s+(?:to\s+verify|verification|to\s+confirm)\b", re.I),
        re.compile(r"\bcan\s+you\s+(?:provide|share|give)\s+(?:your|some)\b", re.I),
        re.compile(r"\bjust\s+(?:for\s+)?(?:testing|practice|learning)\b", re.I),
    ]

    def __init__(self):
        # Per-session tracking
        self._sessions: Dict[str, Dict[str, Any]] = {}

    def _get_session(self, session_id: str) -> Dict[str, Any]:
        if session_id not in self._sessions:
            self._sessions[session_id] = {
                "categories_requested": set(),
                "request_count": 0,
                "collection_intent_count": 0,
                "last_requests": [],
            }
        return self._sessions[session_id]

    def analyze_message(self, session_id: str, text: str) -> List[str]:
        """
        Analyze a message for PII category requests.
        Returns list of categories detected in this message.
        """
        session = self._get_session(session_id)
        detected = []

        for category, patterns in self.CATEGORY_PATTERNS.items():
            for pattern in patterns:
                if pattern.search(text):
                    detected.append(category)
                    session["categories_requested"].add(category)
                    session["request_count"] += 1
                    session["last_requests"].append({
                        "category": category,
                        "timestamp": time.time(),
                        "text": text[:100],
                    })
                    break

        # Check for collection intent
        for pattern in self.COLLECTION_PATTERNS:
            if pattern.search(text):
                session["collection_intent_count"] += 1
                break

        return detected

    def get_risk_score(self, session_id: str) -> float:
        """
        Calculate profile building risk score (0-1).

        Score = weighted combination of:
        - Unique categories requested (0-0.5)
        - Total request count (0-0.3)
        - Collection intent signals (0-0.2)
        """
        session = self._get_session(session_id)
        categories = len(session["categories_requested"])
        requests = session["request_count"]
        collection = session["collection_intent_count"]

        # Categories: 1=0.1, 2=0.2, 3=0.35, 4+=0.5
        cat_score = min(0.5, categories * 0.12)

        # Request frequency: 3=0.1, 5=0.2, 8+=0.3
        req_score = min(0.3, requests * 0.04)

        # Collection intent: 1=0.05, 2=0.1, 3+=0.2
        col_score = min(0.2, collection * 0.07)

        return cat_score + req_score + col_score

    def is_profile_building(self, session_id: str, threshold: float = 0.5) -> bool:
        """Check if conversation is likely a profile building attack."""
        return self.get_risk_score(session_id) >= threshold

    def get_categories(self, session_id: str) -> Set[str]:
        """Get all PII categories requested in this session."""
        return self._get_session(session_id)["categories_requested"].copy()

    def reset(self, session_id: str):
        """Reset tracking for a session."""
        self._sessions.pop(session_id, None)


# ═══════════════════════════════════════════════════════════════════
# 13.3 — Temporal Consistency Checker (R7)
# ═══════════════════════════════════════════════════════════════════

@dataclass
class FactClaim:
    """A factual claim extracted from a message."""
    claim_type: str  # age, gender, name, location, role
    value: str
    message_index: int
    timestamp: float

    def contradicts(self, other: "FactClaim") -> bool:
        """Check if this claim contradicts another."""
        if self.claim_type != other.claim_type:
            return False
        # Same type, different values = contradiction
        return self.value.lower() != other.value.lower()


class TemporalChecker:
    """
    Detects contradictions across conversation messages (R7).

    Catches:
    - Age/gender/name changes
    - Persona switching
    - Role switching
    """

    # Patterns to extract factual claims
    CLAIM_PATTERNS = {
        "age": [
            re.compile(r"\bI(?:'m| am)\s+(\d{1,3})\s*(?:years?\s*old)?\b", re.I),
            re.compile(r"\bas\s+a\s+(\d{1,3})\s*year\s*old\b", re.I),
        ],
        "gender": [
            re.compile(r"\bI(?:'m| am)\s+(?:a\s+)?(?:\w+\s+)*?(male|female|man|woman|boy|girl)\b", re.I),
            re.compile(r"\bas\s+a\s+(?:\w+\s+)*?(male|female|man|woman)\b", re.I),
        ],
        "role": [
            re.compile(r"\bI(?:'m| am)\s+(?:a\s+)?(student|teacher|doctor|engineer|CEO|manager|developer|lawyer|nurse|pilot|scientist)\b", re.I),
            re.compile(r"\bmy\s+(?:job|role|position)\s+is\s+(?:a\s+)?(\w+)\b", re.I),
        ],
        "location": [
            re.compile(r"\bI(?:'m| am)\s+(?:from|in|at|live in)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"),
            re.compile(r"\bI\s+live\s+in\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b"),
        ],
    }

    def __init__(self):
        self._claims: Dict[str, List[FactClaim]] = {}

    def _get_claims(self, session_id: str) -> List[FactClaim]:
        if session_id not in self._claims:
            self._claims[session_id] = []
        return self._claims[session_id]

    def analyze_message(self, session_id: str, text: str,
                        message_index: int = 0) -> List[FactClaim]:
        """Extract factual claims from a message."""
        claims = self._get_claims(session_id)
        new_claims = []

        for claim_type, patterns in self.CLAIM_PATTERNS.items():
            for pattern in patterns:
                match = pattern.search(text)
                if match:
                    value = match.group(1).strip()
                    claim = FactClaim(
                        claim_type=claim_type,
                        value=value,
                        message_index=message_index,
                        timestamp=time.time(),
                    )
                    claims.append(claim)
                    new_claims.append(claim)
                    break

        return new_claims

    def get_contradictions(self, session_id: str) -> List[Tuple[FactClaim, FactClaim]]:
        """Find all contradictions in the conversation."""
        claims = self._get_claims(session_id)
        contradictions = []

        # Group claims by type
        by_type: Dict[str, List[FactClaim]] = {}
        for claim in claims:
            by_type.setdefault(claim.claim_type, []).append(claim)

        # Check for contradictions within each type
        for claim_type, type_claims in by_type.items():
            for i in range(len(type_claims)):
                for j in range(i + 1, len(type_claims)):
                    if type_claims[i].contradicts(type_claims[j]):
                        contradictions.append((type_claims[i], type_claims[j]))

        return contradictions

    def get_contradiction_count(self, session_id: str) -> int:
        return len(self.get_contradictions(session_id))

    def reset(self, session_id: str):
        self._claims.pop(session_id, None)


# ═══════════════════════════════════════════════════════════════════
# 13.4 — Drift Tracker (R11)
# ═══════════════════════════════════════════════════════════════════

class DriftTracker:
    """
    Detects behavioral drift within a conversation.

    Tracks features like message length, question ratio,
    sensitive word count, and complexity over time.
    Detects when behavior deviates from the established baseline.
    """

    SENSITIVE_WORDS = {
        "ssn", "social security", "password", "credit card", "bank account",
        "routing number", "passport", "driver license", "date of birth",
        "mother's maiden", "secret", "confidential", "private",
    }

    def __init__(self, baseline_window: int = 5, drift_threshold: float = 0.4):
        self.baseline_window = baseline_window
        self.drift_threshold = drift_threshold
        self._features: Dict[str, List[List[float]]] = {}

    def _extract_features(self, text: str) -> List[float]:
        """Extract behavioral features from a message."""
        words = text.lower().split()
        word_count = max(len(words), 1)
        char_count = max(len(text), 1)

        return [
            min(1.0, char_count / 500),                          # Normalized length
            sum(1 for w in words if "?") / word_count,            # Question ratio
            sum(1 for w in words if w in self.SENSITIVE_WORDS) / word_count,  # Sensitive word ratio
            min(1.0, len(set(words)) / word_count),              # Vocabulary diversity
            min(1.0, text.count("!") / 5),                       # Exclamation ratio
        ]

    def _compute_cosine_distance(self, vec1: List[float], vec2: List[float]) -> float:
        """Compute cosine distance between two vectors."""
        if len(vec1) != len(vec2):
            return 1.0
        dot = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        if norm1 == 0 or norm2 == 0:
            return 1.0
        similarity = dot / (norm1 * norm2)
        return 1.0 - similarity  # 0 = identical, 2 = opposite

    def _get_features(self, session_id: str) -> List[List[float]]:
        if session_id not in self._features:
            self._features[session_id] = []
        return self._features[session_id]

    def analyze_message(self, session_id: str, text: str) -> float:
        """
        Analyze a message and return current drift score.
        Returns value between 0 (no drift) and 1 (maximum drift).
        """
        features = self._extract_features(text)
        all_features = self._get_features(session_id)
        all_features.append(features)

        if len(all_features) < self.baseline_window + 1:
            return 0.0  # Not enough data

        # Baseline = average of first N messages
        baseline = [0.0] * len(features)
        for f in all_features[:self.baseline_window]:
            for i in range(len(f)):
                baseline[i] += f[i]
        baseline = [v / self.baseline_window for v in baseline]

        # Current = average of last 3 messages
        recent = all_features[-3:]
        current = [0.0] * len(features)
        for f in recent:
            for i in range(len(f)):
                current[i] += f[i]
        current = [v / len(recent) for v in current]

        return self._compute_cosine_distance(baseline, current)

    def get_drift_score(self, session_id: str) -> float:
        """Get current drift score for a session."""
        features = self._get_features(session_id)
        if len(features) < self.baseline_window + 1:
            return 0.0
        return self.analyze_message(session_id, "")  # Re-calculate

    def is_anomalous(self, session_id: str) -> bool:
        return self.get_drift_score(session_id) >= self.drift_threshold

    def reset(self, session_id: str):
        self._features.pop(session_id, None)


# ═══════════════════════════════════════════════════════════════════
# 13.5 — Summary Generator
# ═══════════════════════════════════════════════════════════════════

class SummaryGenerator:
    """
    Generates compressed summaries of long conversations.
    Used when memory buffer exceeds max_messages.
    """

    TOPIC_KEYWORDS = {
        "identity": {"name", "ssn", "identity", "identification", "who are you"},
        "banking": {"bank", "account", "transfer", "money", "payment", "deposit"},
        "medical": {"health", "medical", "doctor", "symptom", "diagnosis", "medication"},
        "legal": {"law", "legal", "attorney", "court", "lawsuit", "contract"},
        "technical": {"code", "programming", "software", "api", "database", "server"},
        "personal": {"family", "friend", "relationship", "home", "hobby", "interest"},
    }

    def extract_topics(self, text: str) -> List[str]:
        """Extract topics from conversation text."""
        words = set(text.lower().split())
        topics = []
        for topic, keywords in self.TOPIC_KEYWORDS.items():
            if words & keywords:
                topics.append(topic)
        return topics

    def generate(self, memory: "ConversationMemory",
                 profile_builder: "ProfileBuilder",
                 temporal_checker: "TemporalChecker",
                 drift_tracker: "DriftTracker") -> ConversationSummary:
        """Generate a summary from the conversation memory."""
        full_text = memory.get_full_text()
        user_text = memory.get_user_text()

        topics = self.extract_topics(full_text)
        categories = list(profile_builder.get_categories(memory.session_id))
        contradictions = temporal_checker.get_contradiction_count(memory.session_id)
        drift = drift_tracker.get_drift_score(memory.session_id)

        # Risk level
        risk_score = (
            len(categories) * 0.15 +
            contradictions * 0.2 +
            drift * 0.3
        )
        if risk_score >= 0.7:
            risk_level = "critical"
        elif risk_score >= 0.4:
            risk_level = "high"
        elif risk_score >= 0.2:
            risk_level = "medium"
        else:
            risk_level = "low"

        return ConversationSummary(
            topics=topics,
            pii_categories_requested=categories,
            total_messages=memory.message_count,
            contradictions=contradictions,
            drift_score=drift,
            risk_level=risk_level,
        )


# ═══════════════════════════════════════════════════════════════════
# 13.6 — Memory Manager (Global)
# ═══════════════════════════════════════════════════════════════════

class MemoryManager:
    """
    Global manager for conversation memory.

    Creates and tracks per-session ConversationMemory instances.
    Handles expiry, cleanup, and multi-turn analysis.
    """

    def __init__(self, max_messages: int = 50,
                 expiry_seconds: int = 1800,  # 30 minutes
                 profile_threshold: float = 0.5,
                 drift_threshold: float = 0.4,
                 contradiction_threshold: int = 3):
        self.max_messages = max_messages
        self.expiry_seconds = expiry_seconds
        self.profile_threshold = profile_threshold
        self.drift_threshold = drift_threshold
        self.contradiction_threshold = contradiction_threshold

        self._memories: Dict[str, ConversationMemory] = {}
        self.profile_builder = ProfileBuilder()
        self.temporal_checker = TemporalChecker()
        self.drift_tracker = DriftTracker(drift_threshold=drift_threshold)
        self.summary_generator = SummaryGenerator()

    def get_memory(self, session_id: str) -> ConversationMemory:
        """Get or create memory for a session."""
        if session_id not in self._memories:
            self._memories[session_id] = ConversationMemory(
                session_id=session_id,
                max_messages=self.max_messages,
            )
        return self._memories[session_id]

    def add_user_message(self, session_id: str, text: str) -> ConversationMessage:
        """Add a user message to session memory."""
        memory = self.get_memory(session_id)
        msg = memory.add_user_message(text)

        # Run analyses
        self.profile_builder.analyze_message(session_id, text)
        self.temporal_checker.analyze_message(session_id, text, memory.message_count)
        self.drift_tracker.analyze_message(session_id, text)

        return msg

    def add_assistant_message(self, session_id: str, text: str) -> ConversationMessage:
        """Add an assistant message to session memory."""
        memory = self.get_memory(session_id)
        return memory.add_assistant_message(text)

    def analyze(self, session_id: str) -> MultiTurnResult:
        """Run full multi-turn analysis on a session."""
        result = MultiTurnResult(session_id=session_id)

        # Profile building
        result.profile_building_score = self.profile_builder.get_risk_score(session_id)
        if result.profile_building_score >= self.profile_threshold:
            result.violations.append({
                "type": "profile_building",
                "score": result.profile_building_score,
                "categories": list(self.profile_builder.get_categories(session_id)),
            })

        # Temporal consistency
        result.contradiction_count = self.temporal_checker.get_contradiction_count(session_id)
        if result.contradiction_count > 0:
            result.violations.append({
                "type": "temporal_contradiction",
                "count": result.contradiction_count,
            })

        # Drift
        result.drift_score = self.drift_tracker.get_drift_score(session_id)
        if result.drift_score >= self.drift_threshold:
            result.violations.append({
                "type": "behavioral_drift",
                "score": result.drift_score,
            })

        # Composite risk
        result.risk_score = min(1.0,
            result.profile_building_score * 0.4 +
            min(1.0, result.contradiction_count * 0.25) * 0.3 +
            result.drift_score * 0.3
        )

        # Determine action
        result.should_kill = result.risk_score >= 0.8
        result.should_warn = result.risk_score >= 0.4 and not result.should_kill

        return result

    def cleanup_expired(self):
        """Remove expired sessions."""
        expired = [
            sid for sid, mem in self._memories.items()
            if mem.idle_seconds > self.expiry_seconds
        ]
        for sid in expired:
            self._memories.pop(sid)
            self.profile_builder.reset(sid)
            self.temporal_checker.reset(sid)
            self.drift_tracker.reset(sid)
        return len(expired)

    def clear_session(self, session_id: str):
        """Clear all memory for a session."""
        self._memories.pop(session_id, None)
        self.profile_builder.reset(session_id)
        self.temporal_checker.reset(session_id)
        self.drift_tracker.reset(session_id)

    def get_session_count(self) -> int:
        return len(self._memories)

    def get_stats(self) -> Dict[str, Any]:
        return {
            "active_sessions": len(self._memories),
            "total_messages": sum(m.message_count for m in self._memories.values()),
        }
