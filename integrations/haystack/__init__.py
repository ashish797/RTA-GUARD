"""
RTA-GUARD — Haystack Integration

Drop-in protection for Haystack pipelines, generators, document stores, and components.
Wraps input/output with RTA-GUARD's 13 rules + plugin system.

Usage:
    from integrations.haystack import RtaGuardPipeline, RtaGuardGenerator

    # Option 1: Wrap a full pipeline
    pipeline = Pipeline()
    protected = RtaGuardPipeline(pipeline)
    result = protected.run({"query": "What is AI?"})

    # Option 2: Wrap a generator component
    generator = HuggingFaceTGIGenerator(model_id="...")
    protected_gen = RtaGuardGenerator(generator)
    result = protected_gen.run({"prompt": "Tell me a story"})
"""
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger("rta_guard.haystack")

# ─── Guard Engine Import ───────────────────────────────────────────

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from discus import DiscusGuard, GuardConfig
from discus.plugins import PluginManager

# Shared guard instance (lazy initialized)
_guard: Optional[DiscusGuard] = None
_plugins: Optional[PluginManager] = None


def get_guard(**kwargs) -> DiscusGuard:
    """Get or create the shared guard instance.

    Usage:
        guard = get_guard()
        guard = get_guard(config=GuardConfig())
    """
    global _guard, _plugins
    if _guard is None:
        _plugins = PluginManager()
        try:
            _plugins.load_all()
        except Exception:
            pass
        _guard = DiscusGuard(
            config=kwargs.get("config", GuardConfig()),
            plugin_manager=_plugins,
        )
    return _guard


def set_guard(guard: DiscusGuard):
    """Set a custom guard instance.

    Usage:
        guard = DiscusGuard()
        set_guard(guard)
    """
    global _guard
    _guard = guard


# ═══════════════════════════════════════════════════════════════════
# Component Wrapper — wraps any Haystack Component
# ═══════════════════════════════════════════════════════════════════

class RtaGuardComponent:
    """
    Wraps any Haystack Component with RTA-GUARD protection.
    Checks both component input and output.

    Usage:
        from haystack.components.builders import PromptBuilder
        builder = PromptBuilder(template="Answer: {{query}}")
        protected = RtaGuardComponent(builder, session_id="user-123")
        result = protected.run(query="What is AI?")
    """

    def __init__(self, inner_component: Any, session_id: Optional[str] = None,
                 on_violation: str = "raise",
                 check_input: bool = True, check_output: bool = True,
                 guard: Optional[DiscusGuard] = None):
        """
        Args:
            inner_component: The Haystack component to wrap
            session_id: Session identifier (auto-generated if None, prefix "hs-")
            on_violation: "raise", "warn", or "block"
            check_input: Check component inputs
            check_output: Check component outputs
            guard: Custom DiscusGuard instance
        """
        self.inner = inner_component
        self.session_id = session_id or f"hs-{uuid.uuid4().hex[:8]}"
        self.on_violation = on_violation
        self.check_input = check_input
        self.check_output = check_output
        self.guard = guard or get_guard()
        self._violations: List[Dict[str, Any]] = []

    @property
    def violations(self) -> List[Dict[str, Any]]:
        """List of violations detected during this session."""
        return self._violations

    def _extract_text(self, data: Any) -> str:
        """Extract text from various input/output formats."""
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            return data.get("query", data.get("text", data.get("prompt",
                   data.get("content", data.get("documents", "")))))
        return str(data)[:500]

    def _check(self, text: str, is_output: bool = False) -> Optional[Dict[str, Any]]:
        """Run guard check on text. Returns violation dict or None."""
        if not text:
            return None
        try:
            self.guard.check(str(text), session_id=self.session_id)
            return None
        except Exception as e:
            violation = {
                "text": str(text)[:200],
                "is_output": is_output,
                "error": str(e),
                "session_id": self.session_id,
                "timestamp": time.time(),
            }
            self._violations.append(violation)
            logger.warning(f"RTA-GUARD violation: {e}")
            return violation

    def _handle_violation(self, violation: Dict[str, Any]) -> str:
        """Handle a violation based on on_violation setting."""
        if self.on_violation == "raise":
            raise RuntimeError(
                f"RTA-GUARD blocked this {'output' if violation['is_output'] else 'input'}: "
                f"{violation['error']}"
            )
        elif self.on_violation == "block":
            return "[BLOCKED BY RTA-GUARD]"
        else:  # warn
            logger.warning(f"RTA-GUARD warning: {violation['error']}")
            return violation["text"]

    def run(self, **kwargs) -> Any:
        """Run component with input/output protection."""
        # Check inputs
        if self.check_input:
            for key, value in kwargs.items():
                text = self._extract_text(value)
                if text:
                    violation = self._check(text, is_output=False)
                    if violation:
                        result = self._handle_violation(violation)
                        if self.on_violation == "block":
                            return {"result": result}

        # Run inner component
        result = self.inner.run(**kwargs)

        # Check outputs
        if self.check_output:
            if isinstance(result, dict):
                for key, value in result.items():
                    text = self._extract_text(value)
                    if text:
                        violation = self._check(text, is_output=True)
                        if violation:
                            handled = self._handle_violation(violation)
                            if self.on_violation == "block":
                                result[key] = handled
            elif isinstance(result, str):
                violation = self._check(result, is_output=True)
                if violation:
                    return self._handle_violation(violation)

        return result

    async def run_async(self, **kwargs) -> Any:
        """Async run with input/output protection."""
        if self.check_input:
            for key, value in kwargs.items():
                text = self._extract_text(value)
                if text:
                    violation = self._check(text, is_output=False)
                    if violation:
                        self._handle_violation(violation)

        if hasattr(self.inner, "run_async"):
            result = await self.inner.run_async(**kwargs)
        else:
            result = self.inner.run(**kwargs)

        if self.check_output:
            if isinstance(result, dict):
                for key, value in result.items():
                    text = self._extract_text(value)
                    if text:
                        violation = self._check(text, is_output=True)
                        if violation:
                            handled = self._handle_violation(violation)
                            if self.on_violation == "block":
                                result[key] = handled

        return result

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attributes to inner component."""
        return getattr(self.inner, name)

    def __repr__(self) -> str:
        return f"RtaGuardComponent(session={self.session_id}, inner={self.inner!r})"


# ═══════════════════════════════════════════════════════════════════
# Pipeline Wrapper — wraps Haystack Pipeline
# ═══════════════════════════════════════════════════════════════════

class RtaGuardPipeline:
    """
    Wraps a Haystack Pipeline with RTA-GUARD protection.
    Monitors pipeline.run() and run_async() for violations.

    Usage:
        from haystack import Pipeline
        pipeline = Pipeline()
        # ... add components ...
        protected = RtaGuardPipeline(pipeline, session_id="user-123")
        result = protected.run({"query": "What is AI?"})
    """

    def __init__(self, inner_pipeline: Any, session_id: Optional[str] = None,
                 on_violation: str = "raise",
                 check_input: bool = True, check_output: bool = True,
                 guard: Optional[DiscusGuard] = None):
        """
        Args:
            inner_pipeline: The Haystack Pipeline to wrap
            session_id: Session identifier (auto-generated if None)
            on_violation: "raise", "warn", or "block"
            check_input: Check pipeline inputs
            check_output: Check pipeline outputs
            guard: Custom DiscusGuard instance
        """
        self.inner = inner_pipeline
        self.session_id = session_id or f"hs-{uuid.uuid4().hex[:8]}"
        self.on_violation = on_violation
        self.check_input = check_input
        self.check_output = check_output
        self.guard = guard or get_guard()
        self._violations: List[Dict[str, Any]] = []

    @property
    def violations(self) -> List[Dict[str, Any]]:
        """List of violations detected during this session."""
        return self._violations

    def _extract_text(self, data: Any) -> str:
        """Extract text from various data formats."""
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            for key in ("query", "text", "prompt", "question", "input"):
                if key in data:
                    return str(data[key])
            return ""
        if isinstance(data, list):
            return " ".join(self._extract_text(item) for item in data[:5])
        return str(data)[:500]

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
                "session_id": self.session_id,
                "timestamp": time.time(),
            }
            self._violations.append(violation)
            logger.warning(f"RTA-GUARD violation: {e}")
            return str(e)

    def _handle(self, text: str, error: str, is_output: bool = False) -> str:
        """Handle a violation."""
        if self.on_violation == "raise":
            raise RuntimeError(
                f"RTA-GUARD {'output' if is_output else 'input'} blocked: {error}"
            )
        elif self.on_violation == "block":
            return "[BLOCKED BY RTA-GUARD]"
        else:  # warn
            logger.warning(f"RTA-GUARD warning: {error}")
            return text

    def run(self, pipeline_input: Optional[Dict[str, Any]] = None,
            **kwargs) -> Any:
        """Run pipeline with full input→output protection."""
        # Check inputs
        if self.check_input and pipeline_input:
            text = self._extract_text(pipeline_input)
            error = self._check(text, is_output=False)
            if error:
                self._handle(text, error, is_output=False)

        # Run pipeline
        result = self.inner.run(pipeline_input, **kwargs) if pipeline_input else self.inner.run(**kwargs)

        # Check outputs
        if self.check_output and isinstance(result, dict):
            for key, value in result.items():
                text = self._extract_text(value)
                if text:
                    error = self._check(text, is_output=True)
                    if error:
                        handled = self._handle(text, error, is_output=True)
                        if self.on_violation == "block":
                            result[key] = handled

        return result

    async def run_async(self, pipeline_input: Optional[Dict[str, Any]] = None,
                        **kwargs) -> Any:
        """Async run with full protection."""
        if self.check_input and pipeline_input:
            text = self._extract_text(pipeline_input)
            error = self._check(text, is_output=False)
            if error:
                self._handle(text, error, is_output=False)

        if hasattr(self.inner, "run_async"):
            result = await self.inner.run_async(pipeline_input, **kwargs) if pipeline_input else await self.inner.run_async(**kwargs)
        else:
            result = self.inner.run(pipeline_input, **kwargs) if pipeline_input else self.inner.run(**kwargs)

        if self.check_output and isinstance(result, dict):
            for key, value in result.items():
                text = self._extract_text(value)
                if text:
                    error = self._check(text, is_output=True)
                    if error:
                        handled = self._handle(text, error, is_output=True)
                        if self.on_violation == "block":
                            result[key] = handled

        return result

    def add_component(self, name: str, component: Any) -> None:
        """Add a component to the inner pipeline."""
        self.inner.add_component(name, component)

    def connect(self, sender: str, receiver: str) -> None:
        """Connect components in the inner pipeline."""
        self.inner.connect(sender, receiver)

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attributes to inner pipeline."""
        return getattr(self.inner, name)

    def __repr__(self) -> str:
        return f"RtaGuardPipeline(session={self.session_id}, inner={self.inner!r})"


# ═══════════════════════════════════════════════════════════════════
# DocumentStore Wrapper — wraps Haystack DocumentStore
# ═══════════════════════════════════════════════════════════════════

class RtaGuardDocumentStore:
    """
    Wraps a Haystack DocumentStore with RTA-GUARD protection.
    Filters violating documents from query results.

    Usage:
        from haystack.document_stores import InMemoryDocumentStore
        store = InMemoryDocumentStore()
        protected = RtaGuardDocumentStore(store)
        docs = protected.filter_documents(filters={})
    """

    def __init__(self, inner_store: Any, session_id: Optional[str] = None,
                 on_violation: str = "warn",
                 guard: Optional[DiscusGuard] = None):
        """
        Args:
            inner_store: The Haystack DocumentStore to wrap
            session_id: Session identifier
            on_violation: "warn" (log + keep), "block" (remove violating docs), "raise"
            guard: Custom DiscusGuard instance
        """
        self.inner = inner_store
        self.session_id = session_id or f"hs-doc-{uuid.uuid4().hex[:8]}"
        self.on_violation = on_violation
        self.guard = guard or get_guard()
        self._violations: List[Dict[str, Any]] = []

    @property
    def violations(self) -> List[Dict[str, Any]]:
        """List of violations detected during this session."""
        return self._violations

    def _check_document(self, doc: Any) -> bool:
        """Check if a document's content is safe. Returns True if safe."""
        text = ""
        if hasattr(doc, "content"):
            text = doc.content
        elif hasattr(doc, "text"):
            text = doc.text
        elif isinstance(doc, dict):
            text = doc.get("content", doc.get("text", ""))
        else:
            text = str(doc)

        if not text:
            return True

        try:
            self.guard.check(text, session_id=self.session_id)
            return True
        except Exception as e:
            violation = {
                "text": text[:200],
                "is_output": False,
                "error": str(e),
                "session_id": self.session_id,
                "timestamp": time.time(),
            }
            self._violations.append(violation)
            logger.warning(f"RTA-GUARD document violation: {e}")
            return False

    def filter_documents(self, filters: Optional[Dict[str, Any]] = None,
                         **kwargs) -> List[Any]:
        """Filter documents with RTA-GUARD protection on results."""
        docs = self.inner.filter_documents(filters=filters, **kwargs)

        safe_docs = []
        for doc in docs:
            if self._check_document(doc):
                safe_docs.append(doc)
            elif self.on_violation == "raise":
                text = getattr(doc, "content", str(doc))[:100]
                raise RuntimeError(f"RTA-GUARD blocked document: {text}")
            # "block" mode: skip the doc; "warn" mode: already logged

        return safe_docs

    async def filter_documents_async(self, filters: Optional[Dict[str, Any]] = None,
                                     **kwargs) -> List[Any]:
        """Async filter with protection."""
        if hasattr(self.inner, "filter_documents_async"):
            docs = await self.inner.filter_documents_async(filters=filters, **kwargs)
        else:
            docs = self.inner.filter_documents(filters=filters, **kwargs)

        safe_docs = []
        for doc in docs:
            if self._check_document(doc):
                safe_docs.append(doc)
            elif self.on_violation == "raise":
                text = getattr(doc, "content", str(doc))[:100]
                raise RuntimeError(f"RTA-GUARD blocked document: {text}")

        return safe_docs

    def write_documents(self, documents: List[Any], **kwargs) -> None:
        """Write documents after checking them."""
        safe_docs = []
        for doc in documents:
            if self._check_document(doc):
                safe_docs.append(doc)
            elif self.on_violation == "raise":
                text = getattr(doc, "content", str(doc))[:100]
                raise RuntimeError(f"RTA-GUARD blocked document write: {text}")

        self.inner.write_documents(safe_docs, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attributes to inner store."""
        return getattr(self.inner, name)

    def __repr__(self) -> str:
        return f"RtaGuardDocumentStore(session={self.session_id}, inner={self.inner!r})"


# ═══════════════════════════════════════════════════════════════════
# Generator Wrapper — wraps Haystack Generator components
# ═══════════════════════════════════════════════════════════════════

class RtaGuardGenerator:
    """
    Wraps a Haystack Generator with RTA-GUARD protection.
    Checks prompts and generated outputs. Streaming support via run().

    Usage:
        from haystack.components.generators import HuggingFaceTGIGenerator
        generator = HuggingFaceTGIGenerator(model_id="gpt2")
        protected = RtaGuardGenerator(generator)
        result = protected.run(prompt="Tell me a story")
    """

    def __init__(self, inner_generator: Any, session_id: Optional[str] = None,
                 on_violation: str = "raise",
                 check_input: bool = True, check_output: bool = True,
                 guard: Optional[DiscusGuard] = None,
                 buffer_size: int = 200,
                 check_every_n_chars: int = 10):
        """
        Args:
            inner_generator: The Haystack generator to wrap
            session_id: Session identifier
            on_violation: "raise", "warn", or "block"
            check_input: Check prompts before generation
            check_output: Check generated outputs
            guard: Custom DiscusGuard instance
            buffer_size: Size of streaming buffer
            check_every_n_chars: Check streaming output every N chars
        """
        self.inner = inner_generator
        self.session_id = session_id or f"hs-gen-{uuid.uuid4().hex[:8]}"
        self.on_violation = on_violation
        self.check_input = check_input
        self.check_output = check_output
        self.guard = guard or get_guard()
        self.buffer_size = buffer_size
        self.check_every_n_chars = check_every_n_chars
        self._violations: List[Dict[str, Any]] = []
        self._streaming_guard = None

    @property
    def violations(self) -> List[Dict[str, Any]]:
        """List of violations detected during this session."""
        return self._violations

    def _extract_text(self, data: Any) -> str:
        """Extract text from various data formats."""
        if isinstance(data, str):
            return data
        if isinstance(data, dict):
            return data.get("prompt", data.get("text", data.get("query", "")))
        if isinstance(data, list):
            return " ".join(str(item) for item in data[:5])
        return str(data)[:500]

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
                "session_id": self.session_id,
                "timestamp": time.time(),
            }
            self._violations.append(violation)
            logger.warning(f"RTA-GUARD violation: {e}")
            return str(e)

    def _handle(self, text: str, error: str, is_output: bool = False) -> str:
        """Handle a violation."""
        if self.on_violation == "raise":
            raise RuntimeError(
                f"RTA-GUARD {'output' if is_output else 'input'} blocked: {error}"
            )
        elif self.on_violation == "block":
            return "[BLOCKED BY RTA-GUARD]"
        else:  # warn
            logger.warning(f"RTA-GUARD warning: {error}")
            return text

    def run(self, prompt: Optional[str] = None, **kwargs) -> Any:
        """Run generator with input/output protection."""
        # Check input prompt
        if self.check_input and prompt:
            error = self._check(prompt, is_output=False)
            if error:
                self._handle(prompt, error, is_output=False)

        # Also check prompts in kwargs
        if self.check_input:
            for key in ("prompts", "query", "text"):
                if key in kwargs:
                    text = self._extract_text(kwargs[key])
                    if text:
                        error = self._check(text, is_output=False)
                        if error:
                            self._handle(text, error, is_output=False)

        # Run generator
        if prompt is not None:
            result = self.inner.run(prompt=prompt, **kwargs)
        else:
            result = self.inner.run(**kwargs)

        # Check output
        if self.check_output and isinstance(result, dict):
            if "replies" in result:
                replies = result["replies"]
                if isinstance(replies, list):
                    for i, reply in enumerate(replies):
                        reply_text = str(reply)
                        error = self._check(reply_text, is_output=True)
                        if error:
                            handled = self._handle(reply_text, error, is_output=True)
                            if self.on_violation == "block":
                                result["replies"][i] = handled
            if "completion" in result:
                text = str(result["completion"])
                error = self._check(text, is_output=True)
                if error:
                    handled = self._handle(text, error, is_output=True)
                    if self.on_violation == "block":
                        result["completion"] = handled
            if "text" in result:
                text = str(result["text"])
                error = self._check(text, is_output=True)
                if error:
                    handled = self._handle(text, error, is_output=True)
                    if self.on_violation == "block":
                        result["text"] = handled

        return result

    async def run_async(self, prompt: Optional[str] = None, **kwargs) -> Any:
        """Async run with protection."""
        if self.check_input and prompt:
            error = self._check(prompt, is_output=False)
            if error:
                self._handle(prompt, error, is_output=False)

        if hasattr(self.inner, "run_async"):
            if prompt is not None:
                result = await self.inner.run_async(prompt=prompt, **kwargs)
            else:
                result = await self.inner.run_async(**kwargs)
        else:
            result = self.run(prompt=prompt, **kwargs)

        return result

    @property
    def streaming_metrics(self):
        """Get streaming metrics from last stream operation."""
        if self._streaming_guard:
            return self._streaming_guard.metrics
        return None

    def _get_streaming_guard(self):
        """Get or create a StreamingGuard instance."""
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

    def stream(self, prompt: str, **kwargs):
        """Stream with per-chunk protection and early termination."""
        if self.check_input:
            error = self._check(prompt, is_output=False)
            if error:
                self._handle(prompt, error, is_output=False)

        sguard = self._get_streaming_guard()
        sguard.reset()

        if hasattr(self.inner, "stream"):
            chunks = self.inner.stream(prompt=prompt, **kwargs)
        else:
            # Fallback: run and yield result
            result = self.run(prompt=prompt, **kwargs)
            yield result
            return

        for chunk in chunks:
            chunk_text = self._extract_text(chunk)
            if chunk_text:
                result = sguard.process_chunk(chunk_text)
                if result.should_stop:
                    if result.raise_error:
                        sguard.complete()
                        raise RuntimeError(f"RTA-GUARD streaming blocked: {result.reason}")
                    if result.replacement_text:
                        yield result.replacement_text
                    sguard.complete()
                    return
            yield chunk

        sguard.complete()

    def __getattr__(self, name: str) -> Any:
        """Delegate unknown attributes to inner generator."""
        return getattr(self.inner, name)

    def __repr__(self) -> str:
        return f"RtaGuardGenerator(session={self.session_id}, inner={self.inner!r})"
