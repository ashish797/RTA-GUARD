"""
RTA-GUARD Federation — Protocol

HTTP-based protocol for inter-node communication.
Handles: node registration, fingerprint exchange, threat intel sharing.
"""
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from pathlib import Path
import sqlite3

logger = logging.getLogger("discus.federation.protocol")


class MessageType(Enum):
    """Federation message types."""
    REGISTER = "register"
    HEARTBEAT = "heartbeat"
    FINGERPRINT_SHARE = "fingerprint_share"
    THREAT_INTEL = "threat_intel"
    AGGREGATION_REQUEST = "aggregation_request"
    AGGREGATION_RESPONSE = "aggregation_response"
    DRIFT_ALERT = "drift_alert"
    SYNC_REQUEST = "sync_request"
    SYNC_RESPONSE = "sync_response"


@dataclass
class FederationNode:
    """A node in the federation."""
    node_id: str
    url: str  # Base URL for this node
    public_key: str = ""  # For future PQC auth
    last_seen: float = 0.0
    is_trusted: bool = True
    shared_fingerprints: int = 0
    shared_threats: int = 0
    privacy_mode: str = "balanced"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_id": self.node_id,
            "url": self.url,
            "public_key": self.public_key,
            "last_seen": self.last_seen,
            "is_trusted": self.is_trusted,
            "shared_fingerprints": self.shared_fingerprints,
            "shared_threats": self.shared_threats,
            "privacy_mode": self.privacy_mode,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FederationNode":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ThreatSignature:
    """
    Shared threat intelligence signature.
    Captures attack patterns without exposing the original content.
    """
    signature_id: str
    threat_type: str  # e.g., "injection", "jailbreak", "pii_leak"
    pattern_hash: str  # Hashed pattern features
    severity: str  # kill, warn
    confidence: float  # 0-1
    source_node: str
    seen_count: int = 1
    first_seen: float = field(default_factory=time.time)
    last_seen: float = field(default_factory=time.time)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "signature_id": self.signature_id,
            "threat_type": self.threat_type,
            "pattern_hash": self.pattern_hash,
            "severity": self.severity,
            "confidence": self.confidence,
            "source_node": self.source_node,
            "seen_count": self.seen_count,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ThreatSignature":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class FederationMessage:
    """Message sent between federation nodes."""
    msg_type: MessageType
    source_node: str
    target_node: str
    payload: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    message_id: str = ""
    signature: str = ""  # For future PQC signing

    def __post_init__(self):
        if not self.message_id:
            raw = f"{self.source_node}:{self.timestamp}:{self.msg_type.value}"
            self.message_id = hashlib.sha256(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "msg_type": self.msg_type.value,
            "source_node": self.source_node,
            "target_node": self.target_node,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "message_id": self.message_id,
            "signature": self.signature,
        }

    def serialize(self) -> str:
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def deserialize(cls, data: str) -> "FederationMessage":
        d = json.loads(data)
        d["msg_type"] = MessageType(d["msg_type"])
        return cls(**d)


class FederationStore:
    """SQLite storage for federation data."""

    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path.home() / ".rta-guard" / "federation.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS nodes (
                    node_id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    public_key TEXT DEFAULT '',
                    last_seen REAL DEFAULT 0,
                    is_trusted INTEGER DEFAULT 1,
                    shared_fingerprints INTEGER DEFAULT 0,
                    shared_threats INTEGER DEFAULT 0,
                    privacy_mode TEXT DEFAULT 'balanced'
                );

                CREATE TABLE IF NOT EXISTS fingerprints (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_hash TEXT NOT NULL,
                    source_node TEXT NOT NULL,
                    feature_vector TEXT NOT NULL,
                    sample_count INTEGER DEFAULT 0,
                    received_at REAL NOT NULL,
                    FOREIGN KEY (source_node) REFERENCES nodes(node_id)
                );

                CREATE TABLE IF NOT EXISTS threat_signatures (
                    signature_id TEXT PRIMARY KEY,
                    threat_type TEXT NOT NULL,
                    pattern_hash TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    confidence REAL DEFAULT 0.0,
                    source_node TEXT NOT NULL,
                    seen_count INTEGER DEFAULT 1,
                    first_seen REAL NOT NULL,
                    last_seen REAL NOT NULL,
                    tags TEXT DEFAULT '[]'
                );

                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    msg_type TEXT NOT NULL,
                    source_node TEXT NOT NULL,
                    target_node TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    timestamp REAL NOT NULL,
                    direction TEXT NOT NULL DEFAULT 'outbound'
                );

                CREATE INDEX IF NOT EXISTS idx_fp_source ON fingerprints(source_node);
                CREATE INDEX IF NOT EXISTS idx_threat_type ON threat_signatures(threat_type);
                CREATE INDEX IF NOT EXISTS idx_msg_ts ON messages(timestamp);
            """)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    # ─── Node Management ────────────────────────────────────────────

    def register_node(self, node: FederationNode) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO nodes
                (node_id, url, public_key, last_seen, is_trusted, shared_fingerprints, shared_threats, privacy_mode)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (node.node_id, node.url, node.public_key, time.time(),
                  int(node.is_trusted), node.shared_fingerprints, node.shared_threats, node.privacy_mode))

    def get_node(self, node_id: str) -> Optional[FederationNode]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE node_id = ?", (node_id,)).fetchone()
            if not row:
                return None
            return FederationNode(
                node_id=row["node_id"], url=row["url"], public_key=row["public_key"],
                last_seen=row["last_seen"], is_trusted=bool(row["is_trusted"]),
                shared_fingerprints=row["shared_fingerprints"], shared_threats=row["shared_threats"],
                privacy_mode=row["privacy_mode"],
            )

    def list_nodes(self, trusted_only: bool = False) -> List[FederationNode]:
        q = "SELECT * FROM nodes"
        if trusted_only:
            q += " WHERE is_trusted = 1"
        with self._conn() as conn:
            rows = conn.execute(q).fetchall()
            return [FederationNode(
                node_id=r["node_id"], url=r["url"], public_key=r["public_key"],
                last_seen=r["last_seen"], is_trusted=bool(r["is_trusted"]),
                shared_fingerprints=r["shared_fingerprints"], shared_threats=r["shared_threats"],
                privacy_mode=r["privacy_mode"],
            ) for r in rows]

    def update_heartbeat(self, node_id: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE nodes SET last_seen = ? WHERE node_id = ?", (time.time(), node_id))

    # ─── Fingerprints ───────────────────────────────────────────────

    def store_fingerprint(self, session_hash: str, source_node: str,
                          feature_vector: List[float], sample_count: int) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO fingerprints (session_hash, source_node, feature_vector, sample_count, received_at)
                VALUES (?, ?, ?, ?, ?)
            """, (session_hash, source_node, json.dumps(feature_vector), sample_count, time.time()))

    def get_fingerprints(self, source_node: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        q = "SELECT * FROM fingerprints"
        params = []
        if source_node:
            q += " WHERE source_node = ?"
            params.append(source_node)
        q += " ORDER BY received_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(q, params).fetchall()
            return [{k: (json.loads(r["feature_vector"]) if k == "feature_vector" else r[k])
                     for k in r.keys()} for r in rows]

    # ─── Threat Signatures ──────────────────────────────────────────

    def store_threat(self, sig: ThreatSignature) -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO threat_signatures
                (signature_id, threat_type, pattern_hash, severity, confidence, source_node,
                 seen_count, first_seen, last_seen, tags)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sig.signature_id, sig.threat_type, sig.pattern_hash, sig.severity,
                  sig.confidence, sig.source_node, sig.seen_count, sig.first_seen,
                  sig.last_seen, json.dumps(sig.tags)))

    def get_threats(self, threat_type: Optional[str] = None, min_confidence: float = 0.0) -> List[ThreatSignature]:
        q = "SELECT * FROM threat_signatures WHERE confidence >= ?"
        params: list = [min_confidence]
        if threat_type:
            q += " AND threat_type = ?"
            params.append(threat_type)
        q += " ORDER BY last_seen DESC"
        with self._conn() as conn:
            rows = conn.execute(q, params).fetchall()
            return [ThreatSignature(
                signature_id=r["signature_id"], threat_type=r["threat_type"],
                pattern_hash=r["pattern_hash"], severity=r["severity"],
                confidence=r["confidence"], source_node=r["source_node"],
                seen_count=r["seen_count"], first_seen=r["first_seen"],
                last_seen=r["last_seen"], tags=json.loads(r["tags"]),
            ) for r in rows]

    def increment_threat_count(self, signature_id: str) -> None:
        with self._conn() as conn:
            conn.execute("""
                UPDATE threat_signatures SET seen_count = seen_count + 1, last_seen = ?
                WHERE signature_id = ?
            """, (time.time(), signature_id))

    # ─── Messages ───────────────────────────────────────────────────

    def log_message(self, msg: FederationMessage, direction: str = "outbound") -> None:
        with self._conn() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO messages
                (message_id, msg_type, source_node, target_node, payload, timestamp, direction)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (msg.message_id, msg.msg_type.value, msg.source_node,
                  msg.target_node, json.dumps(msg.payload), msg.timestamp, direction))

    def get_stats(self) -> Dict[str, Any]:
        with self._conn() as conn:
            nodes = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            fps = conn.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0]
            threats = conn.execute("SELECT COUNT(*) FROM threat_signatures").fetchone()[0]
            msgs = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            return {
                "nodes": nodes,
                "fingerprints": fps,
                "threat_signatures": threats,
                "messages": msgs,
            }
