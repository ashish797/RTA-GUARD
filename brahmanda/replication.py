"""
RTA-GUARD — Data Replication Module (Phase 6.5)

Async, event-driven replication for session state and audit logs across
regions. Conflict resolution: last-write-wins for sessions, append-only
merge for audit logs. Replication lag monitoring included.
"""

from __future__ import annotations

import json
import hashlib
import threading
import time
import logging
from collections import deque
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, List, Dict, Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ReplicationStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    REPLICATED = "replicated"
    FAILED = "failed"
    CONFLICT = "conflict"


@dataclass
class ReplicationEvent:
    """A single replication event."""
    event_id: str
    event_type: str  # "session_state" | "audit_log"
    payload: Dict[str, Any] = field(default_factory=dict)
    source_region: str = ""
    target_regions: List[str] = field(default_factory=list)
    status: str = ReplicationStatus.PENDING.value
    created_at: float = 0.0
    replicated_at: Optional[float] = None
    retry_count: int = 0
    error: Optional[str] = None
    checksum: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = time.time()
        if not self.checksum:
            self.checksum = self._compute_checksum()

    def _compute_checksum(self) -> str:
        raw = json.dumps(self.payload, sort_keys=True).encode()
        return hashlib.sha256(raw).hexdigest()[:16]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReplicationLag:
    """Replication lag measurement between two regions."""
    source_region: str
    target_region: str
    lag_seconds: float = 0.0
    pending_events: int = 0
    last_successful_replication: Optional[float] = None
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Conflict Resolution
# ---------------------------------------------------------------------------

class ConflictResolver:
    """
    Strategy-based conflict resolution.

    - sessions: last-write-wins (highest timestamp)
    - audit_log: append-only merge (union of all events, deduplicated by hash)
    """

    @staticmethod
    def resolve_session(local: Dict[str, Any],
                        remote: Dict[str, Any]) -> Dict[str, Any]:
        """Last-write-wins for session state."""
        local_ts = local.get("updated_at", 0)
        remote_ts = remote.get("updated_at", 0)
        if remote_ts > local_ts:
            return remote
        return local

    @staticmethod
    def resolve_audit_log(local_entries: List[Dict[str, Any]],
                          remote_entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Append-only merge: union by entry hash, sorted by timestamp."""
        seen: Dict[str, Dict[str, Any]] = {}
        for entry in local_entries + remote_entries:
            key = entry.get("hash") or entry.get("event_id", "")
            if key and key not in seen:
                seen[key] = entry
        return sorted(seen.values(), key=lambda e: e.get("timestamp", 0))


# ---------------------------------------------------------------------------
# Replicator
# ---------------------------------------------------------------------------

class Replicator:
    """
    Async event-driven replicator.

    Events are queued and flushed in batches. A background thread processes
    the queue and calls registered transport functions to send data to
    target regions.

    Usage:
        repl = Replicator(source_region="us-east-1")
        repl.register_transport("eu-west-1", my_send_fn)
        repl.enqueue_session(session_id, session_data)
        repl.enqueue_audit(event_data)
        repl.start()
    """

    def __init__(self, source_region: str, batch_size: int = 50,
                 flush_interval: float = 5.0, max_retries: int = 3):
        self._source = source_region
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._max_retries = max_retries
        self._queue: deque[ReplicationEvent] = deque()
        self._completed: deque[ReplicationEvent] = deque(maxlen=1000)
        self._transports: Dict[str, Callable[[ReplicationEvent], bool]] = {}
        self._resolver = ConflictResolver()
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._stats: Dict[str, int] = {
            "total_enqueued": 0,
            "total_replicated": 0,
            "total_failed": 0,
        }

    def register_transport(self, target_region: str,
                           send_fn: Callable[[ReplicationEvent], bool]) -> None:
        """Register a transport function for a target region."""
        self._transports[target_region] = send_fn

    def enqueue_session(self, session_id: str, session_data: Dict[str, Any],
                        targets: Optional[List[str]] = None) -> str:
        """Enqueue a session state replication event."""
        import uuid
        event_id = f"sess-{uuid.uuid4().hex[:12]}"
        event = ReplicationEvent(
            event_id=event_id,
            event_type="session_state",
            payload={"session_id": session_id, **session_data},
            source_region=self._source,
            target_regions=targets or list(self._transports.keys()),
        )
        with self._lock:
            self._queue.append(event)
            self._stats["total_enqueued"] += 1
        return event_id

    def enqueue_audit(self, audit_data: Dict[str, Any],
                      targets: Optional[List[str]] = None) -> str:
        """Enqueue an audit log replication event."""
        import uuid
        event_id = f"audit-{uuid.uuid4().hex[:12]}"
        event = ReplicationEvent(
            event_id=event_id,
            event_type="audit_log",
            payload=audit_data,
            source_region=self._source,
            target_regions=targets or list(self._transports.keys()),
        )
        with self._lock:
            self._queue.append(event)
            self._stats["total_enqueued"] += 1
        return event_id

    def start(self) -> None:
        """Start background replication thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="replicator"
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop replication and flush remaining events."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        self._flush_batch()

    def get_lag(self) -> List[ReplicationLag]:
        """Get replication lag for all target regions."""
        with self._lock:
            pending_by_target: Dict[str, int] = {}
            for event in self._queue:
                for t in event.target_regions:
                    pending_by_target[t] = pending_by_target.get(t, 0) + 1

        lags = []
        for target in self._transports:
            last_ok: Optional[float] = None
            for e in reversed(self._completed):
                if e.status == ReplicationStatus.REPLICATED.value and target in e.target_regions:
                    last_ok = e.replicated_at
                    break
            lag_s = (time.time() - last_ok) if last_ok else float("inf")
            lags.append(ReplicationLag(
                source_region=self._source,
                target_region=target,
                lag_seconds=round(lag_s, 2),
                pending_events=pending_by_target.get(target, 0),
                last_successful_replication=last_ok,
            ))
        return lags

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                **self._stats,
                "queue_depth": len(self._queue),
                "completed_count": len(self._completed),
            }

    def flush(self) -> int:
        """Manually flush one batch. Returns events processed."""
        return self._flush_batch()

    # -- internals --

    def _flush_loop(self) -> None:
        while self._running:
            time.sleep(self._flush_interval)
            self._flush_batch()

    def _flush_batch(self) -> int:
        batch: List[ReplicationEvent] = []
        with self._lock:
            while self._queue and len(batch) < self._batch_size:
                batch.append(self._queue.popleft())

        processed = 0
        for event in batch:
            event.status = ReplicationStatus.IN_PROGRESS.value
            success = self._send_to_targets(event)
            if success:
                event.status = ReplicationStatus.REPLICATED.value
                event.replicated_at = time.time()
                with self._lock:
                    self._stats["total_replicated"] += 1
            else:
                event.retry_count += 1
                if event.retry_count < self._max_retries:
                    event.status = ReplicationStatus.PENDING.value
                    with self._lock:
                        self._queue.appendleft(event)
                else:
                    event.status = ReplicationStatus.FAILED.value
                    with self._lock:
                        self._stats["total_failed"] += 1
                    logger.error("Replication failed after %d retries: %s",
                                 self._max_retries, event.event_id)
            with self._lock:
                self._completed.append(event)
            processed += 1
        return processed

    def _send_to_targets(self, event: ReplicationEvent) -> bool:
        all_ok = True
        for target in event.target_regions:
            transport = self._transports.get(target)
            if transport is None:
                logger.warning("No transport for region %s", target)
                all_ok = False
                continue
            try:
                ok = transport(event)
                if not ok:
                    all_ok = False
            except Exception as e:
                logger.exception("Transport error for %s", target)
                event.error = str(e)
                all_ok = False
        return all_ok


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_replicator: Optional[Replicator] = None


def get_replicator(**kwargs) -> Replicator:
    global _replicator
    if _replicator is None:
        _replicator = Replicator(**kwargs)
    return _replicator


def reset_replicator() -> None:
    global _replicator
    if _replicator:
        _replicator.stop()
    _replicator = None
