"""
RTA-GUARD Observability — Trace Engine

Collects, stores, and queries guard decision traces.
Every check produces a trace for audit, debugging, and analytics.
"""
import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("discus.observability.trace")


@dataclass
class GuardTrace:
    """A single guard decision trace."""
    trace_id: str
    session_id: str
    decision: str  # pass, warn, kill
    rule_triggered: str  # Which rule caused the decision
    duration_ms: float
    timestamp: float = field(default_factory=time.time)
    input_hash: str = ""  # SHA-256 of input (privacy-safe)
    profile_name: str = ""
    tenant_id: str = ""
    violation_type: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "session_id": self.session_id,
            "decision": self.decision,
            "rule_triggered": self.rule_triggered,
            "duration_ms": round(self.duration_ms, 3),
            "timestamp": self.timestamp,
            "input_hash": self.input_hash,
            "profile_name": self.profile_name,
            "tenant_id": self.tenant_id,
            "violation_type": self.violation_type,
            "metadata": self.metadata,
        }


class TraceCollector:
    """
    Collects and stores guard traces in SQLite.

    Features:
    - Fast writes (batch support)
    - Query by session, rule, decision, time range
    - Export as JSON/CSV
    - Auto-cleanup of old traces
    """

    def __init__(self, db_path: Optional[Path] = None, retention_days: int = 30):
        self.db_path = db_path or Path.home() / ".rta-guard" / "traces.db"
        self.retention_days = retention_days
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS traces (
                    trace_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    rule_triggered TEXT DEFAULT '',
                    duration_ms REAL DEFAULT 0,
                    timestamp REAL NOT NULL,
                    input_hash TEXT DEFAULT '',
                    profile_name TEXT DEFAULT '',
                    tenant_id TEXT DEFAULT '',
                    violation_type TEXT DEFAULT '',
                    metadata TEXT DEFAULT '{}'
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON traces(session_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_decision ON traces(decision)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON traces(timestamp)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_rule ON traces(rule_triggered)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tenant ON traces(tenant_id)")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def record(self, trace: GuardTrace) -> None:
        """Record a single trace."""
        with self._conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO traces
                (trace_id, session_id, decision, rule_triggered, duration_ms,
                 timestamp, input_hash, profile_name, tenant_id, violation_type, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trace.trace_id, trace.session_id, trace.decision,
                trace.rule_triggered, trace.duration_ms, trace.timestamp,
                trace.input_hash, trace.profile_name, trace.tenant_id,
                trace.violation_type, json.dumps(trace.metadata),
            ))

    def record_many(self, traces: List[GuardTrace]) -> None:
        """Batch record traces."""
        with self._conn() as conn:
            conn.executemany("""
                INSERT OR IGNORE INTO traces
                (trace_id, session_id, decision, rule_triggered, duration_ms,
                 timestamp, input_hash, profile_name, tenant_id, violation_type, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [(
                t.trace_id, t.session_id, t.decision, t.rule_triggered,
                t.duration_ms, t.timestamp, t.input_hash, t.profile_name,
                t.tenant_id, t.violation_type, json.dumps(t.metadata),
            ) for t in traces])

    def query(self, session_id: Optional[str] = None, decision: Optional[str] = None,
              rule: Optional[str] = None, tenant_id: Optional[str] = None,
              start_time: Optional[float] = None, end_time: Optional[float] = None,
              limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        """Query traces with filters."""
        conditions = []
        params = []

        if session_id:
            conditions.append("session_id = ?")
            params.append(session_id)
        if decision:
            conditions.append("decision = ?")
            params.append(decision)
        if rule:
            conditions.append("rule_triggered = ?")
            params.append(rule)
        if tenant_id:
            conditions.append("tenant_id = ?")
            params.append(tenant_id)
        if start_time:
            conditions.append("timestamp >= ?")
            params.append(start_time)
        if end_time:
            conditions.append("timestamp <= ?")
            params.append(end_time)

        query = "SELECT * FROM traces"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self._conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def count(self, **kwargs) -> int:
        """Count traces matching filters."""
        conditions = []
        params = []
        for key in ["session_id", "decision", "rule_triggered", "tenant_id"]:
            val = kwargs.get(key)
            if val:
                conditions.append(f"{key} = ?")
                params.append(val)

        query = "SELECT COUNT(*) FROM traces"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        with self._conn() as conn:
            return conn.execute(query, params).fetchone()[0]

    def cleanup(self) -> int:
        """Remove traces older than retention period."""
        cutoff = time.time() - (self.retention_days * 86400)
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM traces WHERE timestamp < ?", (cutoff,))
            return cursor.rowcount

    def export_json(self, session_id: Optional[str] = None,
                    limit: int = 1000) -> str:
        """Export traces as JSON."""
        traces = self.query(session_id=session_id, limit=limit)
        return json.dumps(traces, indent=2, default=str)

    def export_csv(self, session_id: Optional[str] = None,
                   limit: int = 1000) -> str:
        """Export traces as CSV."""
        traces = self.query(session_id=session_id, limit=limit)
        if not traces:
            return ""

        headers = list(traces[0].keys())
        lines = [",".join(headers)]
        for t in traces:
            values = [str(t.get(h, "")) for h in headers]
            lines.append(",".join(values))
        return "\n".join(lines)

    def get_stats(self) -> Dict[str, Any]:
        """Get trace storage statistics."""
        with self._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0]
            oldest = conn.execute("SELECT MIN(timestamp) FROM traces").fetchone()[0]
            newest = conn.execute("SELECT MAX(timestamp) FROM traces").fetchone()[0]
            return {
                "total_traces": total,
                "oldest_timestamp": oldest,
                "newest_timestamp": newest,
                "retention_days": self.retention_days,
            }
