"""
RTA-GUARD — Efficient Operations (Phase 6.6)

Batch kill processing, lazy drift scoring, cache warming, audit log compression.
All features are opt-in (disabled by default).
"""

import gzip
import hashlib
import json
import os
import sqlite3
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any, Callable, Tuple


# ---------------------------------------------------------------------------
# Batch Kill Processor
# ---------------------------------------------------------------------------

@dataclass
class PendingKill:
    """A kill decision queued for batch processing."""
    tenant_id: str
    agent_id: str
    session_id: str
    rule_id: str
    reason: str
    severity: str
    timestamp: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class BatchKillProcessor:
    """
    Batches kill decisions to reduce per-decision overhead.
    Groups kills by tenant, flushes in batches based on size or time threshold.

    Usage:
        processor = BatchKillProcessor(max_batch_size=50, flush_interval_seconds=5.0)
        processor.enqueue(PendingKill(tenant_id="acme", agent_id="gpt4", ...))
        # Auto-flushes when batch reaches 50 or after 5 seconds
    """

    def __init__(self, max_batch_size: int = 50,
                 flush_interval_seconds: float = 5.0,
                 handler: Optional[Callable[[List[PendingKill]], None]] = None):
        self._max_batch_size = max_batch_size
        self._flush_interval = flush_interval_seconds
        self._handler = handler
        self._batches: Dict[str, List[PendingKill]] = defaultdict(list)
        self._lock = threading.Lock()
        self._flush_thread: Optional[threading.Thread] = None
        self._running = False
        self._stats = {"total_enqueued": 0, "total_flushed": 0, "total_batches": 0}

    def start(self):
        """Start the background flush thread."""
        if self._running:
            return
        self._running = True
        self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True)
        self._flush_thread.start()

    def stop(self):
        """Stop the background thread and flush remaining items."""
        self._running = False
        self.flush_all()
        if self._flush_thread:
            self._flush_thread.join(timeout=5)

    def enqueue(self, kill: PendingKill) -> bool:
        """Enqueue a kill for batch processing. Returns True if batch was flushed."""
        with self._lock:
            self._batches[kill.tenant_id].append(kill)
            self._stats["total_enqueued"] += 1

            if len(self._batches[kill.tenant_id]) >= self._max_batch_size:
                batch = self._batches.pop(kill.tenant_id)
                self._execute_batch(batch)
                return True
        return False

    def flush_tenant(self, tenant_id: str):
        """Immediately flush all pending kills for a tenant."""
        with self._lock:
            batch = self._batches.pop(tenant_id, [])
        if batch:
            self._execute_batch(batch)

    def flush_all(self):
        """Flush all pending kills across all tenants."""
        with self._lock:
            batches = dict(self._batches)
            self._batches.clear()
        for batch in batches.values():
            if batch:
                self._execute_batch(batch)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            pending = {k: len(v) for k, v in self._batches.items()}
        return {**self._stats, "pending_by_tenant": pending}

    def _execute_batch(self, batch: List[PendingKill]):
        self._stats["total_flushed"] += len(batch)
        self._stats["total_batches"] += 1
        if self._handler:
            try:
                self._handler(batch)
            except Exception:
                pass  # Don't let handler errors break batching

    def _flush_loop(self):
        while self._running:
            time.sleep(self._flush_interval)
            self.flush_all()


# ---------------------------------------------------------------------------
# Lazy Drift Scorer
# ---------------------------------------------------------------------------

@dataclass
class DriftScoreCache:
    """Cached drift score with staleness tracking."""
    agent_id: str
    score: float
    components: Dict[str, float]
    computed_at: str
    ttl_seconds: int = 300  # 5 min default TTL

    @property
    def is_stale(self) -> bool:
        computed = datetime.fromisoformat(self.computed_at)
        age = (datetime.now(timezone.utc) - computed).total_seconds()
        return age > self.ttl_seconds


class LazyDriftScorer:
    """
    Lazy drift score computation — scores are computed only when requested.
    Caches results with configurable TTL.

    Usage:
        scorer = LazyDriftScorer()
        score = scorer.get_drift_score("agent_001", compute_fn=my_compute_fn)
    """

    def __init__(self, default_ttl: int = 300,
                 max_cache_size: int = 1000):
        self._default_ttl = default_ttl
        self._max_cache_size = max_cache_size
        self._cache: Dict[str, DriftScoreCache] = {}
        self._lock = threading.Lock()
        self._stats = {"hits": 0, "misses": 0, "computes": 0, "evictions": 0}

    def get_drift_score(self, agent_id: str,
                        compute_fn: Optional[Callable[[str], Tuple[float, Dict[str, float]]]] = None,
                        force_recompute: bool = False) -> Optional[Tuple[float, Dict[str, float]]]:
        """
        Get drift score for an agent. Returns cached value if fresh.
        If cache miss and compute_fn provided, computes and caches.

        Returns (score, components) or None if no data available.
        """
        with self._lock:
            cached = self._cache.get(agent_id)

            if cached and not cached.is_stale and not force_recompute:
                self._stats["hits"] += 1
                return cached.score, cached.components

        # Cache miss or stale — compute
        self._stats["misses"] += 1

        if compute_fn is None:
            return None

        self._stats["computes"] += 1
        score, components = compute_fn(agent_id)

        with self._lock:
            # Evict if cache is full (LRU-style: evict oldest)
            if len(self._cache) >= self._max_cache_size:
                oldest_key = min(self._cache, key=lambda k: self._cache[k].computed_at)
                del self._cache[oldest_key]
                self._stats["evictions"] += 1

            self._cache[agent_id] = DriftScoreCache(
                agent_id=agent_id,
                score=score,
                components=components,
                computed_at=datetime.now(timezone.utc).isoformat(),
                ttl_seconds=self._default_ttl,
            )

        return score, components

    def invalidate(self, agent_id: str):
        """Invalidate cached score for an agent."""
        with self._lock:
            self._cache.pop(agent_id, None)

    def invalidate_all(self):
        """Clear entire cache."""
        with self._lock:
            self._cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            hit_rate = 0.0
            total = self._stats["hits"] + self._stats["misses"]
            if total > 0:
                hit_rate = self._stats["hits"] / total * 100
            return {**self._stats, "cache_size": len(self._cache), "hit_rate_pct": round(hit_rate, 1)}


# ---------------------------------------------------------------------------
# Cache Warmer
# ---------------------------------------------------------------------------

@dataclass
class CacheEntry:
    """A cached rule evaluation result."""
    key: str
    value: Any
    computed_at: str
    ttl_seconds: int = 3600
    hit_count: int = 0

    @property
    def is_stale(self) -> bool:
        computed = datetime.fromisoformat(self.computed_at)
        age = (datetime.now(timezone.utc) - computed).total_seconds()
        return age > self.ttl_seconds


class CacheWarmer:
    """
    Pre-computes common rule evaluations for frequently-hit rules.
    Tracks access patterns to identify warming candidates.

    Usage:
        warmer = CacheWarmer()
        warmer.record_access("R1", "agent_001", "session_abc")  # track usage
        warmer.warm(compute_fn=my_rule_fn)  # pre-compute top rules
    """

    def __init__(self, max_cache_size: int = 5000, default_ttl: int = 3600):
        self._max_cache_size = max_cache_size
        self._default_ttl = default_ttl
        self._cache: Dict[str, CacheEntry] = {}
        self._access_counts: Dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        self._stats = {"hits": 0, "misses": 0, "warming_runs": 0, "entries": 0}

    def record_access(self, rule_id: str, agent_id: str, context_hash: str = ""):
        """Record an access pattern for warming analysis."""
        key = self._make_key(rule_id, agent_id, context_hash)
        with self._lock:
            self._access_counts[key] += 1

    def get(self, rule_id: str, agent_id: str, context_hash: str = "") -> Optional[Any]:
        """Get a cached evaluation result."""
        key = self._make_key(rule_id, agent_id, context_hash)
        with self._lock:
            entry = self._cache.get(key)
            if entry and not entry.is_stale:
                entry.hit_count += 1
                self._stats["hits"] += 1
                return entry.value
        self._stats["misses"] += 1
        return None

    def put(self, rule_id: str, agent_id: str, value: Any,
            context_hash: str = "", ttl: Optional[int] = None):
        """Store a computed result in cache."""
        key = self._make_key(rule_id, agent_id, context_hash)
        with self._lock:
            if len(self._cache) >= self._max_cache_size:
                # Evict least-hit entry
                min_key = min(self._cache, key=lambda k: self._cache[k].hit_count)
                del self._cache[min_key]
            self._cache[key] = CacheEntry(
                key=key, value=value,
                computed_at=datetime.now(timezone.utc).isoformat(),
                ttl_seconds=ttl or self._default_ttl,
            )
            self._stats["entries"] = len(self._cache)

    def warm(self, compute_fn: Callable[[str, str, str], Any],
             top_n: int = 100):
        """
        Pre-compute evaluations for the most frequently accessed rule+agent combos.
        `compute_fn(rule_id, agent_id, context_hash) -> result`
        """
        with self._lock:
            top_keys = sorted(self._access_counts.items(), key=lambda x: -x[1])[:top_n]
            stale_keys = [k for k, entry in self._cache.items() if entry.is_stale]

        # Compute stale and top-N entries
        seen = set()
        for key, _ in top_keys + [(k, 0) for k in stale_keys]:
            if key in seen:
                continue
            seen.add(key)
            parts = key.split(":")
            if len(parts) >= 2:
                rule_id, agent_id = parts[0], parts[1]
                context_hash = parts[2] if len(parts) > 2 else ""
                try:
                    value = compute_fn(rule_id, agent_id, context_hash)
                    self.put(rule_id, agent_id, value, context_hash)
                except Exception:
                    pass

        self._stats["warming_runs"] += 1

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            total = self._stats["hits"] + self._stats["misses"]
            hit_rate = (self._stats["hits"] / total * 100) if total > 0 else 0
            return {
                **self._stats,
                "hit_rate_pct": round(hit_rate, 1),
                "access_patterns": len(self._access_counts),
            }

    @staticmethod
    def _make_key(rule_id: str, agent_id: str, context_hash: str = "") -> str:
        return f"{rule_id}:{agent_id}:{context_hash}"


# ---------------------------------------------------------------------------
# Compressed Audit Log
# ---------------------------------------------------------------------------

class CompressedAuditLog:
    """
    Audit log writer with gzip compression for storage efficiency.
    Stores compressed entries in SQLite.

    Usage:
        log = CompressedAuditLog(db_path="data/audit_compressed.db")
        log.append({"event": "kill", "agent": "gpt4", "rule": "R1"})
        entries = log.read_all()
    """

    def __init__(self, db_path: Optional[str] = None, in_memory: bool = False,
                 compression_level: int = 6):
        self._compression_level = compression_level
        if in_memory:
            self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        else:
            self._db_path = db_path or os.getenv("AUDIT_LOG_DB_PATH", "data/audit_compressed.db")
            os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._init_schema()
        self._stats = {"entries": 0, "raw_bytes": 0, "compressed_bytes": 0}

    def _init_schema(self):
        with self._lock:
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS compressed_audit (
                    entry_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    compressed_data BLOB NOT NULL,
                    raw_size INTEGER NOT NULL,
                    compressed_size INTEGER NOT NULL,
                    timestamp TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_tenant ON compressed_audit(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_audit_type ON compressed_audit(event_type);
                CREATE INDEX IF NOT EXISTS idx_audit_time ON compressed_audit(timestamp);
            """)
            self._conn.commit()

    def append(self, entry: Dict[str, Any], tenant_id: str = "default",
               event_type: str = "generic") -> str:
        """Append a compressed audit log entry. Returns entry ID."""
        raw_data = json.dumps(entry, separators=(',', ':')).encode('utf-8')
        compressed = gzip.compress(raw_data, compresslevel=self._compression_level)

        entry_id = hashlib.sha256(
            f"{tenant_id}:{event_type}:{time.monotonic_ns()}".encode()
        ).hexdigest()[:16]

        timestamp = entry.get("timestamp", datetime.now(timezone.utc).isoformat())

        with self._lock:
            self._conn.execute(
                """INSERT INTO compressed_audit
                   (entry_id, tenant_id, event_type, compressed_data, raw_size, compressed_size, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (entry_id, tenant_id, event_type, compressed,
                 len(raw_data), len(compressed), timestamp)
            )
            self._conn.commit()
            self._stats["entries"] += 1
            self._stats["raw_bytes"] += len(raw_data)
            self._stats["compressed_bytes"] += len(compressed)

        return entry_id

    def read(self, entry_id: str) -> Optional[Dict[str, Any]]:
        """Read and decompress a single audit entry."""
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM compressed_audit WHERE entry_id = ?", (entry_id,)
            ).fetchone()
        if not row:
            return None
        return json.loads(gzip.decompress(row["compressed_data"]))

    def read_all(self, tenant_id: Optional[str] = None,
                 event_type: Optional[str] = None,
                 start: Optional[str] = None,
                 end: Optional[str] = None,
                 limit: int = 1000) -> List[Dict[str, Any]]:
        """Read and decompress audit entries with optional filters."""
        query = "SELECT * FROM compressed_audit WHERE 1=1"
        params = []
        if tenant_id:
            query += " AND tenant_id = ?"
            params.append(tenant_id)
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if start:
            query += " AND timestamp >= ?"
            params.append(start)
        if end:
            query += " AND timestamp < ?"
            params.append(end)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)

        with self._lock:
            rows = self._conn.execute(query, params).fetchall()

        return [json.loads(gzip.decompress(r["compressed_data"])) for r in rows]

    def get_compression_stats(self) -> Dict[str, Any]:
        """Get compression ratio statistics."""
        with self._lock:
            stats = dict(self._stats)
        if stats["raw_bytes"] > 0:
            stats["compression_ratio"] = round(
                1 - (stats["compressed_bytes"] / stats["raw_bytes"]), 3
            )
            stats["space_saved_bytes"] = stats["raw_bytes"] - stats["compressed_bytes"]
        else:
            stats["compression_ratio"] = 0
            stats["space_saved_bytes"] = 0
        return stats

    def close(self):
        self._conn.close()


# ---------------------------------------------------------------------------
# Singleton management
# ---------------------------------------------------------------------------

_batch_processor: Optional[BatchKillProcessor] = None
_lazy_scorer: Optional[LazyDriftScorer] = None
_cache_warmer: Optional[CacheWarmer] = None
_audit_log: Optional[CompressedAuditLog] = None


def get_batch_processor(**kwargs) -> BatchKillProcessor:
    global _batch_processor
    if _batch_processor is None:
        _batch_processor = BatchKillProcessor(**kwargs)
    return _batch_processor


def get_lazy_scorer(**kwargs) -> LazyDriftScorer:
    global _lazy_scorer
    if _lazy_scorer is None:
        _lazy_scorer = LazyDriftScorer(**kwargs)
    return _lazy_scorer


def get_cache_warmer(**kwargs) -> CacheWarmer:
    global _cache_warmer
    if _cache_warmer is None:
        _cache_warmer = CacheWarmer(**kwargs)
    return _cache_warmer


def get_compressed_audit_log(**kwargs) -> CompressedAuditLog:
    global _audit_log
    if _audit_log is None:
        _audit_log = CompressedAuditLog(**kwargs)
    return _audit_log


def reset_singletons():
    global _batch_processor, _lazy_scorer, _cache_warmer, _audit_log
    _batch_processor = None
    _lazy_scorer = None
    _cache_warmer = None
    _audit_log = None
