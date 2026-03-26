"""
RTA-GUARD — SLA Monitoring System (Phase 4.8)

Tracks service-level metrics: uptime, response time, kill rate, false positive
rate, mean time to detect. SQLite persistence. Alerts on SLA breaches.
"""

import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class SLAStatus(Enum):
    """Status of an SLA metric relative to its threshold."""
    WITHIN = "within"
    BREACHED = "breached"
    UNKNOWN = "unknown"


@dataclass
class SLAMetric:
    """A single SLA metric reading."""
    name: str
    value: float
    threshold: float
    threshold_direction: str  # "below" means value should be < threshold; "above" means value should be > threshold
    status: str  # "within" | "breached" | "unknown"
    unit: str = ""
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if self.status not in ("within", "breached", "unknown"):
            raise ValueError(f"Invalid status: {self.status}")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SLABreach:
    """Record of an SLA breach event."""
    breach_id: str
    metric_name: str
    value: float
    threshold: float
    timestamp: str
    details: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RequestRecord:
    """A recorded API request."""
    endpoint: str
    duration_ms: float
    status_code: int
    timestamp: str = ""
    record_id: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.record_id:
            self.record_id = str(uuid.uuid4())


@dataclass
class KillRecord:
    """A recorded kill event."""
    session_id: str
    reason: str
    detection_time_ms: float
    timestamp: str = ""
    is_false_positive: bool = False
    record_id: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if not self.record_id:
            self.record_id = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Default SLA thresholds
# ---------------------------------------------------------------------------

DEFAULT_SLA_THRESHOLDS = {
    "uptime_percentage": {"threshold": 99.9, "direction": "above", "unit": "%"},
    "avg_response_time_ms": {"threshold": 500.0, "direction": "below", "unit": "ms"},
    "kill_rate": {"threshold": 0.05, "direction": "below", "unit": "ratio"},
    "false_positive_rate": {"threshold": 0.01, "direction": "below", "unit": "ratio"},
    "mean_time_to_detect_ms": {"threshold": 1000.0, "direction": "below", "unit": "ms"},
    "api_availability": {"threshold": 99.9, "direction": "above", "unit": "%"},
}


# ---------------------------------------------------------------------------
# SLATracker
# ---------------------------------------------------------------------------

class SLATracker:
    """
    Collects and tracks SLA metrics with SQLite persistence.

    Metrics tracked:
    - Uptime percentage (target: 99.9%)
    - Average response time (target: <500ms)
    - Kill rate (violations per total requests)
    - False positive rate (kills that shouldn't have happened)
    - Mean time to detect (time from violation to kill)
    - API availability (uptime of dashboard)
    """

    def __init__(self, db_path: str = ":memory:", thresholds: Optional[Dict[str, dict]] = None):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._thresholds = thresholds or DEFAULT_SLA_THRESHOLDS
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    # -- Database -----------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if self._db_path == ":memory:":
            if self._conn is None:
                self._conn = sqlite3.connect(":memory:", check_same_thread=False)
                self._conn.row_factory = sqlite3.Row
                self._conn.execute("PRAGMA journal_mode=WAL")
            return self._conn
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _close_conn(self, conn: sqlite3.Connection):
        """Close a connection unless it's the shared in-memory connection."""
        if self._db_path != ":memory:":
            conn.close()

    def _init_db(self):
        with self._lock:
            conn = self._get_conn()
            try:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS sla_requests (
                        record_id TEXT PRIMARY KEY,
                        endpoint TEXT NOT NULL,
                        duration_ms REAL NOT NULL,
                        status_code INTEGER NOT NULL,
                        timestamp TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS sla_kills (
                        record_id TEXT PRIMARY KEY,
                        session_id TEXT NOT NULL,
                        reason TEXT NOT NULL,
                        detection_time_ms REAL NOT NULL,
                        is_false_positive INTEGER NOT NULL DEFAULT 0,
                        timestamp TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS sla_breaches (
                        breach_id TEXT PRIMARY KEY,
                        metric_name TEXT NOT NULL,
                        value REAL NOT NULL,
                        threshold REAL NOT NULL,
                        timestamp TEXT NOT NULL,
                        details TEXT DEFAULT ''
                    );
                    CREATE INDEX IF NOT EXISTS idx_requests_ts ON sla_requests(timestamp);
                    CREATE INDEX IF NOT EXISTS idx_kills_ts ON sla_kills(timestamp);
                    CREATE INDEX IF NOT EXISTS idx_breaches_ts ON sla_breaches(timestamp);
                    CREATE INDEX IF NOT EXISTS idx_breaches_name ON sla_breaches(metric_name);
                """)
                conn.commit()
            finally:
                self._close_conn(conn)

    # -- Recording ----------------------------------------------------------

    def record_request(self, endpoint: str, duration_ms: float, status_code: int,
                       timestamp: Optional[str] = None) -> str:
        """Log an API request. Returns record_id."""
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        record_id = str(uuid.uuid4())
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO sla_requests (record_id, endpoint, duration_ms, status_code, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (record_id, endpoint, duration_ms, status_code, ts),
                )
                conn.commit()
            finally:
                self._close_conn(conn)

        # Auto-check and record breach if response time breached
        self._check_response_time_breach(duration_ms, ts)
        return record_id

    def record_kill(self, session_id: str, reason: str, detection_time_ms: float,
                    is_false_positive: bool = False, timestamp: Optional[str] = None) -> str:
        """Log a kill event. Returns record_id."""
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        record_id = str(uuid.uuid4())
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO sla_kills (record_id, session_id, reason, detection_time_ms, is_false_positive, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                    (record_id, session_id, reason, detection_time_ms, 1 if is_false_positive else 0, ts),
                )
                conn.commit()
            finally:
                self._close_conn(conn)
        return record_id

    def _record_breach(self, metric_name: str, value: float, threshold: float,
                       details: str = "", timestamp: Optional[str] = None) -> str:
        """Record an SLA breach internally."""
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        breach_id = str(uuid.uuid4())
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute(
                    "INSERT INTO sla_breaches (breach_id, metric_name, value, threshold, timestamp, details) VALUES (?, ?, ?, ?, ?, ?)",
                    (breach_id, metric_name, value, threshold, ts, details),
                )
                conn.commit()
            finally:
                self._close_conn(conn)
        return breach_id

    def _check_response_time_breach(self, duration_ms: float, timestamp: str):
        """Check if a response time breaches SLA and record breach."""
        threshold = self._thresholds.get("avg_response_time_ms", {}).get("threshold", 500.0)
        if duration_ms > threshold:
            self._record_breach(
                "avg_response_time_ms", duration_ms, threshold,
                details=f"Response took {duration_ms:.1f}ms (threshold: {threshold:.0f}ms)",
                timestamp=timestamp,
            )

    # -- Querying -----------------------------------------------------------

    def get_sla_status(self) -> List[SLAMetric]:
        """
        Get current SLA status for all tracked metrics.

        Returns a list of SLAMetric with current values and breach status.
        """
        metrics = []

        # Uptime
        uptime = self.get_uptime_percentage()
        info = self._thresholds.get("uptime_percentage", {})
        metrics.append(SLAMetric(
            name="uptime_percentage",
            value=uptime,
            threshold=info.get("threshold", 99.9),
            threshold_direction=info.get("direction", "above"),
            status="within" if uptime >= info.get("threshold", 99.9) else "breached",
            unit=info.get("unit", "%"),
        ))

        # Avg response time
        avg_rt = self.get_avg_response_time()
        info = self._thresholds.get("avg_response_time_ms", {})
        metrics.append(SLAMetric(
            name="avg_response_time_ms",
            value=avg_rt,
            threshold=info.get("threshold", 500.0),
            threshold_direction=info.get("direction", "below"),
            status="within" if avg_rt <= info.get("threshold", 500.0) else "breached",
            unit=info.get("unit", "ms"),
        ))

        # Kill rate
        kill_rate = self.get_kill_rate()
        info = self._thresholds.get("kill_rate", {})
        metrics.append(SLAMetric(
            name="kill_rate",
            value=kill_rate,
            threshold=info.get("threshold", 0.05),
            threshold_direction=info.get("direction", "below"),
            status="within" if kill_rate <= info.get("threshold", 0.05) else "breached",
            unit=info.get("unit", "ratio"),
        ))

        # False positive rate
        fp_rate = self.get_false_positive_rate()
        info = self._thresholds.get("false_positive_rate", {})
        metrics.append(SLAMetric(
            name="false_positive_rate",
            value=fp_rate,
            threshold=info.get("threshold", 0.01),
            threshold_direction=info.get("direction", "below"),
            status="within" if fp_rate <= info.get("threshold", 0.01) else "breached",
            unit=info.get("unit", "ratio"),
        ))

        # Mean time to detect
        mttd = self.get_mean_time_to_detect()
        info = self._thresholds.get("mean_time_to_detect_ms", {})
        metrics.append(SLAMetric(
            name="mean_time_to_detect_ms",
            value=mttd,
            threshold=info.get("threshold", 1000.0),
            threshold_direction=info.get("direction", "below"),
            status="within" if mttd <= info.get("threshold", 1000.0) else "breached",
            unit=info.get("unit", "ms"),
        ))

        # API availability (same as uptime for now)
        api_avail = self.get_uptime_percentage()
        info = self._thresholds.get("api_availability", {})
        metrics.append(SLAMetric(
            name="api_availability",
            value=api_avail,
            threshold=info.get("threshold", 99.9),
            threshold_direction=info.get("direction", "above"),
            status="within" if api_avail >= info.get("threshold", 99.9) else "breached",
            unit=info.get("unit", "%"),
        ))

        return metrics

    def get_sla_breaches(self, from_date: Optional[str] = None,
                         to_date: Optional[str] = None) -> List[SLABreach]:
        """Get SLA breaches within a date range."""
        query = "SELECT breach_id, metric_name, value, threshold, timestamp, details FROM sla_breaches WHERE 1=1"
        params: list = []
        if from_date:
            query += " AND timestamp >= ?"
            params.append(from_date)
        if to_date:
            query += " AND timestamp <= ?"
            params.append(to_date)
        query += " ORDER BY timestamp DESC"

        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(query, params).fetchall()
            finally:
                self._close_conn(conn)

        return [
            SLABreach(
                breach_id=r["breach_id"],
                metric_name=r["metric_name"],
                value=r["value"],
                threshold=r["threshold"],
                timestamp=r["timestamp"],
                details=r["details"],
            )
            for r in rows
        ]

    def get_uptime_percentage(self) -> float:
        """
        Calculate uptime as percentage of successful (2xx) requests.

        Returns 100.0 if no requests recorded.
        """
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT COUNT(*) as total, SUM(CASE WHEN status_code BETWEEN 200 AND 299 THEN 1 ELSE 0 END) as success FROM sla_requests"
                ).fetchone()
            finally:
                self._close_conn(conn)

        total = row["total"]
        if total == 0:
            return 100.0
        return (row["success"] / total) * 100.0

    def get_avg_response_time(self) -> float:
        """
        Get average response time in milliseconds.

        Returns 0.0 if no requests recorded.
        """
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT AVG(duration_ms) as avg_rt FROM sla_requests"
                ).fetchone()
            finally:
                self._close_conn(conn)

        return row["avg_rt"] if row["avg_rt"] is not None else 0.0

    def get_kill_rate(self) -> float:
        """
        Get kill rate (kills / total requests).

        Returns 0.0 if no requests recorded.
        """
        with self._lock:
            conn = self._get_conn()
            try:
                req_row = conn.execute("SELECT COUNT(*) as total FROM sla_requests").fetchone()
                kill_row = conn.execute("SELECT COUNT(*) as total FROM sla_kills").fetchone()
            finally:
                self._close_conn(conn)

        total_req = req_row["total"]
        if total_req == 0:
            return 0.0
        return kill_row["total"] / total_req

    def get_false_positive_rate(self) -> float:
        """
        Get false positive rate (false positive kills / total kills).

        Returns 0.0 if no kills recorded.
        """
        with self._lock:
            conn = self._get_conn()
            try:
                total_row = conn.execute("SELECT COUNT(*) as total FROM sla_kills").fetchone()
                fp_row = conn.execute("SELECT COUNT(*) as total FROM sla_kills WHERE is_false_positive = 1").fetchone()
            finally:
                self._close_conn(conn)

        total = total_row["total"]
        if total == 0:
            return 0.0
        return fp_row["total"] / total

    def get_mean_time_to_detect(self) -> float:
        """
        Get mean time to detect in milliseconds (average detection_time_ms from kills).

        Returns 0.0 if no kills recorded.
        """
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT AVG(detection_time_ms) as avg_dt FROM sla_kills"
                ).fetchone()
            finally:
                self._close_conn(conn)

        return row["avg_dt"] if row["avg_dt"] is not None else 0.0

    def get_request_count(self) -> int:
        """Get total number of recorded requests."""
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute("SELECT COUNT(*) as total FROM sla_requests").fetchone()
            finally:
                self._close_conn(conn)
        return row["total"]

    def get_kill_count(self) -> int:
        """Get total number of recorded kills."""
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute("SELECT COUNT(*) as total FROM sla_kills").fetchone()
            finally:
                self._close_conn(conn)
        return row["total"]

    def get_breach_count(self) -> int:
        """Get total number of recorded breaches."""
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute("SELECT COUNT(*) as total FROM sla_breaches").fetchone()
            finally:
                self._close_conn(conn)
        return row["total"]

    def clear(self):
        """Clear all data (for testing)."""
        with self._lock:
            conn = self._get_conn()
            try:
                conn.execute("DELETE FROM sla_requests")
                conn.execute("DELETE FROM sla_kills")
                conn.execute("DELETE FROM sla_breaches")
                conn.commit()
            finally:
                self._close_conn(conn)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_tracker: Optional[SLATracker] = None


def get_sla_tracker(db_path: str = ":memory:", **kwargs) -> SLATracker:
    """Get or create the global SLA tracker singleton."""
    global _tracker
    if _tracker is None:
        _tracker = SLATracker(db_path=db_path, **kwargs)
    return _tracker


def reset_sla_tracker():
    """Reset the global tracker (for testing)."""
    global _tracker
    _tracker = None
