# RTA-GUARD — Phase 17: Framework Ecosystem

## Overview

Phase 17 extends RTA-GUARD's integration coverage from LangChain + LlamaIndex to **6 major AI agent frameworks**. After this phase, RTA-GUARD becomes a universal security layer that plugs into any AI agent stack.

## Status: ✅ COMPLETE

**Built:** 2026-03-28
**Tests:** 128 passing
**Total code:** 3,225 lines (integration) + 1,281 lines (tests)

---

## Subphases

### 17.1 — Haystack Integration ✅
**File:** `integrations/haystack/__init__.py` (721 lines)

| Class | Purpose |
|---|---|
| `RtaGuardComponent` | Wraps any Haystack Component. Input/output checks at each pipeline step |
| `RtaGuardPipeline` | Wraps `Pipeline.run()` and `Pipeline.run_async()`. Full protection |
| `RtaGuardDocumentStore` | Wraps `DocumentStore.filter_documents()`. Pre-filters violating docs |
| `RtaGuardGenerator` | Wraps Generator components. Streaming support |

Session prefix: `hs-`

### 17.2 — Microsoft Semantic Kernel Integration ✅
**File:** `integrations/semantic_kernel/__init__.py` (630 lines)

| Class | Purpose |
|---|---|
| `RtaGuardPlugin` | KernelPlugin exposing guard as native function |
| `RtaGuardFilter` | FunctionInvocationFilter for kernel-wide protection |
| `RtaGuardPlanner` | Wraps planner execution, step-by-step validation |
| `RtaGuardChatService` | Wraps ChatCompletionService, prompt + completion protection |

Session prefix: `sk-`

### 17.3 — CrewAI Integration ✅
**File:** `integrations/crewai/__init__.py` (633 lines)

| Class | Purpose |
|---|---|
| `RtaGuardAgent` | Wraps Agent, checks inputs/outputs, behavioral profiling |
| `RtaGuardTask` | Wraps Task, validates descriptions and results |
| `RtaGuardCrew` | Wraps Crew, monitors inter-agent communication |
| `RtaGuardTool` | Wraps Tool, input/output protection |

Session prefix: `cr-`

### 17.4 — AutoGen Integration ✅
**File:** `integrations/autogen/__init__.py` (760 lines)

| Class | Purpose |
|---|---|
| `RtaGuardAgent` | Wraps ConversableAgent, checks every message |
| `RtaGuardGroupChat` | Wraps GroupChat, monitors conversation tree |
| `RtaGuardUserProxy` | Wraps UserProxyAgent, human↔agent protection |
| `RtaGuardCodeExecutor` | Wraps code execution, blocks dangerous patterns |

Session prefix: `ag-`

### 17.5 — Unified Interface ✅

| File | Lines | Purpose |
|---|---|---|
| `integrations/base.py` | 164 | Abstract base class `RtaGuardIntegration` |
| `integrations/detect.py` | 214 | Auto-detect installed frameworks, `guard_for()` factory |
| `integrations/__init__.py` | 103 | Unified exports for all 6 frameworks |

---

## Test Coverage

**File:** `tests/test_integrations.py` (1,281 lines, 128 tests)

| Section | Tests |
|---|---|
| LangChain (existing) | 17 |
| LlamaIndex (existing) | 17 |
| Haystack | 18 |
| Semantic Kernel | 26 |
| CrewAI | 25 |
| AutoGen | 22 |
| Unified Interface | 9 |

---

## Integration Pattern

All integrations follow the same pattern established by LangChain/LlamaIndex:

```python
# Shared guard instance
def get_guard(**kwargs) -> DiscusGuard
def set_guard(guard: DiscusGuard)

# Each class:
class RtaGuardWrapper:
    def __init__(self, inner, session_id, on_violation, check_input, check_output, guard)
    def _check(self, text, is_output) -> Optional[str]
    def _handle_violation(self, violation) -> str
    def __getattr__(self, name) -> Any  # delegation
```

## Unified Usage

```python
# Auto-detect and wrap
from integrations import guard_for, detect_frameworks

frameworks = detect_frameworks()
# → ['langchain', 'crewai', 'haystack']

protected = guard_for("langchain", chain)
result = protected.invoke({"input": "Hello"})
```

---

*Last updated: 2026-03-28*
