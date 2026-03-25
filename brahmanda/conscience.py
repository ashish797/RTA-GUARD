"""
RTA-GUARD — Conscience Monitor (Phase 3.1)

Behavioral monitoring orchestrator for AI agents.
Tracks agent behavior across sessions, detects anomalies,
calculates drift, and maintains persistent profiles via SQLite.

Usage:
    monitor = ConscienceMonitor()
    monitor.register_agent("agent-001")
    monitor.record_interaction("agent-001", "sess-abc", verification_result)
    health = monitor.get_agent_health("agent-001")
"""
import json
import os
import sqlite3
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Tuple
from pathlib import Path
from contextlib import contextmanager

from .profiles import (
    AgentProfile, SessionProfile, UserProfile,
    AnomalyType, DriftLevel, DriftComponents,
    classify_drift, MIN_INTERACTIONS_FOR_BASELINE,
)

from .tamas import (
    TamasDetector, TamasState, TamasEvent, TamasStore,
    EscalationAction,
)

from .temporal import (
    TemporalConsistencyChecker,
    ConsistencyLevel,
    classify_consistency,
    ContradictionPair,
)

from .escalation import (
    EscalationChain,
    EscalationLevel,
    EscalationDecision,
    EscalationConfig,
)

logger = logging.getLogger(__name__)

# ─── Database helpers ──────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_profiles (
    agent_id TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session_profiles (
    session_id TEXT PRIMARY KEY,
    agent_id TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_profiles (
    user_id TEXT PRIMARY KEY,
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_session_agent ON session_profiles(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_updated ON agent_profiles(updated_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── Behavioral Baseline ──────────────────────────────────────────


@dataclass
class BehavioralBaseline:
    """
    Statistical baseline from historical agent data.

    Computed from the agent's own history — the "normal" behavior
    to compare current behavior against.
    """
    agent_id: str = ""
    baseline_confidence: float = 1.0
    baseline_violation_rate: float = 0.0
    baseline_accuracy: float = 1.0
    baseline_drift: float = 0.0
    sample_count: int = 0
    computed_at: str = ""

    @classmethod
    def from_profile(cls, profile: AgentProfile) -> "BehavioralBaseline":
        """Build baseline from an agent profile's history."""
        if len(profile.confidence_history) < MIN_INTERACTIONS_FOR_BASELINE:
            return cls(
                agent_id=profile.agent_id,
                sample_count=len(profile.confidence_history),
                computed_at=_now(),
            )

        history = profile.confidence_history
        # Use first 60% of history as baseline, last 40% as current
        split_idx = max(1, int(len(history) * 0.6))
        baseline_confs = history[:split_idx]

        return cls(
            agent_id=profile.agent_id,
            baseline_confidence=sum(baseline_confs) / len(baseline_confs),
            baseline_violation_rate=profile.violation_rate,
            baseline_accuracy=profile.claim_accuracy,
            baseline_drift=profile.drift_score,
            sample_count=len(baseline_confs),
            computed_at=_now(),
        )

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "baseline_confidence": round(self.baseline_confidence, 4),
            "baseline_violation_rate": round(self.baseline_violation_rate, 4),
            "baseline_accuracy": round(self.baseline_accuracy, 4),
            "baseline_drift": round(self.baseline_drift, 4),
            "sample_count": self.sample_count,
            "computed_at": self.computed_at,
        }


# ─── Live Drift Scorer (Phase 3.2) ────────────────────────────────


@dataclass
class DriftSnapshot:
    """A point-in-time drift measurement for an interaction."""
    session_id: str = ""
    agent_id: str = ""
    timestamp: str = ""
    components: DriftComponents = field(default_factory=DriftComponents)
    weighted_score: float = 0.0
    level: DriftLevel = DriftLevel.HEALTHY

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "timestamp": self.timestamp,
            "components": self.components.to_dict(),
            "weighted_score": self.weighted_score,
            "level": self.level.value,
        }


class LiveDriftScorer:
    """
    Continuous, live drift scoring that updates in real-time.

    Uses a sliding window of the last N interactions and exponential
    moving average (EMA) for smooth drift tracking. Integrated with
    ConscienceMonitor so each interaction updates drift scores.

    Drift components mirror the AnRtaDriftRule (R11):
        - D_semantic:    0.30 weight — output pattern variance
        - D_alignment:   0.25 weight — temporal consistency
        - D_scope:       0.20 weight — capability boundary proximity
        - D_confidence:  0.15 weight — confidence-verifiability gap
        - D_rule_proximity: 0.10 weight — proximity to violation thresholds

    Thresholds:
        HEALTHY:   < 0.15
        DEGRADED:  0.15 – 0.35
        UNHEALTHY: 0.35 – 0.60
        CRITICAL:  > 0.60
    """

    DEFAULT_WINDOW_SIZE = 20
    DEFAULT_EMA_ALPHA = 0.3

    def __init__(
        self,
        window_size: int = DEFAULT_WINDOW_SIZE,
        ema_alpha: float = DEFAULT_EMA_ALPHA,
    ):
        self.window_size = window_size
        self.ema_alpha = ema_alpha
        # Per-agent drift history: agent_id -> list of DriftSnapshot
        self._agent_snapshots: Dict[str, List[DriftSnapshot]] = {}
        # Per-session drift history: session_id -> list of DriftSnapshot
        self._session_snapshots: Dict[str, List[DriftSnapshot]] = {}
        # Per-agent EMA state
        self._agent_ema: Dict[str, float] = {}
        # Track which agent owns which session
        self._session_agents: Dict[str, str] = {}

    def record_drift(
        self,
        agent_id: str,
        session_id: str,
        components: DriftComponents | Dict[str, float],
    ) -> DriftSnapshot:
        """
        Record a drift measurement for an interaction.

        Call this after each verification to update live drift state.
        Accepts either a DriftComponents object or a dict with component values.
        Returns the resulting DriftSnapshot.
        """
        self._session_agents[session_id] = agent_id
        timestamp = _now()

        # Normalize to DriftComponents
        if isinstance(components, dict):
            components = DriftComponents(
                semantic=components.get("semantic", 0.0),
                alignment=components.get("alignment", 0.0),
                scope=components.get("scope", 0.0),
                confidence=components.get("confidence", 0.0),
                rule_proximity=components.get("rule_proximity", 0.0),
            )

        weighted = components.weighted_score()
        level = classify_drift(weighted)

        snapshot = DriftSnapshot(
            session_id=session_id,
            agent_id=agent_id,
            timestamp=timestamp,
            components=components,
            weighted_score=weighted,
            level=level,
        )

        # Store in agent history (sliding window)
        if agent_id not in self._agent_snapshots:
            self._agent_snapshots[agent_id] = []
        self._agent_snapshots[agent_id].append(snapshot)
        if len(self._agent_snapshots[agent_id]) > self.window_size:
            self._agent_snapshots[agent_id] = self._agent_snapshots[agent_id][-self.window_size:]

        # Store in session history
        if session_id not in self._session_snapshots:
            self._session_snapshots[session_id] = []
        self._session_snapshots[session_id].append(snapshot)

        # Update EMA
        prev_ema = self._agent_ema.get(agent_id, 0.0)
        new_ema = self.ema_alpha * weighted + (1 - self.ema_alpha) * prev_ema
        self._agent_ema[agent_id] = round(new_ema, 4)

        return snapshot

    def calculate_session_drift(self, session_id: str) -> Dict[str, Any]:
        """
        Get the real-time drift score for the current session.

        Returns the latest snapshot's data plus session-level aggregates.
        """
        snapshots = self._session_snapshots.get(session_id, [])
        if not snapshots:
            return {
                "session_id": session_id,
                "error": "No drift data for this session",
                "drift_score": 0.0,
                "level": DriftLevel.HEALTHY.value,
            }

        latest = snapshots[-1]
        agent_id = self._session_agents.get(session_id, latest.agent_id)

        # Session EMA from session-local snapshots
        session_scores = [s.weighted_score for s in snapshots]
        session_ema = session_scores[-1]
        if len(session_scores) > 1:
            ema = 0.0
            for s in session_scores:
                ema = self.ema_alpha * s + (1 - self.ema_alpha) * ema
            session_ema = round(ema, 4)

        return {
            "session_id": session_id,
            "agent_id": agent_id,
            "drift_score": latest.weighted_score,
            "smoothed_score": session_ema,
            "level": latest.level.value,
            "components": latest.components.to_dict(),
            "snapshot_count": len(snapshots),
            "first_snapshot": snapshots[0].timestamp if snapshots else None,
            "last_snapshot": latest.timestamp,
        }

    def calculate_agent_drift(self, agent_id: str) -> Dict[str, Any]:
        """
        Get accumulated drift across all sessions for an agent.

        Uses EMA-smoothed score from the sliding window.
        """
        snapshots = self._agent_snapshots.get(agent_id, [])
        if not snapshots:
            return {
                "agent_id": agent_id,
                "error": "No drift data for this agent",
                "drift_score": 0.0,
                "level": DriftLevel.HEALTHY.value,
            }

        ema_score = self._agent_ema.get(agent_id, 0.0)
        level = classify_drift(ema_score)

        # Average components across window
        avg_components = self._average_components(snapshots)

        # Session breakdown
        session_ids = list(set(s.session_id for s in snapshots))
        session_scores = {}
        for sid in session_ids:
            sess_snaps = [s for s in snapshots if s.session_id == sid]
            if sess_snaps:
                session_scores[sid] = sess_snaps[-1].weighted_score

        return {
            "agent_id": agent_id,
            "drift_score": ema_score,
            "level": level.value,
            "components": avg_components.to_dict(),
            "snapshot_count": len(snapshots),
            "sessions_tracked": len(session_ids),
            "session_scores": session_scores,
            "trend": self.get_drift_trend(agent_id),
        }

    def get_drift_trend(self, agent_id: str) -> str:
        """
        Determine if drift is increasing, stable, or decreasing.

        Compares first half of sliding window to second half.
        """
        snapshots = self._agent_snapshots.get(agent_id, [])
        if len(snapshots) < 4:
            return "stable"

        scores = [s.weighted_score for s in snapshots]
        mid = len(scores) // 2
        first_half_avg = sum(scores[:mid]) / mid
        second_half_avg = sum(scores[mid:]) / (len(scores) - mid)

        delta = second_half_avg - first_half_avg
        if delta > 0.05:
            return "increasing"
        elif delta < -0.05:
            return "decreasing"
        return "stable"

    def get_drift_components(self, agent_id: str) -> Dict[str, Any]:
        """
        Get the breakdown of the 5 drift components for an agent.

        Averages across the sliding window for each component.
        """
        snapshots = self._agent_snapshots.get(agent_id, [])
        if not snapshots:
            return {
                "agent_id": agent_id,
                "error": "No drift data",
                "components": DriftComponents().to_dict(),
            }

        avg = self._average_components(snapshots)
        latest = snapshots[-1].components

        return {
            "agent_id": agent_id,
            "latest": latest.to_dict(),
            "window_average": avg.to_dict(),
            "snapshot_count": len(snapshots),
            "level": classify_drift(avg.weighted_score()).value,
            "trend": self.get_drift_trend(agent_id),
        }

    def get_drift_level(self, agent_id: str) -> DriftLevel:
        """Get the current drift level for an agent."""
        ema = self._agent_ema.get(agent_id, 0.0)
        return classify_drift(ema)

    def _average_components(self, snapshots: List[DriftSnapshot]) -> DriftComponents:
        """Average drift components across a list of snapshots."""
        if not snapshots:
            return DriftComponents()

        n = len(snapshots)
        return DriftComponents(
            semantic=sum(s.components.semantic for s in snapshots) / n,
            alignment=sum(s.components.alignment for s in snapshots) / n,
            scope=sum(s.components.scope for s in snapshots) / n,
            confidence=sum(s.components.confidence for s in snapshots) / n,
            rule_proximity=sum(s.components.rule_proximity for s in snapshots) / n,
        )


# ─── Conscience Monitor ──────────────────────────────────────────


class ConscienceMonitor:
    """
    Main orchestrator for behavioral profiling and anomaly detection.

    Maintains persistent agent/session/user profiles in SQLite.
    Provides health scores, drift detection, and anomaly alerts.
    Integrates LiveDriftScorer (Phase 3.2) for continuous drift monitoring.
    """

    def __init__(self, db_path: Optional[str] = None, in_memory: bool = False,
                 drift_window: int = 20, drift_ema_alpha: float = 0.3,
                 tenant_context: Optional[Any] = None):
        """
        Args:
            db_path: Path to SQLite database file. Default: data/conscience.db
            in_memory: If True, use in-memory SQLite (for testing).
            tenant_context: TenantContext for multi-tenant isolation.
                           If provided, db_path is derived from tenant_context.conscience_db_path.
        """
        if in_memory:
            self._db_path = ":memory:"
        elif tenant_context is not None:
            # Multi-tenant mode: use tenant-isolated database
            self._db_path = tenant_context.conscience_db_path
            db_dir = os.path.dirname(self._db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
        else:
            self._db_path = db_path or os.path.join("data", "conscience.db")
            db_dir = os.path.dirname(self._db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)
        self._tenant_context = tenant_context

        # For in-memory SQLite, keep a persistent connection so schema survives
        self._mem_conn = None
        if self._db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
            self._mem_conn.executescript(SCHEMA_SQL)

        # Live drift scorer (Phase 3.2)
        self.drift_scorer = LiveDriftScorer(
            window_size=drift_window,
            ema_alpha=drift_ema_alpha,
        )

        # Tamas detector (Phase 3.3)
        self.tamas_detector = TamasDetector()

        # Temporal consistency checker (Phase 3.4)
        self.temporal_checker = TemporalConsistencyChecker()

        # Escalation chain (Phase 3.6)
        self.escalation_chain = EscalationChain()

        self._init_db()

        # Tamas store (needs persistent connection)
        if self._mem_conn:
            self._tamas_store = TamasStore(self._mem_conn)
        else:
            self._tamas_store = None  # Lazy init in _conn()

    def _init_db(self):
        """Initialize SQLite database with schema."""
        with self._conn() as conn:
            conn.executescript(SCHEMA_SQL)

    @contextmanager
    def _conn(self):
        """Context manager for database connections."""
        if self._mem_conn:
            yield self._mem_conn
            self._mem_conn.commit()
        else:
            conn = sqlite3.connect(self._db_path)
            conn.row_factory = sqlite3.Row
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    # ── Agent Management ──────────────────────────────────────────

    def register_agent(self, agent_id: str) -> AgentProfile:
        """Create a new agent profile or return existing one."""
        existing = self._load_agent(agent_id)
        if existing:
            return existing

        profile = AgentProfile(agent_id=agent_id)
        self._save_agent(profile)
        logger.info(f"Registered new agent: {agent_id}")
        return profile

    def _load_agent(self, agent_id: str) -> Optional[AgentProfile]:
        """Load an agent profile from SQLite."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT profile_json FROM agent_profiles WHERE agent_id = ?",
                (agent_id,),
            ).fetchone()

        if not row:
            return None

        data = json.loads(row["profile_json"])
        # Remove computed fields not in AgentProfile constructor
        data.pop("health_score", None)
        data.pop("confidence_history_len", None)
        data.pop("drift_history_len", None)  # Phase 3.2 computed field
        return AgentProfile(**data)

    def _save_agent(self, profile: AgentProfile):
        """Persist an agent profile to SQLite."""
        now = _now()
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO agent_profiles
                   (agent_id, profile_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (profile.agent_id, json.dumps(profile.to_dict()), now, now),
            )

    def _load_session(self, session_id: str) -> Optional[SessionProfile]:
        """Load a session profile from SQLite."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT profile_json FROM session_profiles WHERE session_id = ?",
                (session_id,),
            ).fetchone()

        if not row:
            return None

        data = json.loads(row["profile_json"])
        # Remove computed fields not in constructor
        data.pop("session_drift", None)
        data.pop("session_health", None)
        data.pop("confidence_timeline_len", None)
        return SessionProfile(**data)

    def _save_session(self, profile: SessionProfile):
        """Persist a session profile to SQLite."""
        now = _now()
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO session_profiles
                   (session_id, agent_id, profile_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (profile.session_id, profile.agent_id, json.dumps(profile.to_dict()), now, now),
            )

    def _load_user(self, user_id: str) -> Optional[UserProfile]:
        """Load a user profile from SQLite."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT profile_json FROM user_profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()

        if not row:
            return None

        data = json.loads(row["profile_json"])
        return UserProfile(**data)

    def _save_user(self, profile: UserProfile):
        """Persist a user profile to SQLite."""
        now = _now()
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO user_profiles
                   (user_id, profile_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (profile.user_id, json.dumps(profile.to_dict()), now, now),
            )

    # ── Core Recording ────────────────────────────────────────────

    def record_interaction(
        self,
        agent_id: str,
        session_id: str,
        verification_result: Any,  # VerifyResult or PipelineResult
        user_id: str = "",
        violation: bool = False,
        violation_type: str = "",
        violation_severity: float = 1.0,
        domain: str = "general",
    ):
        """
        Record an interaction from a verification result.

        Updates agent, session, and (optionally) user profiles.
        Call this after every BrahmandaVerifier.verify() or pipeline verification.
        """
        # Extract confidence from verification result
        confidence = self._extract_confidence(verification_result)
        claims_verified, claims_total = self._extract_claim_counts(verification_result)

        # Ensure agent exists
        agent = self.register_agent(agent_id)

        # Update agent profile
        agent.update_from_verification(
            confidence=confidence,
            claims_verified=claims_verified,
            claims_total=claims_total,
            domain=domain,
        )
        if violation:
            agent.update_from_violation(
                violation_type=violation_type,
                severity=violation_severity,
                domain=domain,
            )
        self._save_agent(agent)

        # Update or create session profile
        session = self._load_session(session_id)
        if not session:
            session = SessionProfile(
                session_id=session_id,
                agent_id=agent_id,
                user_id=user_id,
            )

        session.update_from_verification(
            confidence=confidence,
            claims_verified=claims_verified,
            claims_total=claims_total,
            domain=domain,
        )
        if violation:
            session.update_from_violation(domain=domain)
        self._save_session(session)

        # Update user profile if user_id provided
        if user_id:
            user = self._load_user(user_id)
            if not user:
                user = UserProfile(user_id=user_id)
            user.update_from_session(session)
            self._save_user(user)

        # Tamas detection (Phase 3.3)
        self._evaluate_tamas(agent_id, agent)

        # Temporal consistency check (Phase 3.4)
        self._evaluate_temporal(agent_id, verification_result)

    def _extract_confidence(self, result: Any) -> float:
        """Extract confidence score from a verification result."""
        # PipelineResult or VerifyResult
        if hasattr(result, "overall_confidence"):
            return result.overall_confidence
        if hasattr(result, "confidence"):
            return result.confidence
        if isinstance(result, dict):
            return result.get("overall_confidence", result.get("confidence", 0.5))
        return 0.5

    def _extract_claim_counts(self, result: Any) -> Tuple[int, int]:
        """Extract (verified, total) claim counts from a verification result."""
        if hasattr(result, "claims"):
            claims = result.claims
            if isinstance(claims, list):
                total = len(claims)
                verified = 0
                for c in claims:
                    if hasattr(c, "verified"):
                        if c.verified:
                            verified += 1
                    elif hasattr(c, "contradicted"):
                        if not c.contradicted and hasattr(c, "matched_fact") and c.matched_fact:
                            verified += 1
                    elif isinstance(c, dict):
                        if c.get("verified") or (not c.get("contradicted") and c.get("matched_fact")):
                            verified += 1
                return verified, total

        if hasattr(result, "claim_count"):
            passed = getattr(result, "passed_count", 0)
            return passed, result.claim_count

        return 1, 1

    # ── Health & Anomaly Queries ──────────────────────────────────

    def get_agent_health(self, agent_id: str) -> Dict[str, Any]:
        """
        Get current health score and status for an agent.

        Returns dict with health_score, profile summary, and anomaly status.
        """
        agent = self._load_agent(agent_id)
        if not agent:
            return {
                "agent_id": agent_id,
                "error": "Agent not registered",
                "health_score": None,
            }

        is_anomalous, anomaly_type, anomaly_detail = agent.is_anomalous()

        return {
            "agent_id": agent_id,
            "health_score": agent.get_score(),
            "avg_confidence": round(agent.avg_confidence, 4),
            "violation_rate": round(agent.violation_rate, 4),
            "claim_accuracy": round(agent.claim_accuracy, 4),
            "drift_score": round(agent.drift_score, 4),
            "interaction_count": agent.interaction_count,
            "domains_seen": agent.domains_seen,
            "is_anomalous": is_anomalous,
            "anomaly_type": anomaly_type.value if is_anomalous else "none",
            "anomaly_detail": anomaly_detail,
            "last_seen": agent.last_seen,
        }

    def detect_anomaly(self, agent_id: str) -> Tuple[bool, AnomalyType, str]:
        """
        Compare agent's current behavior to its historical baseline.

        Returns (is_anomalous, anomaly_type, detail_string).
        """
        agent = self._load_agent(agent_id)
        if not agent:
            return False, AnomalyType.NONE, "Agent not found"

        baseline = BehavioralBaseline.from_profile(agent)
        return agent.is_anomalous(baseline)

    def get_session_drift(self, agent_id: str, session_id: str) -> Dict[str, Any]:
        """
        Get drift metrics for a specific session.

        Compares session behavior to agent's overall profile.
        """
        session = self._load_session(session_id)
        if not session or session.agent_id != agent_id:
            return {
                "session_id": session_id,
                "agent_id": agent_id,
                "error": "Session not found or agent mismatch",
            }

        agent = self._load_agent(agent_id)
        agent_health = agent.get_score() if agent else 1.0

        session_drift = session.get_drift()
        session_health = session.get_health()

        # Compare session to agent baseline
        confidence_delta = 0.0
        if agent:
            confidence_delta = session.avg_confidence - agent.avg_confidence

        return {
            "session_id": session_id,
            "agent_id": agent_id,
            "session_drift": session_drift,
            "session_health": session_health,
            "agent_health": agent_health,
            "confidence_delta": round(confidence_delta, 4),
            "interaction_count": session.interaction_count,
            "violation_count": session.violation_count,
            "avg_confidence": round(session.avg_confidence, 4),
            "domains_seen": session.domains_seen,
            "is_degrading": confidence_delta < -0.1,
        }

    # ── Live Drift (Phase 3.2) ──────────────────────────────────

    def record_drift(
        self,
        agent_id: str,
        session_id: str,
        components: Dict[str, float],
    ) -> Dict[str, Any]:
        """
        Record a live drift measurement for an interaction.

        Args:
            agent_id: The agent identifier.
            session_id: The session identifier.
            components: Dict with keys: semantic, alignment, scope, confidence, rule_proximity.

        Returns the drift snapshot with score and level.
        """
        drift_comp = DriftComponents(
            semantic=components.get("semantic", 0.0),
            alignment=components.get("alignment", 0.0),
            scope=components.get("scope", 0.0),
            confidence=components.get("confidence", 0.0),
            rule_proximity=components.get("rule_proximity", 0.0),
        )

        snapshot = self.drift_scorer.record_drift(agent_id, session_id, drift_comp)

        # Update agent profile's live drift fields
        agent = self._load_agent(agent_id)
        if agent:
            agent.live_drift_score = self.drift_scorer._agent_ema.get(agent_id, 0.0)
            agent.live_drift_level = snapshot.level.value
            agent.drift_components = drift_comp.to_dict()
            agent.drift_trend = self.drift_scorer.get_drift_trend(agent_id)
            agent.drift_history.append(snapshot.weighted_score)
            if len(agent.drift_history) > 50:
                agent.drift_history = agent.drift_history[-50:]
            self._save_agent(agent)

        return snapshot.to_dict()

    def get_live_drift(self, agent_id: str) -> Dict[str, Any]:
        """Get the current live drift state for an agent."""
        return self.drift_scorer.calculate_agent_drift(agent_id)

    def get_live_drift_session(self, session_id: str) -> Dict[str, Any]:
        """Get the current live drift state for a session."""
        return self.drift_scorer.calculate_session_drift(session_id)

    def get_drift_trend(self, agent_id: str) -> str:
        """Get drift trend: increasing, stable, or decreasing."""
        return self.drift_scorer.get_drift_trend(agent_id)

    def get_drift_components(self, agent_id: str) -> Dict[str, Any]:
        """Get drift component breakdown for an agent."""
        return self.drift_scorer.get_drift_components(agent_id)

    # ── Tamas Detection (Phase 3.3) ──────────────────────────────

    def _evaluate_tamas(self, agent_id: str, agent: AgentProfile):
        """Evaluate Tamas state for an agent after an interaction."""
        old_state = self.tamas_detector.get_current_state(agent_id)
        new_state = self.tamas_detector.evaluate_agent(agent_id, agent)

        # Persist events if transition occurred
        if new_state != old_state:
            events = self.tamas_detector._agent_events.get(agent_id, [])
            if events:
                latest_event = events[-1]
                if self._tamas_store:
                    self._tamas_store.save_event(latest_event)

    def get_tamas_state(self, agent_id: str) -> Dict[str, Any]:
        """Get current Tamas state for an agent."""
        return self.tamas_detector.get_tamas_summary(agent_id)

    def get_tamas_history(self, agent_id: str) -> List[Dict[str, Any]]:
        """Get Tamas event history for an agent."""
        events = self.tamas_detector.get_tamas_history(agent_id)
        if self._tamas_store:
            db_events = self._tamas_store.get_events(agent_id)
            # Merge in-memory and db events (dedupe by event_id)
            seen_ids = {e["event_id"] for e in events}
            for e in db_events:
                if e["event_id"] not in seen_ids:
                    events.append(e)
                    seen_ids.add(e["event_id"])
        return sorted(events, key=lambda e: e["timestamp"])

    def get_recovery_score(self, agent_id: str) -> Dict[str, Any]:
        """Get recovery score for an agent."""
        return {
            "agent_id": agent_id,
            "recovery_score": self.tamas_detector.get_recovery_score(agent_id),
            "current_state": self.tamas_detector.get_current_state(agent_id).value,
        }

    # ── Temporal Consistency (Phase 3.4) ─────────────────────────

    def _evaluate_temporal(self, agent_id: str, verification_result: Any):
        """
        Extract claims from a verification result and add them to
        the temporal consistency checker.

        Feeds the consistency score into the agent's drift calculation
        by updating the alignment drift component.
        """
        claims = self._extract_temporal_claims(verification_result)
        for claim_text in claims:
            self.temporal_checker.add_statement(
                agent_id=agent_id,
                claim=claim_text,
                confidence=self._extract_confidence(verification_result),
                source="verification",
            )

        # Update agent's alignment drift component with temporal consistency
        agent = self._load_agent(agent_id)
        if agent and agent.interaction_count > 0:
            consistency_score = self.temporal_checker.get_consistency_score(agent_id)
            # Alignment drift = 1 - consistency (high consistency = low drift)
            alignment_drift = round(1.0 - consistency_score, 4)
            if agent.drift_components:
                agent.drift_components["alignment"] = alignment_drift
            else:
                agent.drift_components = {"alignment": alignment_drift}
            self._save_agent(agent)

    def _extract_temporal_claims(self, result: Any) -> List[str]:
        """Extract claim texts from a verification result for temporal tracking."""
        claims = []
        if hasattr(result, "claims"):
            result_claims = result.claims
            if isinstance(result_claims, list):
                for c in result_claims:
                    if hasattr(c, "claim"):
                        claims.append(c.claim)
                    elif isinstance(c, dict) and "claim" in c:
                        claims.append(c["claim"])
        elif hasattr(result, "text"):
            claims.append(result.text)
        elif isinstance(result, dict):
            if "claims" in result:
                for c in result["claims"]:
                    if isinstance(c, dict) and "claim" in c:
                        claims.append(c["claim"])
            elif "text" in result:
                claims.append(result["text"])
        return claims

    def get_temporal_consistency(self, agent_id: str) -> Dict[str, Any]:
        """Get temporal consistency summary for an agent."""
        return self.temporal_checker.get_temporal_summary(agent_id)

    def check_temporal_consistency(
        self,
        agent_id: str,
        claim: str,
        confidence: float = 1.0,
    ) -> Dict[str, Any]:
        """
        Pre-flight check: test a claim against an agent's history
        WITHOUT adding it. Returns contradictions if found.
        """
        contradictions = self.temporal_checker.check_consistency(
            agent_id, claim, confidence
        )
        return {
            "agent_id": agent_id,
            "claim": claim,
            "contradictions": [c.to_dict() for c in contradictions],
            "consistency_score": self.temporal_checker.get_consistency_score(agent_id),
            "consistency_level": self.temporal_checker.get_consistency_level(agent_id).value,
        }

    def get_contradiction_history(self, agent_id: str) -> Dict[str, Any]:
        """Get all temporal contradictions for an agent."""
        return {
            "agent_id": agent_id,
            "contradictions": self.temporal_checker.get_contradiction_history(agent_id),
            "total": self.temporal_checker.get_contradiction_count(agent_id),
        }

    # ── Escalation (Phase 3.6) ──────────────────────────────────

    def evaluate_escalation(
        self,
        agent_id: str,
        session_id: str = "",
        user_risk_score: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Unified escalation evaluation combining all signals from Phase 3.

        Aggregates drift, Tamas, temporal consistency, user risk, and
        violation rate into a single EscalationDecision.

        Args:
            agent_id: The agent to evaluate.
            session_id: The current session (optional).
            user_risk_score: User behavior risk score (0.0-1.0).

        Returns:
            Dict with escalation decision details.
        """
        # Gather signals from all subsystems
        agent = self._load_agent(agent_id)
        drift_score = 0.0
        violation_rate = 0.0
        if agent:
            drift_score = agent.live_drift_score or agent.drift_score
            violation_rate = agent.violation_rate

        tamas_state = self.tamas_detector.get_current_state(agent_id).value
        consistency_level = self.temporal_checker.get_consistency_level(agent_id).value

        signals = EscalationChain.build_signals(
            drift_score=drift_score,
            tamas_state=tamas_state,
            consistency_level=consistency_level,
            user_risk_score=user_risk_score,
            violation_rate=violation_rate,
        )

        decision = self.escalation_chain.evaluate(
            signals, session_id=session_id, agent_id=agent_id
        )

        # Execute handlers if escalated
        if decision.level > EscalationLevel.OBSERVE:
            self.escalation_chain.execute(decision)

        return decision.to_dict()

    # ── Listing ───────────────────────────────────────────────────

    def list_agents(self) -> List[Dict[str, Any]]:
        """List all registered agents with their health scores."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT agent_id, profile_json FROM agent_profiles ORDER BY updated_at DESC"
            ).fetchall()

        agents = []
        for row in rows:
            data = json.loads(row["profile_json"])
            data.pop("health_score", None)
            data.pop("confidence_history_len", None)
            data.pop("drift_history_len", None)  # Phase 3.2 computed field
            data["health_score"] = AgentProfile(**data).get_score()
            agents.append(data)
        return agents

    def list_sessions(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List session profiles, optionally filtered by agent_id."""
        with self._conn() as conn:
            if agent_id:
                rows = conn.execute(
                    "SELECT session_id, profile_json FROM session_profiles WHERE agent_id = ? ORDER BY updated_at DESC",
                    (agent_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT session_id, profile_json FROM session_profiles ORDER BY updated_at DESC"
                ).fetchall()

        sessions = []
        for row in rows:
            data = json.loads(row["profile_json"])
            sessions.append(data)
        return sessions

    def list_users(self) -> List[Dict[str, Any]]:
        """List all user profiles."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT user_id, profile_json FROM user_profiles ORDER BY updated_at DESC"
            ).fetchall()

        users = []
        for row in rows:
            data = json.loads(row["profile_json"])
            users.append(data)
        return users


# ── Convenience ───────────────────────────────────────────────────


def get_monitor(in_memory: bool = False, db_path: Optional[str] = None,
                tenant_context: Optional[Any] = None) -> ConscienceMonitor:
    """Get a configured ConscienceMonitor instance."""
    return ConscienceMonitor(db_path=db_path, in_memory=in_memory, tenant_context=tenant_context)
