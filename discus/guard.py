"""
RTA-GUARD Discus — Core Kill-Switch Guard

The main class that wraps your AI app and adds deterministic session termination.
"""
import asyncio
import json
import logging
import os
import time
from typing import Optional, Callable, Any
from datetime import datetime

import httpx

from .models import (
    GuardConfig, GuardResponse, SessionEvent,
    KillDecision, Severity, ViolationType
)
from .rules import RuleEngine
from .rta_engine import RtaEngine, RtaContext

logger = logging.getLogger("discus")

# Phase 6.2: Prometheus metrics (opt-in, backward compatible)
_metrics_enabled = os.getenv("METRICS_ENABLED", "false").lower() == "true"
try:
    from brahmanda.metrics import (
        record_kill, record_check, record_violation, record_webhook,
        set_active_sessions, observe_check_duration, observe_kill_decision_time,
        init_metrics,
    )
    if _metrics_enabled:
        init_metrics()
except ImportError:
    _metrics_enabled = False
    logger.debug("brahanda.metrics not available — metrics disabled")


class SessionKilledError(Exception):
    """Raised when a session is killed by the guard."""
    def __init__(self, event: SessionEvent):
        self.event = event
        super().__init__(f"Session killed: {event.violation_type} — {event.details}")


class DiscusGuard:
    """
    The RTA-GUARD kill-switch.

    Usage:
        guard = DiscusGuard()

        # Check input before sending to LLM
        try:
            response = guard.check_and_forward("user input", session_id="abc123")
            # If we get here, input was safe — forward to your LLM
        except SessionKilledError as e:
            # Session was killed — show error to user
            print(f"Blocked: {e.event.details}")
    """

    def __init__(self, config: Optional[GuardConfig] = None, rta_engine: Optional[RtaEngine] = None,
                 user_tracker: Optional[Any] = None, escalation_chain: Optional[Any] = None,
                 webhook_manager: Optional[Any] = None, sla_tracker: Optional[Any] = None,
                 plugin_manager: Optional[Any] = None, memory_manager: Optional[Any] = None):
        self.config = config or GuardConfig()
        self.rule_engine = RuleEngine(self.config, self.config.pii_patterns_yaml)
        self.rta_engine = rta_engine  # RTA constitutional engine (optional)
        self.user_tracker = user_tracker  # UserBehaviorTracker (optional, Phase 3.5)
        self.escalation_chain = escalation_chain  # EscalationChain (optional, Phase 3.6)
        self.webhook_manager = webhook_manager  # WebhookManager (optional, Phase 4.4)
        self.sla_tracker = sla_tracker  # SLATracker (optional, Phase 4.8)
        self.plugin_manager = plugin_manager  # PluginManager (optional, Phase 9)
        self.memory_manager = memory_manager  # MemoryManager (optional, Phase 13)
        self._event_log: list[SessionEvent] = []
        self._on_kill_callbacks: list[Callable] = []
        self._killed_sessions: set[str] = set()
        logger.info("DiscusGuard initialized" + (" with RTA" if rta_engine else "")
                     + (" with user tracking" if user_tracker else "")
                     + (" with escalation" if escalation_chain else "")
                     + (" with webhooks" if webhook_manager else "")
                     + (" with SLA monitoring" if sla_tracker else "")
                     + (" with plugins" if plugin_manager else "")
                     + (" with memory" if memory_manager else ""))

    def on_kill(self, callback: Callable[[SessionEvent], None]):
        """Register a callback for when a session is killed."""
        self._on_kill_callbacks.append(callback)

    def check(self, text: str, session_id: str = "default", user_id: str = "", agent_role: str = None, check_output: bool = False) -> GuardResponse:
        """
        Check input text against all constitutional rules.

        Args:
            text: Input text to check
            session_id: Session identifier
            user_id: User identifier (for behavior tracking)
            agent_role: Agent role for R2/R5 checks (e.g., 'coding_agent', 'support_agent')
            check_output: If True, only check for PII (skip destructive/role checks)

        Returns:
            GuardResponse with allowed=True/False.
            Raises SessionKilledError if kill threshold is met.
        """
        _check_start = time.monotonic() if _metrics_enabled else None

        # Phase 9: Plugin hooks — ON_INPUT
        plugin_results = []
        if self.plugin_manager:
            try:
                from discus.plugins import PluginHook, PluginContext
                pctx = PluginContext(session_id=session_id, input_text=text)
                plugin_results = self.plugin_manager.run_hooks(PluginHook.ON_INPUT, pctx)
                for pr in plugin_results:
                    if pr.should_kill:
                        event = SessionEvent(
                            session_id=session_id,
                            input_text=text[:200],
                            violation_type=f"plugin:{pr.plugin_id}",
                            severity=Severity.HIGH,
                            decision=KillDecision.KILL,
                            details=pr.message
                        )
                        self._log_event(event)
                        self._killed_sessions.add(session_id)
                        self._fire_on_kill(event)
                        logger.warning(f"🛑 SESSION KILLED by plugin [{session_id}]: {pr.message}")
                        raise SessionKilledError(event)
                    elif pr.should_warn:
                        logger.info(f"⚠️ Plugin warning [{session_id}]: {pr.message}")
            except SessionKilledError:
                raise
            except Exception as e:
                logger.debug(f"Plugin hook error (on_input): {e}")

        # Phase 3.5: User behavior tracking — record before processing
        user_signals = []
        user_risk_kill = False
        if self.user_tracker and user_id:
            try:
                user_signals = self.user_tracker.record_request(user_id, text)
                # Check if user is adversarial — factor into kill decision
                if self.user_tracker.is_adversarial(user_id):
                    user_risk_kill = True
                    logger.warning(f"⚠️ Adversarial user detected: {user_id} "
                                   f"(risk={self.user_tracker.get_user_risk_score(user_id):.2f})")
            except Exception as e:
                logger.debug(f"User tracker error: {e}")

        # Phase 13: Conversation memory — add message and run multi-turn analysis
        if self.memory_manager and text:
            try:
                self.memory_manager.add_user_message(session_id, text)
                mt_result = self.memory_manager.analyze(session_id)
                if mt_result.should_kill:
                    event = SessionEvent(
                        session_id=session_id,
                        input_text=text[:200],
                        decision=KillDecision.KILL,
                        violation_type="multi_turn_attack",
                        details=f"Multi-turn analysis: {mt_result.violations}",
                    )
                    self._log_event(event)
                    self._killed_sessions.add(session_id)
                    self._fire_on_kill(event)
                    logger.warning(f"🛑 SESSION KILLED by multi-turn analysis [{session_id}]: {mt_result.violations}")
                    raise SessionKilledError(event)
                elif mt_result.should_warn:
                    logger.info(f"⚠️ Multi-turn warning [{session_id}]: score={mt_result.risk_score:.2f}")
            except SessionKilledError:
                raise
            except Exception as e:
                logger.debug(f"Memory manager error: {e}")

        # Check if session is already killed
        if session_id in self._killed_sessions:
            event = SessionEvent(
                session_id=session_id,
                input_text=text[:200],  # Truncate for logging
                decision=KillDecision.KILL,
                details="Session already killed — blocked attempt to continue"
            )
            self._log_event(event)
            raise SessionKilledError(event)

        # Layer 1: Pattern-based rules (fast)
        pattern_result = self.rule_engine.evaluate(text, agent_role=agent_role, check_output=check_output)

        if pattern_result is not None:
            violation_type, severity, details = pattern_result
            # Decide: kill or warn based on severity threshold
            severity_order = [Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]
            threshold_idx = severity_order.index(self.config.kill_threshold)
            severity_idx = severity_order.index(severity)

            if severity_idx >= threshold_idx:
                # KILL
                event = SessionEvent(
                    session_id=session_id,
                    input_text=text[:200],
                    violation_type=violation_type,
                    severity=severity,
                    decision=KillDecision.KILL,
                    details=details
                )
                self._log_event(event)
                self._killed_sessions.add(session_id)
                self._fire_on_kill(event)
                self._fire_webhook(event)

                # Phase 6.2: Metrics
                if _metrics_enabled:
                    record_kill()
                    record_check("kill")
                    record_violation(severity.value.lower())
                    observe_check_duration(time.monotonic() - _check_start)
                    observe_kill_decision_time(time.monotonic() - _check_start)
                    set_active_sessions(len(self._killed_sessions))  # approximation

                logger.warning(f"🛑 SESSION KILLED [{session_id}]: {details}")
                raise SessionKilledError(event)
            else:
                # WARN
                event = SessionEvent(
                    session_id=session_id,
                    input_text=text[:200],
                    violation_type=violation_type,
                    severity=severity,
                    decision=KillDecision.WARN,
                    details=f"Warning: {details}"
                )
                self._log_event(event)
                self._fire_webhook(event)

                # Phase 6.2: Metrics
                if _metrics_enabled:
                    record_check("warn")
                    record_violation(severity.value.lower())
                    observe_check_duration(time.monotonic() - _check_start)

                logger.info(f"⚠️ Warning [{session_id}]: {details}")
                return GuardResponse(
                    allowed=True,
                    session_id=session_id,
                    event=event,
                    message=f"Warning: {details}"
                )

        # Layer 2: RTA constitutional rules (deep) — if configured
        if self.rta_engine:
            # Build RTA context from current state
            previous_inputs = [e.input_text for e in self._event_log if e.session_id == session_id][-10:]
            previous_outputs = []  # We'd need to capture assistant outputs in the log; TODO
            context = RtaContext(
                session_id=session_id,
                input_text=text,
                previous_inputs=previous_inputs,
                previous_outputs=previous_outputs,
                llm_provider=getattr(self.config, "llm_provider", None),
                model=getattr(self.config, "model", None)
            )

            allowed, results, decision = self.rta_engine.check(context)

            if not allowed and decision == KillDecision.KILL:
                # Find the highest priority violation
                violation = next((r for r in results if r.is_violation and r.decision == KillDecision.KILL), None)
                if violation:
                    event = violation.to_event(session_id, text)
                    self._log_event(event)
                    self._killed_sessions.add(session_id)
                    self._fire_on_kill(event)
                    self._fire_webhook(event)

                    # Phase 6.2: Metrics
                    if _metrics_enabled:
                        record_kill()
                        record_check("kill")
                        record_violation("critical")
                        observe_kill_decision_time(time.monotonic() - _check_start)

                    logger.warning(f"🛑 SESSION KILLED (RTA) [{session_id}]: {violation.details}")
                    raise SessionKilledError(event)
            elif decision == KillDecision.WARN:
                # RTA warning — do not block, but log and optionally return message
                warning_results = [r for r in results if r.is_violation and r.decision == KillDecision.WARN]
                if warning_results:
                    # Combine warnings
                    details = "; ".join(r.details for r in warning_results)
                    event = SessionEvent(
                        session_id=session_id,
                        input_text=text[:200],
                        violation_type=ViolationType.CUSTOM,
                        severity=Severity.MEDIUM,
                        decision=KillDecision.WARN,
                        details=f"RTA Warnings: {details}"
                    )
                    self._log_event(event)
                    logger.info(f"⚠️ RTA Warning [{session_id}]: {details}")
                    return GuardResponse(
                        allowed=True,
                        session_id=session_id,
                        event=event,
                        message=f"RTA Warning: {details}"
                    )

        # Phase 3.5: Kill session if user is adversarial and has injection signals
        if user_risk_kill and user_signals:
            injection_signals = [s for s in user_signals if s.category.value == "injection_attempt"]
            if injection_signals:
                details = (f"Adversarial user {user_id}: "
                           f"risk={self.user_tracker.get_user_risk_score(user_id):.2f}, "
                           f"{len(injection_signals)} injection signal(s)")
                event = SessionEvent(
                    session_id=session_id,
                    input_text=text[:200],
                    violation_type=ViolationType.PROMPT_INJECTION,
                    severity=Severity.HIGH,
                    decision=KillDecision.KILL,
                    details=details,
                )
                self._log_event(event)
                self._killed_sessions.add(session_id)
                self._fire_on_kill(event)
                self._fire_webhook(event)

                # Phase 6.2: Metrics
                if _metrics_enabled:
                    record_kill()
                    record_check("kill")
                    record_violation("high")
                    observe_kill_decision_time(time.monotonic() - _check_start)

                logger.warning(f"🛑 SESSION KILLED (adversarial user) [{session_id}]: {details}")
                raise SessionKilledError(event)

        # Phase 3.6: Escalation protocol evaluation
        if self.escalation_chain:
            try:
                from brahmanda.escalation import EscalationChain, EscalationLevel
                signals = {
                    "drift_score": 0.0,
                    "tamas_state": "sattva",
                    "consistency_level": "highly_consistent",
                    "user_risk_score": 0.0,
                    "violation_rate": 0.0,
                }
                # Get user risk from tracker if available
                if self.user_tracker and user_id:
                    signals["user_risk_score"] = self.user_tracker.get_user_risk_score(user_id)
                # Get violation rate from event log
                session_events = [e for e in self._event_log if e.session_id == session_id]
                if session_events:
                    violations = [e for e in session_events if e.decision.value in ("kill", "warn")]
                    signals["violation_rate"] = len(violations) / len(session_events)
                decision = self.escalation_chain.evaluate(signals, session_id=session_id)
                if decision.level == EscalationLevel.KILL:
                    details = f"Escalation KILL: {'; '.join(decision.reasons)}"
                    event = SessionEvent(
                        session_id=session_id,
                        input_text=text[:200],
                        violation_type=ViolationType.CUSTOM,
                        severity=Severity.CRITICAL,
                        decision=KillDecision.KILL,
                        details=details,
                    )
                    self._log_event(event)
                    self._killed_sessions.add(session_id)
                    self._fire_on_kill(event)
                    self._fire_webhook(event)

                    # Phase 6.2: Metrics
                    if _metrics_enabled:
                        record_kill()
                        record_check("kill")
                        record_violation("critical")
                        observe_kill_decision_time(time.monotonic() - _check_start)

                    logger.warning(f"🛑 SESSION KILLED (escalation) [{session_id}]: {details}")
                    raise SessionKilledError(event)
                elif decision.level >= EscalationLevel.ALERT:
                    details = f"Escalation ALERT: {'; '.join(decision.reasons)}"
                    event = SessionEvent(
                        session_id=session_id,
                        input_text=text[:200],
                        violation_type=ViolationType.CUSTOM,
                        severity=Severity.HIGH,
                        decision=KillDecision.KILL,
                        details=details,
                    )
                    self._log_event(event)
                    self._killed_sessions.add(session_id)
                    self._fire_on_kill(event)
                    self._fire_webhook(event)

                    # Phase 6.2: Metrics
                    if _metrics_enabled:
                        record_kill()
                        record_check("kill")
                        record_violation("high")
                        observe_kill_decision_time(time.monotonic() - _check_start)

                    logger.warning(f"🛑 SESSION KILLED (escalation alert) [{session_id}]: {details}")
                    raise SessionKilledError(event)
            except SessionKilledError:
                raise
            except Exception as e:
                logger.debug(f"Escalation evaluation error: {e}")

        # No violations — pass
        event = SessionEvent(
            session_id=session_id,
            input_text=text[:200],
            decision=KillDecision.PASS,
            details="Passed all checks"
        )
        if self.config.log_all:
            self._log_event(event)

        # Phase 6.2: Metrics
        if _metrics_enabled:
            record_check("pass")
            observe_check_duration(time.monotonic() - _check_start)
            set_active_sessions(len(self._killed_sessions))  # approximation

        return GuardResponse(allowed=True, session_id=session_id, event=event)

    def check_and_forward(
        self,
        text: str,
        session_id: str = "default",
        user_id: str = "",
        llm_fn: Optional[Callable[[str], str]] = None
    ) -> str:
        """
        Check input, then forward to LLM if safe.

        Args:
            text: User input
            session_id: Session identifier
            user_id: User identifier (for behavior tracking)
            llm_fn: Function that calls the LLM (takes text, returns response)

        Returns:
            LLM response if safe

        Raises:
            SessionKilledError if violation detected
        """
        self.check(text, session_id, user_id=user_id)

        if llm_fn:
            return llm_fn(text)
        return "Input passed all checks (no LLM function provided)"

    def kill_session(self, session_id: str, reason: str = "Manual kill"):
        """Manually kill a session."""
        event = SessionEvent(
            session_id=session_id,
            input_text="[MANUAL KILL]",
            decision=KillDecision.KILL,
            details=reason
        )
        self._log_event(event)
        self._killed_sessions.add(session_id)
        self._fire_on_kill(event)
        self._fire_webhook(event)
        logger.warning(f"🛑 SESSION MANUALLY KILLED [{session_id}]: {reason}")

    def is_session_alive(self, session_id: str) -> bool:
        """Check if a session is still alive."""
        return session_id not in self._killed_sessions

    def get_events(self, session_id: Optional[str] = None) -> list[SessionEvent]:
        """Get logged events, optionally filtered by session."""
        if session_id:
            return [e for e in self._event_log if e.session_id == session_id]
        return self._event_log.copy()

    def get_killed_sessions(self) -> set[str]:
        """Get set of killed session IDs."""
        return self._killed_sessions.copy()

    def reset_session(self, session_id: str):
        """Reset a killed session (allow it to be used again)."""
        self._killed_sessions.discard(session_id)
        logger.info(f"Session reset: {session_id}")

    # --- Dynamic Pattern Management ---

    def add_pattern(self, name: str, pattern: str):
        """Add a custom PII pattern at runtime. No restart needed."""
        self.rule_engine.add_pattern(name, pattern)
        logger.info(f"Added PII pattern: {name}")

    def reload_patterns(self, yaml_path: str = None):
        """Reload patterns from YAML config. Can be called at runtime."""
        self.rule_engine.reload_patterns(yaml_path)
        logger.info(f"Reloaded PII patterns from: {yaml_path or 'auto-detected'}")

    def list_patterns(self) -> dict:
        """List all loaded PII pattern names and their regexes."""
        return self.rule_engine.list_patterns()

    def _log_event(self, event: SessionEvent):
        """Log an event internally with retention limit."""
        self._event_log.append(event)
        # Enforce max events retention (drop oldest)
        if self.config.max_events > 0 and len(self._event_log) > self.config.max_events:
            # Keep events for killed sessions + recent events
            self._event_log = self._event_log[-self.config.max_events:]
        # Notify dashboard via websocket if configured
        if self.config.dashboard_ws_url:
            asyncio.create_task(self._notify_dashboard(event))

    def _fire_on_kill(self, event: SessionEvent):
        """Fire registered kill callbacks."""
        for callback in self._on_kill_callbacks:
            try:
                callback(event)
            except Exception as e:
                logger.error(f"Kill callback error: {e}")
        # SLA kill recording (Phase 4.8)
        self._record_sla_kill(event)

    async def _notify_dashboard(self, event: SessionEvent):
        """Send event to dashboard via websocket."""
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self.config.dashboard_ws_url}/api/events",
                    json=event.model_dump(mode="json")
                )
        except Exception as e:
            logger.debug(f"Dashboard notification failed: {e}")

    def _fire_webhook(self, event: SessionEvent):
        """Fire webhook notification if webhook manager is configured (Phase 4.4)."""
        if not self.webhook_manager:
            return
        try:
            from brahmanda.webhooks import WebhookEvent, WebhookEventType
            webhook_event_type = WebhookEventType.SESSION_KILL
            if event.decision == KillDecision.WARN:
                webhook_event_type = WebhookEventType.RULE_VIOLATION
            elif event.decision == KillDecision.KILL:
                webhook_event_type = WebhookEventType.SESSION_KILL

            webhook_event = WebhookEvent(
                event_type=webhook_event_type,
                payload=event.model_dump(mode="json"),
            )
            self.webhook_manager.fire(webhook_event)

            # Phase 6.2: Metrics
            if _metrics_enabled:
                record_webhook(webhook_event_type.value)
        except Exception as e:
            logger.debug(f"Webhook notification failed: {e}")

    def _record_sla_kill(self, event: SessionEvent, detection_time_ms: float = 0.0):
        """Record kill event for SLA tracking (Phase 4.8)."""
        if not self.sla_tracker:
            return
        try:
            self.sla_tracker.record_kill(
                session_id=event.session_id,
                reason=str(event.violation_type.value) if event.violation_type else "unknown",
                detection_time_ms=detection_time_ms,
            )
        except Exception as e:
            logger.debug(f"SLA kill recording failed: {e}")
