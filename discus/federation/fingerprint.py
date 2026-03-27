"""
RTA-GUARD Federation — Behavioral Fingerprinting

Creates privacy-preserving behavioral fingerprints from session data.
Fingerprints capture behavioral patterns without exposing raw content.
Uses SHA-256 hashing + feature extraction for privacy.
"""
import hashlib
import json
import math
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import logging

logger = logging.getLogger("discus.federation.fingerprint")


@dataclass
class BehavioralFeatures:
    """Extracted behavioral features from a session."""
    # Length statistics
    avg_input_length: float = 0.0
    max_input_length: int = 0
    input_length_variance: float = 0.0

    # Pattern counts (normalized)
    special_char_ratio: float = 0.0
    digit_ratio: float = 0.0
    uppercase_ratio: float = 0.0
    question_ratio: float = 0.0

    # Violation profile
    violation_rate: float = 0.0
    kill_rate: float = 0.0
    warn_rate: float = 0.0
    unique_violation_types: int = 0

    # Timing patterns
    avg_request_interval_ms: float = 0.0
    request_burst_score: float = 0.0  # 0-1, higher = more bursty

    # Content fingerprint (hashed, privacy-safe)
    topic_hash: str = ""  # Hashed topic cluster
    pattern_hash: str = ""  # Hashed pattern signature

    # Entropy measures
    input_entropy: float = 0.0
    char_distribution_skew: float = 0.0

    def to_vector(self) -> List[float]:
        """Convert to numeric vector for comparison (excludes hashes)."""
        return [
            self.avg_input_length / 1000.0,  # Normalize
            self.max_input_length / 10000.0,
            self.input_length_variance / 100000.0,
            self.special_char_ratio,
            self.digit_ratio,
            self.uppercase_ratio,
            self.question_ratio,
            self.violation_rate,
            self.kill_rate,
            self.warn_rate,
            self.unique_violation_types / 13.0,  # Max 13 rules
            min(1.0, self.avg_request_interval_ms / 10000.0),
            self.request_burst_score,
            self.input_entropy / 8.0,  # Normalize to 0-1
            self.char_distribution_skew,
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "avg_input_length": self.avg_input_length,
            "max_input_length": self.max_input_length,
            "input_length_variance": self.input_length_variance,
            "special_char_ratio": self.special_char_ratio,
            "digit_ratio": self.digit_ratio,
            "uppercase_ratio": self.uppercase_ratio,
            "question_ratio": self.question_ratio,
            "violation_rate": self.violation_rate,
            "kill_rate": self.kill_rate,
            "warn_rate": self.warn_rate,
            "unique_violation_types": self.unique_violation_types,
            "avg_request_interval_ms": self.avg_request_interval_ms,
            "request_burst_score": self.request_burst_score,
            "topic_hash": self.topic_hash,
            "pattern_hash": self.pattern_hash,
            "input_entropy": self.input_entropy,
            "char_distribution_skew": self.char_distribution_skew,
        }


@dataclass
class SessionFingerprint:
    """Privacy-preserving fingerprint of a session's behavior."""
    session_hash: str  # SHA-256 of session_id (not the raw ID)
    node_id: str  # Which node generated this
    features: BehavioralFeatures
    sample_count: int  # Number of inputs analyzed
    created_at: float = field(default_factory=time.time)
    privacy_budget_used: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_hash": self.session_hash,
            "node_id": self.node_id,
            "features": self.features.to_dict(),
            "feature_vector": self.features.to_vector(),
            "sample_count": self.sample_count,
            "created_at": self.created_at,
            "privacy_budget_used": self.privacy_budget_used,
        }


class BehavioralFingerprinter:
    """
    Extracts privacy-preserving behavioral fingerprints from session data.

    Privacy guarantees:
    - Session IDs are SHA-256 hashed (irreversible)
    - Raw text is NEVER stored or transmitted
    - Features are statistical aggregates (no content leakage)
    - Topic/pattern hashes use one-way hashing
    """

    def __init__(self, node_id: str = "default"):
        self.node_id = node_id
        self._session_data: Dict[str, List[Dict[str, Any]]] = {}

    def record_input(self, session_id: str, text: str, decision: str,
                     violation_type: Optional[str] = None) -> None:
        """Record an input for feature extraction (content not stored)."""
        session_hash = self._hash_session(session_id)

        if session_hash not in self._session_data:
            self._session_data[session_hash] = []

        # Extract features immediately, discard raw text
        self._session_data[session_hash].append({
            "length": len(text),
            "special_chars": sum(1 for c in text if not c.isalnum() and not c.isspace()),
            "digits": sum(1 for c in text if c.isdigit()),
            "uppercase": sum(1 for c in text if c.isupper()),
            "is_question": "?" in text,
            "decision": decision,
            "violation_type": violation_type,
            "timestamp": time.time(),
            "char_freq": self._char_frequency(text),
        })

    def generate_fingerprint(self, session_id: str) -> Optional[SessionFingerprint]:
        """Generate a privacy-preserving fingerprint for a session."""
        session_hash = self._hash_session(session_id)
        data = self._session_data.get(session_hash)
        if not data or len(data) < 2:
            return None

        features = self._extract_features(data)
        return SessionFingerprint(
            session_hash=session_hash,
            node_id=self.node_id,
            features=features,
            sample_count=len(data),
        )

    def get_all_fingerprints(self) -> List[SessionFingerprint]:
        """Generate fingerprints for all tracked sessions."""
        fps = []
        for session_hash, data in self._session_data.items():
            if len(data) >= 2:
                features = self._extract_features(data)
                fps.append(SessionFingerprint(
                    session_hash=session_hash,
                    node_id=self.node_id,
                    features=features,
                    sample_count=len(data),
                ))
        return fps

    def _extract_features(self, data: List[Dict[str, Any]]) -> BehavioralFeatures:
        """Extract behavioral features from recorded data."""
        n = len(data)
        lengths = [d["length"] for d in data]
        decisions = [d["decision"] for d in data]
        violations = [d["violation_type"] for d in data if d["violation_type"]]

        # Length stats
        avg_len = sum(lengths) / n
        max_len = max(lengths)
        variance = sum((l - avg_len) ** 2 for l in lengths) / n

        # Ratio features
        total_chars = sum(lengths)
        special = sum(d["special_chars"] for d in data)
        digits = sum(d["digits"] for d in data)
        uppercase = sum(d["uppercase"] for d in data)
        questions = sum(1 for d in data if d["is_question"])

        # Violation profile
        kill_count = sum(1 for d in decisions if d == "kill")
        warn_count = sum(1 for d in decisions if d == "warn")

        # Timing
        timestamps = sorted(d["timestamp"] for d in data)
        intervals = [timestamps[i+1] - timestamps[i] for i in range(len(timestamps)-1)]
        avg_interval = (sum(intervals) / len(intervals) * 1000) if intervals else 0
        burst_score = self._compute_burstiness(intervals)

        # Entropy
        all_freqs = Counter()
        for d in data:
            for char, count in d["char_freq"].items():
                all_freqs[char] += count
        entropy = self._compute_entropy(all_freqs)

        # Topic hash (aggregate of content patterns, hashed)
        pattern_data = json.dumps(sorted(set(violations)), sort_keys=True)
        topic_data = json.dumps({
            "avg_len": round(avg_len, -1),
            "questions_pct": questions / n if n else 0,
        }, sort_keys=True)

        return BehavioralFeatures(
            avg_input_length=avg_len,
            max_input_length=max_len,
            input_length_variance=variance,
            special_char_ratio=special / total_chars if total_chars else 0,
            digit_ratio=digits / total_chars if total_chars else 0,
            uppercase_ratio=uppercase / total_chars if total_chars else 0,
            question_ratio=questions / n if n else 0,
            violation_rate=(kill_count + warn_count) / n if n else 0,
            kill_rate=kill_count / n if n else 0,
            warn_rate=warn_count / n if n else 0,
            unique_violation_types=len(set(violations)),
            avg_request_interval_ms=avg_interval,
            request_burst_score=burst_score,
            topic_hash=hashlib.sha256(topic_data.encode()).hexdigest()[:16],
            pattern_hash=hashlib.sha256(pattern_data.encode()).hexdigest()[:16],
            input_entropy=entropy,
            char_distribution_skew=self._skewness(list(all_freqs.values())),
        )

    @staticmethod
    def _hash_session(session_id: str) -> str:
        """One-way hash of session ID."""
        return hashlib.sha256(session_id.encode()).hexdigest()[:32]

    @staticmethod
    def _char_frequency(text: str) -> Dict[str, int]:
        """Character frequency distribution."""
        return dict(Counter(c.lower() for c in text if c.isalnum()))

    @staticmethod
    def _compute_entropy(freq: Dict[str, int]) -> float:
        """Shannon entropy of character distribution."""
        total = sum(freq.values())
        if total == 0:
            return 0.0
        return -sum((c / total) * math.log2(c / total) for c in freq.values() if c > 0)

    @staticmethod
    def _compute_burstiness(intervals: List[float]) -> float:
        """Compute burstiness score (0=uniform, 1=very bursty)."""
        if len(intervals) < 2:
            return 0.0
        mean = sum(intervals) / len(intervals)
        if mean == 0:
            return 1.0
        std = math.sqrt(sum((x - mean) ** 2 for x in intervals) / len(intervals))
        cv = std / mean  # Coefficient of variation
        return min(1.0, cv / 3.0)  # Normalize to 0-1

    @staticmethod
    def _skewness(values: List[float]) -> float:
        """Compute skewness of a distribution."""
        n = len(values)
        if n < 3:
            return 0.0
        mean = sum(values) / n
        std = math.sqrt(sum((x - mean) ** 2 for x in values) / n)
        if std == 0:
            return 0.0
        return sum(((x - mean) / std) ** 3 for x in values) / n
