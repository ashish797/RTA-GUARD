"""
RTA-GUARD Integrations

Drop-in protection for LangChain, LlamaIndex, Haystack, Semantic Kernel,
CrewAI, AutoGen, and other AI frameworks.

Usage:
    # Direct imports
    from integrations import RtaGuardChain, RtaGuardPipeline

    # Auto-detection
    from integrations import guard_for, detect_frameworks
    frameworks = detect_frameworks()
    protected = guard_for("langchain", chain)
"""

# ─── Base & Detection ──────────────────────────────────────────────

from .base import RtaGuardIntegration
from .detect import detect_frameworks, is_framework_installed, guard_for

# ─── LangChain ─────────────────────────────────────────────────────

from .langchain import (
    RtaGuardCallbackHandler,
    RtaGuardChain,
    RtaGuardRunnable,
    RtaGuardLLM,
)

# ─── LlamaIndex ────────────────────────────────────────────────────

from .llamaindex import (
    RtaGuardQueryEngine,
    RtaGuardPostProcessor,
    RtaGuardChatEngine,
)

# ─── Haystack ──────────────────────────────────────────────────────

try:
    from .haystack import (
        RtaGuardComponent as RtaGuardHaystackComponent,
        RtaGuardPipeline as RtaGuardHaystackPipeline,
        RtaGuardDocumentStore as RtaGuardHaystackDocumentStore,
        RtaGuardGenerator as RtaGuardHaystackGenerator,
    )
except ImportError:
    pass

# ─── Semantic Kernel ──────────────────────────────────────────────

try:
    from .semantic_kernel import (
        RtaGuardPlugin as RtaGuardSKPlugin,
        RtaGuardFilter as RtaGuardSKFilter,
        RtaGuardPlanner as RtaGuardSKPlanner,
        RtaGuardChatService as RtaGuardSKChatService,
    )
except ImportError:
    pass

# ─── CrewAI ────────────────────────────────────────────────────────

try:
    from .crewai import (
        RtaGuardAgent as RtaGuardCrewAgent,
        RtaGuardTask as RtaGuardCrewTask,
        RtaGuardCrew,
        RtaGuardTool as RtaGuardCrewTool,
    )
except ImportError:
    pass

# ─── AutoGen ───────────────────────────────────────────────────────

try:
    from .autogen import (
        RtaGuardAgent as RtaGuardAutoGenAgent,
        RtaGuardGroupChat,
        RtaGuardUserProxy,
        RtaGuardCodeExecutor,
    )
except ImportError:
    pass

__all__ = [
    # Base
    "RtaGuardIntegration",
    # Detection
    "detect_frameworks",
    "is_framework_installed",
    "guard_for",
    # LangChain
    "RtaGuardCallbackHandler",
    "RtaGuardChain",
    "RtaGuardRunnable",
    "RtaGuardLLM",
    # LlamaIndex
    "RtaGuardQueryEngine",
    "RtaGuardPostProcessor",
    "RtaGuardChatEngine",
]
