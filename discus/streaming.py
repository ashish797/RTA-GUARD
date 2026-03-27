"""
RTA-GUARD Streaming — Real-Time Protection

Checks tokens/chunks as they arrive, not after the full response.
Kills generation immediately on violation — saves tokens, reduces latency.

Features:
- Per-chunk/token checking
- Early termination on violation
- Streaming metrics (tokens checked, violations, time saved)
- Async and sync support
- Buffer management for multi-token patterns
"""
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, AsyncIterator, Callable, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger("rta_guard.streaming")


class StreamingState(Enum):
    """State of a streaming session."""
    ACTIVE = "active"
    KILLED = "killed"
    COMPLETED = "completed"
    PAUSED = "paused"


@dataclass
class StreamingMetrics:
    """Metrics for a streaming session."""
    session_id: str
    tokens_checked: int = 0
    chunks_checked: int = 0
    violations_detected: int = 0
    bytes_processed: int = 0
    start_time: float = field(default_factory=time.time)
    first_violation_time: Optional[float] = None
    end_time: Optional[float] = None
    total_tokens_if_not_killed: int = 0  # Estimated total if allowed to complete
    tokens_saved: int = 0  # Tokens we didn't generate because we killed early

    @property
    def duration_ms(self) -> float:
        end = self.end_time or time.time()
        return (end - self.start_time) * 1000

    @property
    def kill_rate(self) -> float:
        if self.chunks_checked == 0:
            return 0.0
        return self.violations_detected / self.chunks_checked

    @property
    def time_to_first_violation_ms(self) -> Optional[float]:
        if self.first_violation_time is None:
            return None
        return (self.first_violation_time - self.start_time) * 1000

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "tokens_checked": self.tokens_checked,
            "chunks_checked": self.chunks_checked,
            "violations_detected": self.violations_detected,
            "bytes_processed": self.bytes_processed,
            "duration_ms": round(self.duration_ms, 2),
            "kill_rate": round(self.kill_rate, 4),
            "time_to_first_violation_ms": (
                round(self.time_to_first_violation_ms, 2)
                if self.time_to_first_violation_ms is not None else None
            ),
            "tokens_saved": self.tokens_saved,
            "state": "completed",
        }


class StreamingGuard:
    """
    Real-time streaming guard that checks chunks as they arrive.

    Features:
    - Buffer-aware: accumulates chunks to detect multi-chunk patterns
    - Early termination: stops immediately on kill violations
    - Metrics: tracks tokens checked, violations, time saved
    - Pattern detection across chunk boundaries

    Usage:
        guard = DiscusGuard()
        sguard = StreamingGuard(guard, session_id="user-123")

        for chunk in llm.stream("user input"):
            result = sguard.process_chunk(chunk)
            if result.should_stop:
                yield result.replacement_text
                break
            yield chunk
    """

    def __init__(self, guard: Any, session_id: str = "default",
                 on_violation: str = "raise",
                 buffer_size: int = 200,
                 check_every_n_chars: int = 10):
        """
        Args:
            guard: DiscusGuard instance
            session_id: Session identifier
            on_violation: "raise", "block", "warn"
            buffer_size: Max chars to buffer for cross-chunk pattern detection
            check_every_n_chars: Check the buffer every N new characters
        """
        self.guard = guard
        self.session_id = session_id
        self.on_violation = on_violation
        self.buffer_size = buffer_size
        self.check_every_n_chars = check_every_n_chars

        self._buffer = ""
        self._state = StreamingState.ACTIVE
        self._metrics = StreamingMetrics(session_id=session_id)
        self._violations: List[Dict[str, Any]] = []
        self._last_check_pos = 0

    @property
    def state(self) -> StreamingState:
        return self._state

    @property
    def metrics(self) -> StreamingMetrics:
        return self._metrics

    @property
    def violations(self) -> List[Dict[str, Any]]:
        return self._violations

    @property
    def is_killed(self) -> bool:
        return self._state == StreamingState.KILLED

    def process_chunk(self, chunk: str) -> "ChunkResult":
        """
        Process a single streaming chunk.

        Returns:
            ChunkResult with should_stop, replacement_text, and status.
        """
        if self._state == StreamingState.KILLED:
            return ChunkResult(
                should_stop=True,
                replacement_text="",
                reason="Session already killed",
                metrics=self._metrics,
            )

        if not chunk:
            return ChunkResult(should_stop=False, chunk=chunk, metrics=self._metrics)

        # Update metrics
        self._metrics.chunks_checked += 1
        self._metrics.bytes_processed += len(chunk.encode())

        # Count tokens (approximate: split by whitespace)
        self._metrics.tokens_checked += len(chunk.split())

        # Add to buffer
        self._buffer += chunk
        if len(self._buffer) > self.buffer_size:
            self._buffer = self._buffer[-self.buffer_size:]

        # Check buffer periodically
        if len(self._buffer) - self._last_check_pos >= self.check_every_n_chars:
            self._last_check_pos = len(self._buffer)
            violation = self._check_buffer()
            if violation:
                return self._handle_violation(violation, chunk)

        return ChunkResult(should_stop=False, chunk=chunk, metrics=self._metrics)

    async def process_chunk_async(self, chunk: str) -> "ChunkResult":
        """Async version of process_chunk."""
        return self.process_chunk(chunk)

    def _check_buffer(self) -> Optional[Dict[str, Any]]:
        """Check accumulated buffer for violations."""
        try:
            self.guard.check(self._buffer, session_id=self.session_id)
            return None
        except Exception as e:
            violation = {
                "buffer_text": self._buffer[-100:],
                "error": str(e),
                "timestamp": time.time(),
                "buffer_position": len(self._buffer),
            }
            self._violations.append(violation)
            return violation

    def _handle_violation(self, violation: Dict[str, Any], chunk: str) -> "ChunkResult":
        """Handle a detected violation."""
        self._metrics.violations_detected += 1
        if self._metrics.first_violation_time is None:
            self._metrics.first_violation_time = time.time()

        if self.on_violation == "raise":
            self._state = StreamingState.KILLED
            self._metrics.end_time = time.time()
            return ChunkResult(
                should_stop=True,
                replacement_text="",
                reason=str(violation["error"]),
                violation=violation,
                metrics=self._metrics,
                raise_error=True,
            )
        elif self.on_violation == "block":
            self._state = StreamingState.KILLED
            self._metrics.end_time = time.time()
            return ChunkResult(
                should_stop=True,
                replacement_text="[BLOCKED BY RTA-GUARD]",
                reason=str(violation["error"]),
                violation=violation,
                metrics=self._metrics,
            )
        else:  # warn
            logger.warning(f"RTA-GUARD streaming warning: {violation['error']}")
            return ChunkResult(
                should_stop=False,
                chunk=chunk,
                reason=str(violation["error"]),
                violation=violation,
                metrics=self._metrics,
            )

    def complete(self) -> StreamingMetrics:
        """Mark streaming as complete and return final metrics."""
        if self._state == StreamingState.ACTIVE:
            self._state = StreamingState.COMPLETED
        self._metrics.end_time = time.time()
        return self._metrics

    def reset(self):
        """Reset for a new streaming session."""
        self._buffer = ""
        self._state = StreamingState.ACTIVE
        self._metrics = StreamingMetrics(session_id=self.session_id)
        self._violations = []
        self._last_check_pos = 0


@dataclass
class ChunkResult:
    """Result of processing a streaming chunk."""
    should_stop: bool
    chunk: str = ""
    replacement_text: str = ""
    reason: str = ""
    violation: Optional[Dict[str, Any]] = None
    metrics: Optional[StreamingMetrics] = None
    raise_error: bool = False

    @property
    def output(self) -> str:
        """Get the output text for this chunk."""
        if self.should_stop:
            return self.replacement_text
        return self.chunk


class StreamingIterator:
    """
    Wraps any iterator/generator with streaming guard protection.

    Usage:
        guard = DiscusGuard()
        sguard = StreamingGuard(guard, session_id="s1")

        # Wrap an existing iterator
        protected = StreamingIterator(llm.stream("input"), sguard)
        for chunk in protected:
            print(chunk, end="")
    """

    def __init__(self, inner: Iterator[str], streaming_guard: StreamingGuard):
        self.inner = inner
        self.guard = streaming_guard
        self._stopped = False

    def __iter__(self):
        return self

    def __next__(self) -> str:
        if self._stopped:
            raise StopIteration

        chunk = next(self.inner)
        result = self.guard.process_chunk(chunk)

        if result.should_stop:
            self._stopped = True
            if result.raise_error:
                raise RuntimeError(f"RTA-GUARD streaming blocked: {result.reason}")
            if result.replacement_text:
                return result.replacement_text
            raise StopIteration

        return result.chunk

    @property
    def metrics(self) -> StreamingMetrics:
        return self.guard.metrics


class AsyncStreamingIterator:
    """
    Async version of StreamingIterator.

    Usage:
        guard = DiscusGuard()
        sguard = StreamingGuard(guard, session_id="s1")

        protected = AsyncStreamingIterator(llm.astream("input"), sguard)
        async for chunk in protected:
            print(chunk, end="")
    """

    def __init__(self, inner: AsyncIterator[str], streaming_guard: StreamingGuard):
        self.inner = inner
        self.guard = streaming_guard
        self._stopped = False

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if self._stopped:
            raise StopAsyncIteration

        chunk = await self.inner.__anext__()
        result = await self.guard.process_chunk_async(chunk)

        if result.should_stop:
            self._stopped = True
            if result.raise_error:
                raise RuntimeError(f"RTA-GUARD streaming blocked: {result.reason}")
            if result.replacement_text:
                return result.replacement_text
            raise StopAsyncIteration

        return result.chunk

    @property
    def metrics(self) -> StreamingMetrics:
        return self.guard.metrics
