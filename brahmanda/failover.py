"""
RTA-GUARD — Failover Orchestration (Phase 6.5)

Automatic and manual failover between primary and secondary regions.
Includes failback logic and full failover history for audit.
"""

from __future__ import annotations

import json
import threading
import time
import logging
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class FailoverState(Enum):
    PRIMARY_ACTIVE = "primary_active"
    FAILOVER_IN_PROGRESS = "failover_in_progress"
    SECONDARY_ACTIVE = "secondary_active"
    FAILBACK_IN_PROGRESS = "failback_in_progress"
    DEGRADED = "degraded"


class FailoverTrigger(Enum):
    AUTOMATIC = "automatic"
    MANUAL = "manual"
    SCHEDULED = "scheduled"


@dataclass
class FailoverEvent:
    """A recorded failover/failback event."""
    event_id: str
    trigger: str  # FailoverTrigger value
    from_region: str
    to_region: str
    reason: str = ""
    started_at: float = 0.0
    completed_at: Optional[float] = None
    success: bool = False
    error: Optional[str] = None

    def __post_init__(self):
        if not self.started_at:
            self.started_at = time.time()

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FailoverConfig:
    """Configuration for failover behaviour."""
    primary_region: str = "us-east-1"
    secondary_region: str = "us-west-2"
    health_check_interval: float = 10.0
    failure_threshold: int = 3
    auto_failback: bool = True
    failback_delay: float = 60.0  # seconds to wait before failback
    history_path: Optional[str] = None


# ---------------------------------------------------------------------------
# Failover Orchestrator
# ---------------------------------------------------------------------------

class FailoverOrchestrator:
    """
    Manages automatic and manual failover between regions.

    Automatic failover: monitors health, triggers on consecutive failures.
    Manual failover: exposes promote()/failback() for admin use.
    History: every transition is logged to disk for audit.

    Usage:
        cfg = FailoverConfig(primary_region="us-east-1", secondary_region="us-west-2")
        orch = FailoverOrchestrator(cfg)
        orch.register_health_check(my_health_fn)
        orch.start_monitoring()
        # ... later ...
        # Manual failover:
        orch.manual_failover(reason="planned maintenance")
        # Or manual failback:
        orch.manual_failback()
    """

    def __init__(self, config: Optional[FailoverConfig] = None):
        self._cfg = config or FailoverConfig()
        self._state = FailoverState.PRIMARY_ACTIVE
        self._active_region = self._cfg.primary_region
        self._health_fn: Optional[Callable[[], bool]] = None
        self._on_failover: List[Callable[[FailoverEvent], None]] = []
        self._on_failback: List[Callable[[FailoverEvent], None]] = []
        self._history: List[FailoverEvent] = []
        self._history_path: Optional[Path] = None
        if self._cfg.history_path:
            self._history_path = Path(self._cfg.history_path)
            self._history_path.mkdir(parents=True, exist_ok=True)
        self._consecutive_failures = 0
        self._lock = threading.Lock()
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = False
        self._load_history()

    @property
    def state(self) -> FailoverState:
        return self._state

    @property
    def active_region(self) -> str:
        return self._active_region

    @property
    def is_on_secondary(self) -> bool:
        return self._state in (
            FailoverState.SECONDARY_ACTIVE,
            FailoverState.FAILOVER_IN_PROGRESS,
        )

    def register_health_check(self, fn: Callable[[], bool]) -> None:
        """Register health check function (returns True if healthy)."""
        self._health_fn = fn

    def on_failover(self, fn: Callable[[FailoverEvent], None]) -> None:
        """Register callback invoked on failover."""
        self._on_failover.append(fn)

    def on_failback(self, fn: Callable[[FailoverEvent], None]) -> None:
        """Register callback invoked on failback."""
        self._on_failback.append(fn)

    def start_monitoring(self) -> None:
        """Start background health monitoring for automatic failover."""
        if self._running:
            return
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="failover-monitor"
        )
        self._monitor_thread.start()
        logger.info("Failover monitoring started (primary=%s)",
                     self._cfg.primary_region)

    def stop_monitoring(self) -> None:
        """Stop background monitoring."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)

    def manual_failover(self, reason: str = "manual") -> FailoverEvent:
        """
        Admin-initiated controlled failover to secondary.
        Returns the FailoverEvent.
        """
        with self._lock:
            if self._state == FailoverState.SECONDARY_ACTIVE:
                logger.info("Already on secondary, skipping failover")
                return self._history[-1] if self._history else self._noop_event()

            self._state = FailoverState.FAILOVER_IN_PROGRESS
            logger.warning("Manual failover initiated: %s", reason)

        event = FailoverEvent(
            event_id=self._next_id(),
            trigger=FailoverTrigger.MANUAL.value,
            from_region=self._cfg.primary_region,
            to_region=self._cfg.secondary_region,
            reason=reason,
        )
        return self._execute_failover(event)

    def manual_failback(self, reason: str = "manual") -> FailoverEvent:
        """
        Admin-initiated controlled failback to primary.
        Returns the FailoverEvent.
        """
        with self._lock:
            if self._state == FailoverState.PRIMARY_ACTIVE:
                logger.info("Already on primary, skipping failback")
                return self._history[-1] if self._history else self._noop_event()

            self._state = FailoverState.FAILBACK_IN_PROGRESS
            logger.info("Manual failback initiated: %s", reason)

        event = FailoverEvent(
            event_id=self._next_id(),
            trigger=FailoverTrigger.MANUAL.value,
            from_region=self._cfg.secondary_region,
            to_region=self._cfg.primary_region,
            reason=reason,
        )
        return self._execute_failback(event)

    def get_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent failover history."""
        return [e.to_dict() for e in self._history[-limit:]]

    def get_status(self) -> Dict[str, Any]:
        return {
            "state": self._state.value,
            "active_region": self._active_region,
            "primary": self._cfg.primary_region,
            "secondary": self._cfg.secondary_region,
            "consecutive_failures": self._consecutive_failures,
            "auto_failback": self._cfg.auto_failback,
            "history_count": len(self._history),
        }

    # -- internals --

    def _monitor_loop(self) -> None:
        while self._running:
            time.sleep(self._cfg.health_check_interval)
            if self._health_fn is None:
                continue

            try:
                healthy = self._health_fn()
            except Exception as e:
                logger.exception("Health check error")
                healthy = False

            with self._lock:
                if not healthy:
                    self._consecutive_failures += 1
                    if (self._consecutive_failures >= self._cfg.failure_threshold
                            and self._state == FailoverState.PRIMARY_ACTIVE):
                        logger.warning(
                            "Primary unhealthy (%d failures), triggering auto failover",
                            self._consecutive_failures,
                        )
                        self._state = FailoverState.FAILOVER_IN_PROGRESS
                        # Release lock before executing
                        break
                else:
                    self._consecutive_failures = 0
                    if (self._state == FailoverState.SECONDARY_ACTIVE
                            and self._cfg.auto_failback):
                        logger.info("Primary healthy again, scheduling failback")
                        threading.Timer(
                            self._cfg.failback_delay,
                            self._auto_failback,
                        ).start()

        # Auto failover outside lock
        if self._state == FailoverState.FAILOVER_IN_PROGRESS:
            event = FailoverEvent(
                event_id=self._next_id(),
                trigger=FailoverTrigger.AUTOMATIC.value,
                from_region=self._cfg.primary_region,
                to_region=self._cfg.secondary_region,
                reason=f"{self._consecutive_failures} consecutive health check failures",
            )
            self._execute_failover(event)

    def _auto_failback(self) -> None:
        with self._lock:
            if self._state != FailoverState.SECONDARY_ACTIVE:
                return
            self._state = FailoverState.FAILBACK_IN_PROGRESS

        event = FailoverEvent(
            event_id=self._next_id(),
            trigger=FailoverTrigger.AUTOMATIC.value,
            from_region=self._cfg.secondary_region,
            to_region=self._cfg.primary_region,
            reason="primary recovered, auto-failback",
        )
        self._execute_failback(event)

    def _execute_failover(self, event: FailoverEvent) -> FailoverEvent:
        try:
            self._active_region = self._cfg.secondary_region
            with self._lock:
                self._state = FailoverState.SECONDARY_ACTIVE
            event.completed_at = time.time()
            event.success = True
            logger.warning("Failover complete: %s → %s",
                           event.from_region, event.to_region)
            for cb in self._on_failover:
                try:
                    cb(event)
                except Exception:
                    logger.exception("Failover callback error")
        except Exception as e:
            event.error = str(e)
            event.completed_at = time.time()
            with self._lock:
                self._state = FailoverState.DEGRADED
            logger.exception("Failover failed")
        self._record_event(event)
        return event

    def _execute_failback(self, event: FailoverEvent) -> FailoverEvent:
        try:
            self._active_region = self._cfg.primary_region
            with self._lock:
                self._state = FailoverState.PRIMARY_ACTIVE
                self._consecutive_failures = 0
            event.completed_at = time.time()
            event.success = True
            logger.info("Failback complete: %s → %s",
                        event.from_region, event.to_region)
            for cb in self._on_failback:
                try:
                    cb(event)
                except Exception:
                    logger.exception("Failback callback error")
        except Exception as e:
            event.error = str(e)
            event.completed_at = time.time()
            logger.exception("Failback failed")
        self._record_event(event)
        return event

    def _record_event(self, event: FailoverEvent) -> None:
        with self._lock:
            self._history.append(event)
        if self._history_path:
            try:
                path = self._history_path / f"{event.event_id}.json"
                path.write_text(json.dumps(event.to_dict(), indent=2))
            except OSError:
                logger.exception("Failed to persist failover event")

    def _load_history(self) -> None:
        if not self._history_path or not self._history_path.exists():
            return
        for f in sorted(self._history_path.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                self._history.append(FailoverEvent(**data))
            except (json.JSONDecodeError, TypeError):
                pass

    def _next_id(self) -> str:
        import uuid
        return f"fo-{uuid.uuid4().hex[:12]}"

    def _noop_event(self) -> FailoverEvent:
        return FailoverEvent(
            event_id="noop",
            trigger=FailoverTrigger.MANUAL.value,
            from_region=self._active_region,
            to_region=self._active_region,
            reason="no-op: already in requested state",
            success=True,
            completed_at=time.time(),
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_orchestrator: Optional[FailoverOrchestrator] = None


def get_orchestrator(**kwargs) -> FailoverOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = FailoverOrchestrator(**kwargs)
    return _orchestrator


def reset_orchestrator() -> None:
    global _orchestrator
    if _orchestrator:
        _orchestrator.stop_monitoring()
    _orchestrator = None
