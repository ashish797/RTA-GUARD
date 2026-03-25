"""
RTA-GUARD Discus — Core Kill-Switch Guard

The main class that wraps your AI app and adds deterministic session termination.
"""
import asyncio
import json
import logging
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

    def __init__(self, config: Optional[GuardConfig] = None, rta_engine: Optional[RtaEngine] = None):
        self.config = config or GuardConfig()
        self.rule_engine = RuleEngine(self.config)
        self.rta_engine = rta_engine  # RTA constitutional engine (optional)
        self._event_log: list[SessionEvent] = []
        self._on_kill_callbacks: list[Callable] = []
        self._killed_sessions: set[str] = set()
        logger.info("DiscusGuard initialized" + (" with RTA" if rta_engine else ""))

    def on_kill(self, callback: Callable[[SessionEvent], None]):
        """Register a callback for when a session is killed."""
        self._on_kill_callbacks.append(callback)

    def check(self, text: str, session_id: str = "default") -> GuardResponse:
        """
        Check input text against all rules.

        Returns GuardResponse with allowed=True/False.
        Raises SessionKilledError if kill threshold is met.
        """
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
        pattern_result = self.rule_engine.evaluate(text)

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

        # No violations — pass
        event = SessionEvent(
            session_id=session_id,
            input_text=text[:200],
            decision=KillDecision.PASS,
            details="Passed all checks"
        )
        if self.config.log_all:
            self._log_event(event)
        return GuardResponse(allowed=True, session_id=session_id, event=event)

    def check_and_forward(
        self,
        text: str,
        session_id: str = "default",
        llm_fn: Optional[Callable[[str], str]] = None
    ) -> str:
        """
        Check input, then forward to LLM if safe.

        Args:
            text: User input
            session_id: Session identifier
            llm_fn: Function that calls the LLM (takes text, returns response)

        Returns:
            LLM response if safe

        Raises:
            SessionKilledError if violation detected
        """
        self.check(text, session_id)

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

    def _log_event(self, event: SessionEvent):
        """Log an event internally."""
        self._event_log.append(event)
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
