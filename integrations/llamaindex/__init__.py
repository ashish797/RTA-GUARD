"""
RTA-GUARD — LlamaIndex Integration

Drop-in protection for LlamaIndex query engines and retrieval.
Wraps input/output with RTA-GUARD's 13 rules + plugin system.

Usage:
    from integrations.llamaindex import RtaGuardQueryEngine, RtaGuardPostProcessor

    # Option 1: Wrap the query engine
    index = VectorStoreIndex.from_documents(docs)
    engine = index.as_query_engine()
    protected = RtaGuardQueryEngine(engine, session_id="user-123")
    response = protected.query("What's in the docs?")

    # Option 2: Use as a node postprocessor
    engine = index.as_query_engine(
        node_postprocessors=[RtaGuardPostProcessor()]
    )
"""
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("rta_guard.llamaindex")

# ─── Guard Engine Import ───────────────────────────────────────────

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from discus import DiscusGuard, GuardConfig
from discus.plugins import PluginManager

# Shared guard instance
_guard: Optional[DiscusGuard] = None


def get_guard(**kwargs) -> DiscusGuard:
    global _guard
    if _guard is None:
        plugins = PluginManager()
        try:
            plugins.load_all()
        except Exception:
            pass
        _guard = DiscusGuard(
            config=kwargs.get("config", GuardConfig()),
            plugin_manager=plugins,
        )
    return _guard


def set_guard(guard: DiscusGuard):
    global _guard
    _guard = guard


# ═══════════════════════════════════════════════════════════════════
# Query Engine Wrapper
# ═══════════════════════════════════════════════════════════════════

class RtaGuardQueryEngine:
    """
    Wraps a LlamaIndex query engine with RTA-GUARD protection.
    Checks both the input query and the output response.

    Usage:
        from llama_index import VectorStoreIndex
        index = VectorStoreIndex.from_documents(docs)
        engine = index.as_query_engine()
        protected = RtaGuardQueryEngine(engine)
        response = protected.query("What is this document about?")
    """

    def __init__(self, inner_engine: Any, session_id: Optional[str] = None,
                 on_violation: str = "raise",
                 check_input: bool = True, check_output: bool = True,
                 guard: Optional[DiscusGuard] = None):
        """
        Args:
            inner_engine: The LlamaIndex query engine to wrap
            session_id: Session identifier
            on_violation: "raise", "warn", or "block"
            check_input: Check user queries
            check_output: Check LLM responses
            guard: Custom DiscusGuard instance
        """
        self.inner = inner_engine
        self.session_id = session_id or f"li-{uuid.uuid4().hex[:8]}"
        self.on_violation = on_violation
        self.check_input = check_input
        self.check_output = check_output
        self.guard = guard or get_guard()
        self._violations: List[Dict[str, Any]] = []

    @property
    def violations(self) -> List[Dict[str, Any]]:
        return self._violations

    def _check(self, text: str, is_output: bool = False) -> Optional[str]:
        """Check text. Returns error message or None."""
        if not text:
            return None
        try:
            self.guard.check(text, session_id=self.session_id)
            return None
        except Exception as e:
            violation = {
                "text": text[:200],
                "is_output": is_output,
                "error": str(e),
                "timestamp": time.time(),
            }
            self._violations.append(violation)
            logger.warning(f"RTA-GUARD violation: {e}")
            return str(e)

    def _handle(self, text: str, is_output: bool = False) -> str:
        """Check and handle. Returns text or blocked message."""
        error = self._check(text, is_output)
        if error:
            if self.on_violation == "raise":
                raise RuntimeError(
                    f"RTA-GUARD {'output' if is_output else 'input'} blocked: {error}"
                )
            elif self.on_violation == "block":
                return "[BLOCKED BY RTA-GUARD]"
        return text

    def query(self, query_str: str, **kwargs) -> Any:
        """Query with input/output protection."""
        # Check input
        if self.check_input:
            result = self._handle(query_str, is_output=False)
            if result == "[BLOCKED BY RTA-GUARD]":
                return result

        # Run query
        response = self.inner.query(query_str, **kwargs)

        # Check output
        if self.check_output:
            response_text = str(response)
            handled = self._handle(response_text, is_output=True)
            if handled == "[BLOCKED BY RTA-GUARD]":
                return handled

        return response

    async def aquery(self, query_str: str, **kwargs) -> Any:
        """Async query with protection."""
        if self.check_input:
            self._handle(query_str, is_output=False)

        response = await self.inner.aquery(query_str, **kwargs)

        if self.check_output:
            response_text = str(response)
            self._handle(response_text, is_output=True)

        return response

    def retrieve(self, query_str: str, **kwargs) -> Any:
        """Retrieve with input protection (no output check for raw nodes)."""
        if self.check_input:
            self._handle(query_str, is_output=False)

        if hasattr(self.inner, "retrieve"):
            return self.inner.retrieve(query_str, **kwargs)
        return []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)


# ═══════════════════════════════════════════════════════════════════
# Node PostProcessor — for filtering retrieved nodes
# ═══════════════════════════════════════════════════════════════════

class RtaGuardPostProcessor:
    """
    LlamaIndex node postprocessor that checks retrieved nodes for PII,
    injection, and other violations before they reach the LLM.

    Usage:
        engine = index.as_query_engine(
            node_postprocessors=[RtaGuardPostProcessor()]
        )
    """

    def __init__(self, on_violation: str = "warn",
                 guard: Optional[DiscusGuard] = None):
        """
        Args:
            on_violation: "warn" (log + keep), "remove" (drop violating nodes), "raise"
            guard: Custom DiscusGuard instance
        """
        self.on_violation = on_violation
        self.guard = guard or get_guard()

    def _check_node(self, node_text: str, session_id: str) -> bool:
        """Check if a node's content is safe. Returns True if safe."""
        try:
            self.guard.check(node_text, session_id=session_id)
            return True
        except Exception as e:
            logger.warning(f"RTA-GUARD node violation: {e}")
            return False

    def postprocess_nodes(self, nodes: List[Any],
                          query_bundle: Optional[Any] = None) -> List[Any]:
        """Filter nodes based on RTA-GUARD rules."""
        session_id = f"li-node-{uuid.uuid4().hex[:8]}"
        safe_nodes = []

        for node in nodes:
            node_text = node.node.text if hasattr(node, "node") else str(node)

            if self._check_node(node_text, session_id):
                safe_nodes.append(node)
            elif self.on_violation == "raise":
                raise RuntimeError(f"RTA-GUARD blocked retrieved node: {node_text[:100]}")
            elif self.on_violation == "remove":
                logger.info(f"RTA-GUARD removed violating node: {node_text[:50]}...")
                # Skip this node
            else:  # warn
                safe_nodes.append(node)  # Keep but log

        return safe_nodes


# ═══════════════════════════════════════════════════════════════════
# Chat Engine Wrapper
# ═══════════════════════════════════════════════════════════════════

class RtaGuardChatEngine:
    """
    Wraps a LlamaIndex chat engine with RTA-GUARD protection.

    Usage:
        engine = index.as_chat_engine()
        protected = RtaGuardChatEngine(engine)
        response = protected.chat("Tell me about this document")

        # Stream with early termination
        for chunk in protected.stream_chat("Explain quantum computing"):
            print(chunk, end="", flush=True)
    """

    def __init__(self, inner_engine: Any, session_id: Optional[str] = None,
                 on_violation: str = "raise",
                 guard: Optional[DiscusGuard] = None,
                 buffer_size: int = 200,
                 check_every_n_chars: int = 10):
        self.inner = inner_engine
        self.session_id = session_id or f"li-chat-{uuid.uuid4().hex[:8]}"
        self.on_violation = on_violation
        self.guard = guard or get_guard()
        self.buffer_size = buffer_size
        self.check_every_n_chars = check_every_n_chars
        self._streaming_guard = None

    def _get_streaming_guard(self):
        if self._streaming_guard is None or self._streaming_guard.is_killed:
            from discus.streaming import StreamingGuard
            self._streaming_guard = StreamingGuard(
                guard=self.guard,
                session_id=self.session_id,
                on_violation=self.on_violation,
                buffer_size=self.buffer_size,
                check_every_n_chars=self.check_every_n_chars,
            )
        return self._streaming_guard

    @property
    def streaming_metrics(self):
        if self._streaming_guard:
            return self._streaming_guard.metrics
        return None

    def _check(self, text: str, is_output: bool = False):
        if not text:
            return
        try:
            self.guard.check(text, session_id=self.session_id)
        except Exception as e:
            if self.on_violation == "raise":
                raise RuntimeError(f"RTA-GUARD {'output' if is_output else 'input'} blocked: {e}")

    def chat(self, message: str, **kwargs) -> Any:
        self._check(message, is_output=False)
        response = self.inner.chat(message, **kwargs)
        self._check(str(response), is_output=True)
        return response

    async def achat(self, message: str, **kwargs) -> Any:
        self._check(message, is_output=False)
        response = await self.inner.achat(message, **kwargs)
        self._check(str(response), is_output=True)
        return response

    def stream_chat(self, message: str, **kwargs):
        """Stream chat with per-chunk protection and early termination."""
        self._check(message, is_output=False)

        sguard = self._get_streaming_guard()
        sguard.reset()

        streaming_response = self.inner.stream_chat(message, **kwargs)
        for chunk in streaming_response.response_gen:
            chunk_str = str(chunk)
            result = sguard.process_chunk(chunk_str)

            if result.should_stop:
                if result.raise_error:
                    sguard.complete()
                    raise RuntimeError(f"RTA-GUARD streaming blocked: {result.reason}")
                if result.replacement_text:
                    yield result.replacement_text
                sguard.complete()
                return

            yield result.chunk

        sguard.complete()

    def reset(self):
        if hasattr(self.inner, "reset"):
            self.inner.reset()
        self._streaming_guard = None

    def __getattr__(self, name: str):
        return getattr(self.inner, name)
