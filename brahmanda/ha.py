"""
RTA-GUARD — High Availability Module (Phase 6.5)

Leader election, split-brain detection, graceful shutdown, and health
check aggregation. Opt-in: single-node deployments skip HA entirely.
"""

from __future__ import annotations

import json
import os
import signal
import socket
import threading
import time
import uuid
import logging
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class ComponentStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheck:
    """Result of a single subcomponent health check."""
    name: str
    status: str  # ComponentStatus value
    latency_ms: float = 0.0
    message: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AggregatedHealth:
    """Aggregated health across all subcomponents."""
    overall_status: str = "healthy"
    checks: List[HealthCheck] = field(default_factory=list)
    node_id: str = ""
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "overall_status": self.overall_status,
            "checks": [c.to_dict() for c in self.checks],
            "node_id": self.node_id,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Leader Election (file-based, works without Redis)
# ---------------------------------------------------------------------------

class LeaderElection:
    """
    Simple file-based leader election with optional Redis backend.

    File-based mode writes a lease file to disk with node identity and TTL.
    Works for single-host or NFS-shared deployments. For real multi-node,
    inject a Redis connection string.

    Usage:
        le = LeaderElection(lease_dir="/tmp/rta-guard/leader", ttl=30)
        if le.try_acquire():
            # I am the leader
            ...
        le.release()
    """

    def __init__(self, lease_dir: str = "/tmp/rta-guard/leader",
                 ttl: float = 30.0,
                 node_id: Optional[str] = None,
                 redis_url: Optional[str] = None):
        self._lease_dir = Path(lease_dir)
        self._ttl = ttl
        self._node_id = node_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self._redis_url = redis_url
        self._lease_file = self._lease_dir / "leader.json"
        self._is_leader = False
        self._lock = threading.Lock()
        self._refresh_thread: Optional[threading.Thread] = None
        self._running = False

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def is_leader(self) -> bool:
        return self._is_leader

    def try_acquire(self) -> bool:
        """Attempt to become leader. Returns True if acquired."""
        with self._lock:
            if self._redis_url:
                return self._try_acquire_redis()
            return self._try_acquire_file()

    def release(self) -> None:
        """Release leadership."""
        with self._lock:
            self._running = False
            self._is_leader = False
            if self._refresh_thread and self._refresh_thread.is_alive():
                self._refresh_thread.join(timeout=5)
            if self._redis_url:
                self._release_redis()
            else:
                self._release_file()

    def start_auto_refresh(self) -> None:
        """Background thread to refresh lease before TTL expires."""
        self._running = True
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop, daemon=True, name="ha-leader-refresh"
        )
        self._refresh_thread.start()

    def get_leader_info(self) -> Optional[Dict[str, Any]]:
        """Read current leader info without acquiring."""
        if self._redis_url:
            return self._get_leader_redis()
        return self._get_leader_file()

    # -- file-based internals --

    def _try_acquire_file(self) -> bool:
        self._lease_dir.mkdir(parents=True, exist_ok=True)
        try:
            if self._lease_file.exists():
                raw = self._lease_file.read_text()
                data = json.loads(raw)
                expires = data.get("expires", 0)
                if time.time() < expires and data.get("node_id") != self._node_id:
                    return False  # someone else holds the lease
        except (json.JSONDecodeError, OSError):
            pass  # stale/corrupt — take over

        lease = {
            "node_id": self._node_id,
            "acquired": time.time(),
            "expires": time.time() + self._ttl,
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
        }
        tmp = self._lease_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(lease))
        tmp.replace(self._lease_file)
        self._is_leader = True
        logger.info("Leader acquired by %s", self._node_id)
        return True

    def _release_file(self) -> None:
        try:
            if self._lease_file.exists():
                raw = self._lease_file.read_text()
                data = json.loads(raw)
                if data.get("node_id") == self._node_id:
                    self._lease_file.unlink()
                    logger.info("Leader released by %s", self._node_id)
        except OSError:
            pass

    def _get_leader_file(self) -> Optional[Dict[str, Any]]:
        try:
            if self._lease_file.exists():
                return json.loads(self._lease_file.read_text())
        except (json.JSONDecodeError, OSError):
            pass
        return None

    # -- redis-based stubs (requires redis package) --

    def _try_acquire_redis(self) -> bool:
        try:
            import redis  # type: ignore
        except ImportError:
            logger.warning("redis package not installed, falling back to file")
            self._redis_url = None
            return self._try_acquire_file()
        r = redis.from_url(self._redis_url)
        lease_key = "rta-guard:leader"
        lease = json.dumps({
            "node_id": self._node_id,
            "acquired": time.time(),
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
        })
        ok = r.set(lease_key, lease, nx=True, ex=int(self._ttl))
        self._is_leader = bool(ok)
        if self._is_leader:
            logger.info("Leader acquired (Redis) by %s", self._node_id)
        return self._is_leader

    def _release_redis(self) -> None:
        try:
            import redis  # type: ignore
            r = redis.from_url(self._redis_url)
            data = r.get("rta-guard:leader")
            if data:
                info = json.loads(data)
                if info.get("node_id") == self._node_id:
                    r.delete("rta-guard:leader")
                    logger.info("Leader released (Redis) by %s", self._node_id)
        except Exception:
            pass

    def _get_leader_redis(self) -> Optional[Dict[str, Any]]:
        try:
            import redis  # type: ignore
            r = redis.from_url(self._redis_url)
            data = r.get("rta-guard:leader")
            if data:
                return json.loads(data)
        except Exception:
            pass
        return None

    def _refresh_loop(self) -> None:
        while self._running:
            time.sleep(self._ttl / 3)
            if self._is_leader and self._running:
                if self._redis_url:
                    try:
                        import redis  # type: ignore
                        r = redis.from_url(self._redis_url)
                        r.expire("rta-guard:leader", int(self._ttl))
                    except Exception:
                        pass
                else:
                    self._try_acquire_file()


# ---------------------------------------------------------------------------
# Split-Brain Detection
# ---------------------------------------------------------------------------

class SplitBrainDetector:
    """
    Detect when multiple nodes believe they are leader.

    Mechanism: each leader writes a heartbeat to a shared directory.
    If more than one heartbeat file exists with different node_ids and
    recent timestamps, split-brain is flagged.

    Usage:
        sbd = SplitBrainDetector(heartbeat_dir="/tmp/rta-guard/heartbeats")
        if sbd.detect_split_brain():
            # resolve: highest node_id wins, others demote
            sbd.resolve_split_brain()
    """

    def __init__(self, heartbeat_dir: str = "/tmp/rta-guard/heartbeats",
                 stale_threshold: float = 60.0):
        self._dir = Path(heartbeat_dir)
        self._stale = stale_threshold

    def register_heartbeat(self, node_id: str, is_leader: bool) -> None:
        """Write this node's heartbeat file."""
        if not is_leader:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        hb_file = self._dir / f"{node_id}.json"
        data = {"node_id": node_id, "timestamp": time.time(), "is_leader": True}
        tmp = hb_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        tmp.replace(hb_file)

    def detect_split_brain(self) -> bool:
        """Return True if multiple active leaders detected."""
        leaders = self._active_leaders()
        return len(leaders) > 1

    def resolve_split_brain(self) -> str:
        """
        Resolve split-brain: highest node_id lexicographically wins.
        Returns the winning node_id.
        """
        leaders = self._active_leaders()
        if not leaders:
            return ""
        winner = max(leaders, key=lambda d: d["node_id"])
        # Remove other heartbeats
        for hb in leaders:
            if hb["node_id"] != winner["node_id"]:
                p = self._dir / f"{hb['node_id']}.json"
                try:
                    p.unlink()
                    logger.info("Split-brain: demoted %s", hb["node_id"])
                except OSError:
                    pass
        logger.info("Split-brain: winner is %s", winner["node_id"])
        return winner["node_id"]

    def cleanup_stale(self) -> int:
        """Remove stale heartbeat files. Returns count removed."""
        removed = 0
        if not self._dir.exists():
            return 0
        now = time.time()
        for f in self._dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if now - data.get("timestamp", 0) > self._stale:
                    f.unlink()
                    removed += 1
            except (json.JSONDecodeError, OSError):
                f.unlink()
                removed += 1
        return removed

    def _active_leaders(self) -> List[Dict[str, Any]]:
        leaders = []
        if not self._dir.exists():
            return leaders
        now = time.time()
        for f in self._dir.glob("*.json"):
            try:
                data = json.loads(f.read_text())
                if data.get("is_leader") and now - data.get("timestamp", 0) <= self._stale:
                    leaders.append(data)
            except (json.JSONDecodeError, OSError):
                pass
        return leaders


# ---------------------------------------------------------------------------
# Graceful Shutdown
# ---------------------------------------------------------------------------

class GracefulShutdown:
    """
    Coordinate graceful shutdown: drain connections, finalize pending kills,
    then exit cleanly.

    Usage:
        gs = GracefulShutdown()
        gs.register_drain_callback(my_drain_fn)
        gs.install_signal_handlers()
        # ... run server ...
        gs.shutdown()  # or triggered by SIGTERM/SIGINT
    """

    def __init__(self, drain_timeout: float = 30.0):
        self._drain_timeout = drain_timeout
        self._drain_callbacks: List[Callable[[], None]] = []
        self._finalizers: List[Callable[[], None]] = []
        self._shutting_down = False
        self._lock = threading.Lock()
        self._shutdown_event = threading.Event()

    @property
    def is_shutting_down(self) -> bool:
        return self._shutting_down

    def register_drain_callback(self, fn: Callable[[], None]) -> None:
        """Register a callback to drain active connections/sessions."""
        self._drain_callbacks.append(fn)

    def register_finalizer(self, fn: Callable[[], None]) -> None:
        """Register a callback to finalize pending operations (e.g. kills)."""
        self._finalizers.append(fn)

    def install_signal_handlers(self) -> None:
        """Install SIGTERM and SIGINT handlers."""
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

    def shutdown(self, reason: str = "manual") -> None:
        """Execute graceful shutdown sequence."""
        with self._lock:
            if self._shutting_down:
                return
            self._shutting_down = True

        logger.info("Graceful shutdown initiated: %s", reason)

        # 1. Drain connections
        for cb in self._drain_callbacks:
            try:
                cb()
            except Exception:
                logger.exception("Drain callback error")

        # 2. Finalize pending kills
        for fn in self._finalizers:
            try:
                fn()
            except Exception:
                logger.exception("Finalizer error")

        self._shutdown_event.set()
        logger.info("Graceful shutdown complete")

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Block until shutdown is complete."""
        return self._shutdown_event.wait(timeout=timeout or self._drain_timeout + 5)

    def _signal_handler(self, signum: int, frame: Any) -> None:
        sig_name = signal.Signals(signum).name
        logger.info("Received %s, initiating shutdown", sig_name)
        self.shutdown(reason=f"signal:{sig_name}")


# ---------------------------------------------------------------------------
# Health Check Aggregation
# ---------------------------------------------------------------------------

class HealthAggregator:
    """
    Combine subcomponent health checks into a single aggregated status.

    Usage:
        agg = HealthAggregator(node_id="node-1")
        agg.register_check("database", db_ping_fn)
        agg.register_check("redis", redis_ping_fn)
        status = agg.check_all()
    """

    def __init__(self, node_id: Optional[str] = None):
        self._node_id = node_id or f"{socket.gethostname()}-{os.getpid()}"
        self._checks: Dict[str, Callable[[], HealthCheck]] = {}

    def register_check(self, name: str,
                       fn: Callable[[], HealthCheck]) -> None:
        """Register a health check function for a subcomponent."""
        self._checks[name] = fn

    def check_all(self) -> AggregatedHealth:
        """Run all registered checks and return aggregated status."""
        results: List[HealthCheck] = []
        for name, fn in self._checks.items():
            try:
                start = time.time()
                hc = fn()
                hc.latency_ms = (time.time() - start) * 1000
                results.append(hc)
            except Exception as e:
                results.append(HealthCheck(
                    name=name,
                    status=ComponentStatus.UNHEALTHY.value,
                    message=str(e),
                ))

        # Aggregate: worst status wins
        priority = {
            ComponentStatus.UNHEALTHY.value: 0,
            ComponentStatus.DEGRADED.value: 1,
            ComponentStatus.UNKNOWN.value: 2,
            ComponentStatus.HEALTHY.value: 3,
        }
        if results:
            worst = min(results, key=lambda c: priority.get(c.status, 2))
            overall = worst.status
        else:
            overall = ComponentStatus.UNKNOWN.value

        return AggregatedHealth(
            overall_status=overall,
            checks=results,
            node_id=self._node_id,
        )


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

_leader_election: Optional[LeaderElection] = None
_shutdown: Optional[GracefulShutdown] = None
_aggregator: Optional[HealthAggregator] = None


def get_leader_election(**kwargs) -> LeaderElection:
    global _leader_election
    if _leader_election is None:
        _leader_election = LeaderElection(**kwargs)
    return _leader_election


def get_shutdown(**kwargs) -> GracefulShutdown:
    global _shutdown
    if _shutdown is None:
        _shutdown = GracefulShutdown(**kwargs)
    return _shutdown


def get_aggregator(**kwargs) -> HealthAggregator:
    global _aggregator
    if _aggregator is None:
        _aggregator = HealthAggregator(**kwargs)
    return _aggregator


def reset_singletons() -> None:
    global _leader_election, _shutdown, _aggregator
    _leader_election = None
    _shutdown = None
    _aggregator = None
