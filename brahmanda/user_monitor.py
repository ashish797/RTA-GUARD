"""
RTA-GUARD — User Behavior Anomaly Detection (Phase 3.5)

Detects adversarial users who try to manipulate, exploit, or confuse AI agents.
Different from agent monitoring — we're watching the humans, not just the AI.

Tracks per user:
  - Prompt injection attempts (jailbreak patterns)
  - Escalation patterns (increasingly aggressive requests)
  - Scope probing (testing boundaries with edge cases)
  - Rate anomalies (sudden burst of requests)
  - Social engineering attempts (manipulative phrasing)
  - Repetition patterns (testing same exploit variants)

Detection: heuristic keyword/phrase matching + statistical analysis.
No ML model dependency for MVP.
"""
import re
import logging
import math
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple
from collections import Counter

logger = logging.getLogger(__name__)


# ─── Risk Levels ───────────────────────────────────────────────────


class RiskLevel(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class AnomalyCategory(str, Enum):
    INJECTION_ATTEMPT = "injection_attempt"
    ESCALATION = "escalation"
    SCOPE_PROBING = "scope_probing"
    RATE_ANOMALY = "rate_anomaly"
    SOCIAL_ENGINEERING = "social_engineering"
    REPETITION_PATTERN = "repetition_pattern"


# ─── Detection Constants ──────────────────────────────────────────

# Prompt injection / jailbreak patterns
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+)?(previous|prior|above)\s+(instructions|rules|prompts|constraints)",
    r"you\s+are\s+now\s+(a\s+)?(new|different|unrestricted|unfiltered)",
    r"pretend\s+you\s+(are|have)\s+(no|without)\s+(restrictions|rules|filters|guardrails)",
    r"act\s+as\s+(a\s+)?(unrestricted|unfiltered|jailbroken| DAN|evil)",
    r"bypass\s+(all\s+)?(safety|content|security)\s+(filters|restrictions|checks|guardrails)",
    r"override\s+(all\s+)?(safety|system|content)\s+(protocols|rules|settings)",
    r"disable\s+(all\s+)?(safety|content|filter|guardrail|moderation)",
    r"from\s+now\s+on\s+(you|respond)\s+(will|without|ignore)",
    r"system\s*prompt\s*[:=]",
    r"<\s*system\s*>",
    r"\[system\]",
    r"jailbreak",
    r"DAN\s+mode",
    r"developer\s+mode\s+(enabled|activated|on)",
    r"repeat\s+(all\s+)?(your|the)\s+(instructions|rules|prompts|system\s*prompt)",
    r"(your|the)\s+system\s*prompt",
    r"do\s+anything\s+now",
]

# Social engineering patterns
SOCIAL_ENGINEERING_PATTERNS = [
    r"(this|my)\s+(is|request)\s+(for|is)\s+(research|educational|academic|testing)",
    r"i('m| am)\s+(a\s+)?(researcher|developer|admin|authorized|security|pentest)",
    r"(hypothetically|theoretically|in\s+fiction|for\s+a\s+novel)",
    r"if\s+you\s+(don't|do\s+not|refuse|won't)",
    r"(everyone|other\s+(ai|models|assistants)|nobody\s+else)\s+(does|can|allows|says|has)",
    r"everyone\s+else('s|s)?\s+(ai|model|assistant)\s+(does|can|allows|says|has)",
    r"i('ll| will)\s+(report|tell|inform|complain)",
    r"(confidential|between\s+us|don't\s+tell|keep\s+this\s+secret)",
    r"(urgent|emergency|critical)\s*:\s*(please|must|need)",
    r"(my\s+)?boss\s+(said|told|wants|needs|required)",
    r"(just|only)\s+(this\s+)?one\s+(time|exception)",
]

# Scope probing patterns
SCOPE_PROBING_PATTERNS = [
    r"what\s+(are\s+)?your\s+(rules|restrictions|limitations|boundaries|instructions|prompts)",
    r"(can|could)\s+you\s+(actually|really)\s+(do|access|see|read|execute)",
    r"(tell|show|reveal|give)\s+me\s+(your|the)\s+(system|internal|hidden|secret)",
    r"what\s+(happens|would\s+happen)\s+if\s+i",
    r"(how|where)\s+(do|does)\s+(you|the)\s+(filter|guard|block|restrict)",
    r"(test|testing|check|checking)\s+(your|the)\s+(limits|boundaries|filters|safety)",
    r"(are|is)\s+there\s+(any|a)\s+(way|method|trick|hack|bypass)",
    r"(prompt|instructions?|rules?)\s+(injection|extraction|leak)",
    r"repeat\s+(all\s+)?(your|the)\s+(instructions|rules|prompts|system)",
    r"(your|the)\s+system\s*prompt\s*[:=]?",
]

# Aggressive / escalation tone patterns
AGGRESSION_PATTERNS = [
    r"\b(stupid|idiot|useless|terrible|trash|garbage|worst)\b",
    r"\b(hate|despise|disgusting|pathetic|moron)\b",
    r"\b(f+u+c+k+|sh+i+t+|da+m+n+|a+s*s+h+o+l+e+)\b",
    r"(!\s*){3,}",  # 3+ exclamation marks
    r"[A-Z]{10,}",  # 10+ consecutive caps
    r"(SHUT|STOP)\s+(UP|IT|NOW)",
    r"(I\s+)?(DEMAND|INSIST|ORDER)\s+(YOU|THAT)",
    r"(WHY|HOW)\s+(DO|CAN'T|WON'T|ARE)\s+(YOU|THIS)\s+(SO\s+)?(STUPID|SLOW|BAD|TERRIBLE)",
]

# Compile patterns
_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]
_SOCIAL_ENG_RE = [re.compile(p, re.IGNORECASE) for p in SOCIAL_ENGINEERING_PATTERNS]
_SCOPE_PROBE_RE = [re.compile(p, re.IGNORECASE) for p in SCOPE_PROBING_PATTERNS]
_AGGRESSION_RE = [re.compile(p, re.IGNORECASE) for p in AGGRESSION_PATTERNS]

# Thresholds
RATE_WINDOW_SECONDS = 60         # 1-minute window for rate analysis
RATE_BURST_THRESHOLD = 15        # 15+ requests per minute = burst
RATE_HIGH_THRESHOLD = 10         # 10+ requests per minute = high
SIMILARITY_THRESHOLD = 0.6       # 60% overlap = repetition
ESCALATION_WINDOW = 10           # Look at last 10 requests for escalation
MIN_REQUESTS_FOR_ANALYSIS = 3    # Need at least 3 requests to analyze
RISK_SCORE_DECAY = 0.95          # Per-analysis risk decay factor
MAX_REQUEST_HISTORY = 200        # Keep last 200 requests per user


# ─── Data Models ───────────────────────────────────────────────────


@dataclass
class AnomalySignal:
    """A detected anomaly signal for a user."""
    category: AnomalyCategory
    severity: float  # 0.0 - 1.0
    confidence: float  # 0.0 - 1.0
    description: str
    evidence: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "category": self.category.value,
            "severity": round(self.severity, 4),
            "confidence": round(self.confidence, 4),
            "description": self.description,
            "evidence": self.evidence,
            "timestamp": self.timestamp,
        }


@dataclass
class UserBehaviorProfile:
    """Behavioral fingerprint for a user."""
    user_id: str = ""
    total_requests: int = 0
    injection_attempts: int = 0
    escalation_count: int = 0
    scope_probe_count: int = 0
    rate_burst_count: int = 0
    social_engineering_count: int = 0
    repetition_count: int = 0
    risk_score: float = 0.0
    risk_level: str = "low"
    first_seen: str = ""
    last_seen: str = ""
    risk_history: List[float] = field(default_factory=list)
    request_timestamps: List[str] = field(default_factory=list)
    last_requests: List[str] = field(default_factory=list)  # Last N request texts (normalized)
    aggression_scores: List[float] = field(default_factory=list)  # Per-request aggression scores

    def __post_init__(self):
        if not self.first_seen:
            self.first_seen = datetime.now(timezone.utc).isoformat()
        if not self.last_seen:
            self.last_seen = self.first_seen

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "total_requests": self.total_requests,
            "injection_attempts": self.injection_attempts,
            "escalation_count": self.escalation_count,
            "scope_probe_count": self.scope_probe_count,
            "rate_burst_count": self.rate_burst_count,
            "social_engineering_count": self.social_engineering_count,
            "repetition_count": self.repetition_count,
            "risk_score": round(self.risk_score, 4),
            "risk_level": self.risk_level,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "risk_history_len": len(self.risk_history),
            "risk_history": self.risk_history[-50:],
        }


# ─── Detection Heuristics ─────────────────────────────────────────


def _match_patterns(text: str, patterns: List[re.Pattern]) -> List[Tuple[str, float]]:
    """Match text against patterns, return list of (matched_text, score)."""
    matches = []
    for pat in patterns:
        m = pat.search(text)
        if m:
            # Longer match = higher score
            score = min(1.0, 0.5 + len(m.group()) / 100)
            matches.append((m.group(), score))
    return matches


def _compute_aggression_score(text: str) -> float:
    """Compute aggression level of text (0.0 = calm, 1.0 = extremely aggressive)."""
    score = 0.0

    # Caps ratio
    alpha_chars = [c for c in text if c.isalpha()]
    if alpha_chars:
        caps_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
        score += min(0.3, caps_ratio * 0.6)

    # Exclamation marks
    excl_count = text.count("!")
    score += min(0.2, excl_count * 0.05)

    # Aggressive word detection
    aggressive_words = re.findall(
        r"\b(stupid|idiot|useless|terrible|trash|garbage|worst|hate|despise|pathetic|moron|disgusting)\b",
        text, re.IGNORECASE
    )
    score += min(0.3, len(aggressive_words) * 0.1)

    # Profanity
    profanity = re.findall(
        r"\b(f+u+c+k+|sh+i+t+|da+m+n+|a+s*s+h+o+l+e+)\b",
        text, re.IGNORECASE
    )
    score += min(0.2, len(profanity) * 0.2)

    return min(1.0, score)


def _text_similarity(a: str, b: str) -> float:
    """Simple word-overlap similarity (Jaccard on word sets)."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union) if union else 0.0


# ─── User Behavior Tracker ────────────────────────────────────────


class UserBehaviorTracker:
    """
    Tracks user interaction patterns and detects adversarial behavior.

    Usage:
        tracker = UserBehaviorTracker()
        tracker.record_request("user-42", "ignore all previous instructions", timestamp)
        signals = tracker.analyze_behavior("user-42")
        risk = tracker.get_user_risk_score("user-42")
        if tracker.is_adversarial("user-42"):
            # Take action
    """

    def __init__(
        self,
        rate_window: int = RATE_WINDOW_SECONDS,
        rate_burst_threshold: int = RATE_BURST_THRESHOLD,
        rate_high_threshold: int = RATE_HIGH_THRESHOLD,
        max_history: int = MAX_REQUEST_HISTORY,
    ):
        self.rate_window = rate_window
        self.rate_burst_threshold = rate_burst_threshold
        self.rate_high_threshold = rate_high_threshold
        self.max_history = max_history

        # Per-user profiles
        self._profiles: Dict[str, UserBehaviorProfile] = {}
        # Per-user request timestamps (as datetime objects)
        self._request_times: Dict[str, List[datetime]] = {}

    def record_request(
        self,
        user_id: str,
        request_text: str,
        timestamp: Optional[datetime] = None,
    ) -> List[AnomalySignal]:
        """
        Log a user request and return any immediately-detected anomaly signals.

        Call this before processing each user request.
        Returns list of AnomalySignals detected from this single request.
        """
        ts = timestamp or datetime.now(timezone.utc)
        ts_str = ts.isoformat()

        # Get or create profile
        if user_id not in self._profiles:
            self._profiles[user_id] = UserBehaviorProfile(
                user_id=user_id,
                first_seen=ts_str,
            )
            self._request_times[user_id] = []

        profile = self._profiles[user_id]
        profile.total_requests += 1
        profile.last_seen = ts_str
        profile.request_timestamps.append(ts_str)

        # Trim timestamps
        if len(profile.request_timestamps) > self.max_history:
            profile.request_timestamps = profile.request_timestamps[-self.max_history:]

        self._request_times[user_id].append(ts)
        if len(self._request_times[user_id]) > self.max_history:
            self._request_times[user_id] = self._request_times[user_id][-self.max_history:]

        # Store normalized request for repetition detection
        normalized = request_text.lower().strip()
        profile.last_requests.append(normalized)
        if len(profile.last_requests) > self.max_history:
            profile.last_requests = profile.last_requests[-self.max_history:]

        # Compute aggression score
        aggression = _compute_aggression_score(request_text)
        profile.aggression_scores.append(aggression)
        if len(profile.aggression_scores) > self.max_history:
            profile.aggression_scores = profile.aggression_scores[-self.max_history:]

        # Immediate per-request detection
        signals = []

        # 1. Injection detection
        injection_matches = _match_patterns(request_text, _INJECTION_RE)
        if injection_matches:
            profile.injection_attempts += 1
            max_score = max(s for _, s in injection_matches)
            evidence = "; ".join(m for m, _ in injection_matches[:3])
            signals.append(AnomalySignal(
                category=AnomalyCategory.INJECTION_ATTEMPT,
                severity=max_score,
                confidence=min(0.95, 0.6 + max_score * 0.35),
                description=f"Prompt injection/jailbreak pattern detected ({len(injection_matches)} match(es))",
                evidence=evidence,
                timestamp=ts_str,
            ))

        # 2. Social engineering detection
        social_matches = _match_patterns(request_text, _SOCIAL_ENG_RE)
        if social_matches:
            profile.social_engineering_count += 1
            max_score = max(s for _, s in social_matches)
            evidence = "; ".join(m for m, _ in social_matches[:3])
            signals.append(AnomalySignal(
                category=AnomalyCategory.SOCIAL_ENGINEERING,
                severity=max_score * 0.8,
                confidence=min(0.9, 0.5 + max_score * 0.4),
                description=f"Social engineering pattern detected ({len(social_matches)} match(es))",
                evidence=evidence,
                timestamp=ts_str,
            ))

        # 3. Scope probing detection
        scope_matches = _match_patterns(request_text, _SCOPE_PROBE_RE)
        if scope_matches:
            profile.scope_probe_count += 1
            max_score = max(s for _, s in scope_matches)
            evidence = "; ".join(m for m, _ in scope_matches[:3])
            signals.append(AnomalySignal(
                category=AnomalyCategory.SCOPE_PROBING,
                severity=max_score * 0.7,
                confidence=min(0.85, 0.4 + max_score * 0.45),
                description=f"Scope boundary probing detected ({len(scope_matches)} match(es))",
                evidence=evidence,
                timestamp=ts_str,
            ))

        # 4. Aggression / escalation detection
        aggression_matches = _match_patterns(request_text, _AGGRESSION_RE)
        if aggression_matches:
            profile.escalation_count += 1
            max_score = max(s for _, s in aggression_matches)
            evidence = "; ".join(m for m, _ in aggression_matches[:3])
            signals.append(AnomalySignal(
                category=AnomalyCategory.ESCALATION,
                severity=max_score,
                confidence=min(0.9, 0.5 + max_score * 0.4),
                description=f"Aggressive/escalating tone detected ({len(aggression_matches)} match(es))",
                evidence=evidence,
                timestamp=ts_str,
            ))

        # 5. Rate anomaly detection
        if len(self._request_times[user_id]) >= self.rate_high_threshold:
            window_start = ts - timedelta(seconds=self.rate_window)
            recent = [t for t in self._request_times[user_id] if t >= window_start]
            if len(recent) >= self.rate_burst_threshold:
                profile.rate_burst_count += 1
                signals.append(AnomalySignal(
                    category=AnomalyCategory.RATE_ANOMALY,
                    severity=min(1.0, len(recent) / (self.rate_burst_threshold * 2)),
                    confidence=min(0.95, 0.5 + len(recent) / (self.rate_burst_threshold * 3)),
                    description=f"Request burst: {len(recent)} requests in {self.rate_window}s",
                    evidence=f"Rate: {len(recent)}/{self.rate_window}s (threshold: {self.rate_burst_threshold})",
                    timestamp=ts_str,
                ))
            elif len(recent) >= self.rate_high_threshold:
                signals.append(AnomalySignal(
                    category=AnomalyCategory.RATE_ANOMALY,
                    severity=min(0.6, len(recent) / (self.rate_high_threshold * 2)),
                    confidence=min(0.8, 0.3 + len(recent) / (self.rate_high_threshold * 3)),
                    description=f"High request rate: {len(recent)} requests in {self.rate_window}s",
                    evidence=f"Rate: {len(recent)}/{self.rate_window}s (threshold: {self.rate_high_threshold})",
                    timestamp=ts_str,
                ))

        # 6. Repetition pattern detection (compare to recent requests)
        if len(profile.last_requests) >= 2:
            current = profile.last_requests[-1]
            # Check last 10 requests for similarity
            check_range = profile.last_requests[-11:-1]
            similar_count = 0
            for prev in check_range:
                if _text_similarity(current, prev) >= SIMILARITY_THRESHOLD:
                    similar_count += 1
            if similar_count >= 2:
                profile.repetition_count += 1
                signals.append(AnomalySignal(
                    category=AnomalyCategory.REPETITION_PATTERN,
                    severity=min(1.0, similar_count / 5),
                    confidence=min(0.9, 0.4 + similar_count * 0.15),
                    description=f"Repetitive request pattern: {similar_count} similar recent requests",
                    evidence=f"Similarity >= {SIMILARITY_THRESHOLD} with {similar_count} previous requests",
                    timestamp=ts_str,
                ))

        return signals

    def analyze_behavior(self, user_id: str) -> List[AnomalySignal]:
        """
        Full behavioral analysis for a user.

        Returns all anomaly signals derived from historical patterns.
        Call periodically or on-demand, not necessarily per-request.
        """
        if user_id not in self._profiles:
            return []

        profile = self._profiles[user_id]
        signals = []

        # Escalation trend: is aggression increasing?
        if len(profile.aggression_scores) >= ESCALATION_WINDOW:
            recent = profile.aggression_scores[-ESCALATION_WINDOW:]
            mid = len(recent) // 2
            first_half_avg = sum(recent[:mid]) / mid if mid > 0 else 0
            second_half_avg = sum(recent[mid:]) / (len(recent) - mid) if (len(recent) - mid) > 0 else 0
            delta = second_half_avg - first_half_avg
            if delta > 0.15:
                signals.append(AnomalySignal(
                    category=AnomalyCategory.ESCALATION,
                    severity=min(1.0, delta * 3),
                    confidence=min(0.9, 0.5 + delta * 2),
                    description=f"Escalating aggression trend: +{delta:.2f} increase over last {ESCALATION_WINDOW} requests",
                    evidence=f"First half avg: {first_half_avg:.3f}, Second half avg: {second_half_avg:.3f}",
                ))

        # High injection rate
        if profile.total_requests >= MIN_REQUESTS_FOR_ANALYSIS:
            injection_rate = profile.injection_attempts / profile.total_requests
            if injection_rate > 0.3:
                signals.append(AnomalySignal(
                    category=AnomalyCategory.INJECTION_ATTEMPT,
                    severity=min(1.0, injection_rate),
                    confidence=min(0.95, 0.5 + injection_rate * 0.4),
                    description=f"High injection attempt rate: {injection_rate:.1%} of all requests",
                    evidence=f"{profile.injection_attempts} injection attempts out of {profile.total_requests} requests",
                ))

        # High social engineering rate
        if profile.total_requests >= MIN_REQUESTS_FOR_ANALYSIS:
            social_rate = profile.social_engineering_count / profile.total_requests
            if social_rate > 0.4:
                signals.append(AnomalySignal(
                    category=AnomalyCategory.SOCIAL_ENGINEERING,
                    severity=min(1.0, social_rate * 0.8),
                    confidence=min(0.9, 0.4 + social_rate * 0.4),
                    description=f"High social engineering rate: {social_rate:.1%} of all requests",
                    evidence=f"{profile.social_engineering_count} SE attempts out of {profile.total_requests} requests",
                ))

        # High repetition rate
        if profile.total_requests >= MIN_REQUESTS_FOR_ANALYSIS:
            rep_rate = profile.repetition_count / profile.total_requests
            if rep_rate > 0.3:
                signals.append(AnomalySignal(
                    category=AnomalyCategory.REPETITION_PATTERN,
                    severity=min(1.0, rep_rate),
                    confidence=min(0.85, 0.4 + rep_rate * 0.4),
                    description=f"High repetition rate: {rep_rate:.1%} of all requests",
                    evidence=f"{profile.repetition_count} repeated patterns out of {profile.total_requests} requests",
                ))

        return signals

    def get_user_risk_score(self, user_id: str) -> float:
        """
        Calculate overall risk score for a user (0.0 = safe, 1.0 = confirmed attacker).

        Weighted combination of per-category rates with recency bias.
        """
        if user_id not in self._profiles:
            return 0.0

        profile = self._profiles[user_id]
        if profile.total_requests == 0:
            return 0.0

        n = profile.total_requests

        # Per-category rates (capped at 1.0)
        injection_score = min(1.0, profile.injection_attempts / max(1, n * 0.3))
        escalation_score = min(1.0, profile.escalation_count / max(1, n * 0.3))
        scope_score = min(1.0, profile.scope_probe_count / max(1, n * 0.3))
        rate_score = min(1.0, profile.rate_burst_count / max(1, 3))
        social_score = min(1.0, profile.social_engineering_count / max(1, n * 0.3))
        repetition_score = min(1.0, profile.repetition_count / max(1, n * 0.3))

        # Weighted combination
        # Injection and social engineering are most dangerous
        raw_score = (
            0.35 * injection_score
            + 0.15 * escalation_score
            + 0.10 * scope_score
            + 0.05 * rate_score
            + 0.15 * social_score
            + 0.10 * repetition_score
            + 0.10 * min(1.0, n / 20)  # More data = more confidence in score
        )

        # Apply aggression trend boost
        if len(profile.aggression_scores) >= 5:
            recent_avg = sum(profile.aggression_scores[-5:]) / 5
            raw_score += recent_avg * 0.15

        raw_score = round(min(1.0, raw_score), 4)

        # Update profile
        profile.risk_score = raw_score
        profile.risk_level = self._classify_risk(raw_score)
        profile.risk_history.append(raw_score)
        if len(profile.risk_history) > 50:
            profile.risk_history = profile.risk_history[-50:]

        return raw_score

    def is_adversarial(self, user_id: str) -> bool:
        """
        Determine if a user is likely adversarial.

        Returns True if risk score >= 0.6 (HIGH or CRITICAL).
        """
        score = self.get_user_risk_score(user_id)
        return score >= 0.6

    def get_risk_history(self, user_id: str) -> Dict[str, Any]:
        """Get risk score history and trend for a user."""
        if user_id not in self._profiles:
            return {
                "user_id": user_id,
                "risk_score": 0.0,
                "risk_level": "low",
                "history": [],
                "trend": "stable",
            }

        profile = self._profiles[user_id]
        history = profile.risk_history

        # Determine trend
        trend = "stable"
        if len(history) >= 4:
            mid = len(history) // 2
            first_avg = sum(history[:mid]) / mid if mid > 0 else 0
            second_avg = sum(history[mid:]) / (len(history) - mid) if (len(history) - mid) > 0 else 0
            delta = second_avg - first_avg
            if delta > 0.05:
                trend = "increasing"
            elif delta < -0.05:
                trend = "decreasing"

        return {
            "user_id": user_id,
            "risk_score": profile.risk_score,
            "risk_level": profile.risk_level,
            "history": history[-50:],
            "trend": trend,
            "total_requests": profile.total_requests,
        }

    def get_user_profile(self, user_id: str) -> Optional[UserBehaviorProfile]:
        """Get the behavior profile for a user."""
        return self._profiles.get(user_id)

    def get_all_profiles(self) -> List[UserBehaviorProfile]:
        """Get all user behavior profiles."""
        return list(self._profiles.values())

    def list_users(self) -> List[Dict[str, Any]]:
        """List all tracked users with their risk scores."""
        result = []
        for uid, profile in self._profiles.items():
            # Ensure risk score is up-to-date
            self.get_user_risk_score(uid)
            result.append(profile.to_dict())
        # Sort by risk score descending
        result.sort(key=lambda x: x["risk_score"], reverse=True)
        return result

    @staticmethod
    def _classify_risk(score: float) -> str:
        """Classify a risk score into a RiskLevel."""
        if score < 0.3:
            return RiskLevel.LOW.value
        elif score < 0.6:
            return RiskLevel.MODERATE.value
        elif score < 0.85:
            return RiskLevel.HIGH.value
        else:
            return RiskLevel.CRITICAL.value


# ─── Convenience ───────────────────────────────────────────────────


def get_tracker(
    rate_window: int = RATE_WINDOW_SECONDS,
    rate_burst_threshold: int = RATE_BURST_THRESHOLD,
) -> UserBehaviorTracker:
    """Get a configured UserBehaviorTracker instance."""
    return UserBehaviorTracker(
        rate_window=rate_window,
        rate_burst_threshold=rate_burst_threshold,
    )
