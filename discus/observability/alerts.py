"""
RTA-GUARD Observability — Alerting System

Evaluates alert rules against analytics and fires notifications
via webhooks, Slack, or email when thresholds are breached.
"""
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("discus.observability.alerts")


class AlertCondition(Enum):
    KILL_RATE_ABOVE = "kill_rate_above"
    WARN_RATE_ABOVE = "warn_rate_above"
    VIOLATIONS_PER_MINUTE = "violations_per_minute"
    NEW_VIOLATION_TYPE = "new_violation_type"
    SESSION_COUNT_SPIKE = "session_count_spike"
    DURATION_ABOVE = "duration_above"


class AlertChannel(Enum):
    WEBHOOK = "webhook"
    LOG = "log"
    CALLBACK = "callback"


@dataclass
class AlertRule:
    """A rule that triggers alerts when conditions are met."""
    rule_id: str
    name: str
    condition: AlertCondition
    threshold: float
    channels: List[AlertChannel] = field(default_factory=lambda: [AlertChannel.LOG])
    cooldown_seconds: int = 300  # Don't re-fire for 5 minutes
    enabled: bool = True
    tenant_id: str = ""
    webhook_url: str = ""
    message_template: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "condition": self.condition.value,
            "threshold": self.threshold,
            "channels": [c.value for c in self.channels],
            "cooldown_seconds": self.cooldown_seconds,
            "enabled": self.enabled,
            "tenant_id": self.tenant_id,
        }


@dataclass
class AlertEvent:
    """A fired alert."""
    alert_id: str
    rule_id: str
    rule_name: str
    condition: str
    threshold: float
    actual_value: float
    message: str
    timestamp: float = field(default_factory=time.time)
    tenant_id: str = ""
    acknowledged: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_id": self.alert_id,
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "condition": self.condition,
            "threshold": self.threshold,
            "actual_value": self.actual_value,
            "message": self.message,
            "timestamp": self.timestamp,
            "tenant_id": self.tenant_id,
            "acknowledged": self.acknowledged,
        }


class AlertManager:
    """
    Manages alert rules and fires notifications.

    Usage:
        manager = AlertManager()
        manager.add_rule(AlertRule(
            rule_id="high-kill-rate",
            name="High Kill Rate",
            condition=AlertCondition.KILL_RATE_ABOVE,
            threshold=0.05,
            channels=[AlertChannel.LOG],
        ))
        fired = manager.evaluate(stats)
    """

    def __init__(self):
        self._rules: Dict[str, AlertRule] = {}
        self._history: List[AlertEvent] = []
        self._last_fired: Dict[str, float] = {}  # rule_id -> last fire time
        self._callbacks: List[Callable] = []
        self._known_violation_types: set = set()

    def add_rule(self, rule: AlertRule) -> None:
        self._rules[rule.rule_id] = rule

    def remove_rule(self, rule_id: str) -> bool:
        return self._rules.pop(rule_id, None) is not None

    def get_rule(self, rule_id: str) -> Optional[AlertRule]:
        return self._rules.get(rule_id)

    def list_rules(self) -> List[AlertRule]:
        return list(self._rules.values())

    def evaluate(self, stats: Dict[str, Any],
                 tenant_id: str = "") -> List[AlertEvent]:
        """Evaluate all rules against current stats."""
        fired = []
        now = time.time()

        for rule in self._rules.values():
            if not rule.enabled:
                continue
            if rule.tenant_id and rule.tenant_id != tenant_id:
                continue

            # Check cooldown
            last = self._last_fired.get(rule.rule_id, 0)
            if now - last < rule.cooldown_seconds:
                continue

            # Evaluate condition
            event = self._evaluate_rule(rule, stats, now)
            if event:
                fired.append(event)
                self._history.append(event)
                self._last_fired[rule.rule_id] = now
                self._fire_notifications(event, rule)

        return fired

    def _evaluate_rule(self, rule: AlertRule, stats: Dict[str, Any],
                       now: float) -> Optional[AlertEvent]:
        """Evaluate a single rule."""
        actual = 0.0
        triggered = False

        if rule.condition == AlertCondition.KILL_RATE_ABOVE:
            actual = stats.get("kill_rate", 0)
            triggered = actual > rule.threshold

        elif rule.condition == AlertCondition.WARN_RATE_ABOVE:
            actual = stats.get("warn_rate", 0)
            triggered = actual > rule.threshold

        elif rule.condition == AlertCondition.VIOLATIONS_PER_MINUTE:
            total = stats.get("total_kills", 0) + stats.get("total_warns", 0)
            checks = stats.get("total_checks", 0)
            # Rough estimate
            actual = total
            triggered = actual > rule.threshold

        elif rule.condition == AlertCondition.NEW_VIOLATION_TYPE:
            types = set(stats.get("violations_by_type", {}).keys())
            new_types = types - self._known_violation_types
            self._known_violation_types.update(types)
            if new_types:
                actual = len(new_types)
                triggered = True

        elif rule.condition == AlertCondition.DURATION_ABOVE:
            actual = stats.get("avg_duration_ms", 0)
            triggered = actual > rule.threshold

        if triggered:
            import hashlib
            alert_id = hashlib.sha256(
                f"{rule.rule_id}:{now}".encode()
            ).hexdigest()[:16]

            message = rule.message_template or (
                f"Alert: {rule.name} — {rule.condition.value} = {actual:.3f} "
                f"(threshold: {rule.threshold})"
            )

            return AlertEvent(
                alert_id=alert_id,
                rule_id=rule.rule_id,
                rule_name=rule.name,
                condition=rule.condition.value,
                threshold=rule.threshold,
                actual_value=actual,
                message=message,
                timestamp=now,
                tenant_id=rule.tenant_id,
            )

        return None

    def _fire_notifications(self, event: AlertEvent, rule: AlertRule):
        """Send notifications through configured channels."""
        for channel in rule.channels:
            try:
                if channel == AlertChannel.LOG:
                    logger.warning(f"🚨 ALERT: {event.message}")
                elif channel == AlertChannel.CALLBACK:
                    for cb in self._callbacks:
                        cb(event)
                elif channel == AlertChannel.WEBHOOK:
                    # Webhook firing would use httpx in production
                    logger.info(f"Webhook alert: {rule.webhook_url} — {event.message}")
            except Exception as e:
                logger.error(f"Alert notification error: {e}")

    def on_alert(self, callback: Callable):
        """Register a callback for alert events."""
        self._callbacks.append(callback)

    def get_history(self, limit: int = 100,
                    rule_id: Optional[str] = None) -> List[AlertEvent]:
        """Get alert history."""
        history = self._history
        if rule_id:
            history = [e for e in history if e.rule_id == rule_id]
        return sorted(history, key=lambda e: e.timestamp, reverse=True)[:limit]

    def acknowledge(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        for event in self._history:
            if event.alert_id == alert_id:
                event.acknowledged = True
                return True
        return False

    def get_stats(self) -> Dict[str, Any]:
        return {
            "rules_count": len(self._rules),
            "enabled_rules": sum(1 for r in self._rules.values() if r.enabled),
            "total_alerts_fired": len(self._history),
            "unacknowledged": sum(1 for e in self._history if not e.acknowledged),
        }
