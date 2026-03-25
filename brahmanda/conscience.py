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
    AnomalyType, MIN_INTERACTIONS_FOR_BASELINE,
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


# ─── Conscience Monitor ──────────────────────────────────────────


class ConscienceMonitor:
    """
    Main orchestrator for behavioral profiling and anomaly detection.

    Maintains persistent agent/session/user profiles in SQLite.
    Provides health scores, drift detection, and anomaly alerts.
    """

    def __init__(self, db_path: Optional[str] = None, in_memory: bool = False):
        """
        Args:
            db_path: Path to SQLite database file. Default: data/conscience.db
            in_memory: If True, use in-memory SQLite (for testing).
        """
        if in_memory:
            self._db_path = ":memory:"
        else:
            self._db_path = db_path or os.path.join("data", "conscience.db")
            db_dir = os.path.dirname(self._db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir, exist_ok=True)

        # For in-memory SQLite, keep a persistent connection so schema survives
        self._mem_conn = None
        if self._db_path == ":memory:":
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
            self._mem_conn.executescript(SCHEMA_SQL)

        self._init_db()

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


def get_monitor(in_memory: bool = False, db_path: Optional[str] = None) -> ConscienceMonitor:
    """Get a configured ConscienceMonitor instance."""
    return ConscienceMonitor(db_path=db_path, in_memory=in_memory)
