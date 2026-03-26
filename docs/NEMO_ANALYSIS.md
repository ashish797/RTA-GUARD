# NeMo Guardrails — Comprehensive Analysis

## What Is NeMo Guardrails?

NeMo Guardrails is an open-source toolkit by NVIDIA for adding **programmable guardrails** to LLM-based conversational applications. It's the industry standard for LLM safety.

**GitHub:** https://github.com/NVIDIA-NeMo/Guardrails
**License:** Apache 2.0
**Version:** 0.21.0 (latest)
**Python:** 3.10, 3.11, 3.12, 3.13

---

## Architecture

### Core Concept: Rails

Rails are specific ways of controlling LLM output. NeMo defines **5 types of rails**:

| Rail Type | When It Runs | What It Does |
|-----------|-------------|--------------|
| **Input Rails** | Before LLM call | Reject/alter user input |
| **Dialog Rails** | During conversation flow | Control dialog path |
| **Retrieval Rails** | After RAG retrieval | Filter/alter retrieved chunks |
| **Execution Rails** | Around tool calls | Validate tool input/output |
| **Output Rails** | After LLM response | Reject/alter LLM output |

### Configuration Structure

```
config/
├── config.yml          # LLM config, active rails
├── config.py           # Custom initialization
├── actions.py          # Custom Python actions
├── rails.co            # Colang definitions
├── flows.co            # Dialog flows
└── kb/                 # Knowledge base
```

### Key Components

| Component | Purpose |
|-----------|---------|
| **LLMRails** | Main entry point (wraps LLM) |
| **RailsConfig** | Configuration loader |
| **Runtime** | Colang runtime (V1.0 or V2.x) |
| **LLMTaskManager** | Task-oriented LLM interface |
| **EmbeddingsIndex** | Vector search for KB |
| **KnowledgeBase** | Document store for RAG |

---

## Built-in Guardrails Library

NeMo has **25+ built-in guardrail modules**:

### LLM Self-Checking
| Module | Purpose |
|--------|---------|
| `input_moderation` | Check user input for harmful content |
| `output_moderation` | Check LLM output for harmful content |
| `self_check_facts` | Verify factual accuracy |
| `self_check_hallucination` | Detect hallucinations |
| `self_check_input` | Moderate user input |
| `self_check_output` | Moderate LLM output |

### NVIDIA Safety Models
| Module | Purpose |
|--------|---------|
| `content_safety` | NVIDIA content safety model |
| `topic_safety` | Topic control via NVIDIA model |

### Community Integrations
| Module | Purpose |
|--------|---------|
| `activefence` | ActiveFence content moderation |
| `autoalign` | AutoAlign safety alignment |
| `cleanlab` | Cleanlab trustworthiness scoring |
| `patronus_ai` | Patronus Lynx hallucination detection |
| `align_score` | AlignScore fact verification |
| `vakshot` | Vakshot content moderation |
| `clavata` | Clavata content moderation |

### Sensitive Data
| Module | Purpose |
|--------|---------|
| `sensitive_data_detection` | PII detection via Presidio |
| `sensitive_data_masking` | Mask PII in text |

### Jailbreak/Injection
| Module | Purpose |
|--------|---------|
| `jailbreak_detection` | Detect jailbreak attempts |
| `prompt_injection_detection` | Detect prompt injection |

### RAG-Specific
| Module | Purpose |
|--------|---------|
| `hallucination_detection` | Hallucination in RAG responses |
| `fact_checking` | Fact verification in RAG |

---

## Detection Methods

### 1. PII Detection (Presidio)

```yaml
rails:
  config:
    sensitive_data_detection:
      input:
        entities:
          - PERSON
          - EMAIL_ADDRESS
          - PHONE_NUMBER
          - CREDIT_CARD
          - US_SSN
          - LOCATION
```

**How it works:**
- Uses Microsoft Presidio (spaCy NER + pattern recognizers)
- Configurable entity types
- Configurable score threshold
- Can mask instead of block

### 2. Jailbreak Detection

**Methods:**
- LLM self-check: "Is this a jailbreak attempt?"
- Pattern matching: known jailbreak signatures
- Perplexity-based: unusual token patterns

### 3. Hallucination Detection

**Methods:**
- LLM self-check: "Is this supported by context?"
- Grounding verification: compare output to retrieved chunks
- Confidence scoring: check LLM confidence

### 4. Content Moderation

**Integrations:**
- OpenAI moderation endpoint
- ActiveFence API
- NVIDIA content safety model
- Custom models

---

## Colang Language

Colang is NeMo's modeling language for defining dialog flows.

### Syntax

```colang
# Define user intents
define user express greeting
  "Hello!"
  "Hi there!"

# Define bot responses
define bot express greeting
  "Hello! How can I help?"

# Define flows
define flow
  user express greeting
  bot express greeting
  bot offer to help

# Define rails
define flow self check input
  user said something
  execute self_check_input
  if not result
    bot refuse to respond
```

### Key Features
- Python-like syntax
- Pattern matching for intents
- Conditional logic
- Custom actions
- Modular composition

---

## Configuration

### config.yml

```yaml
models:
  - type: main
    engine: openai
    model: gpt-3.5-turbo-instruct

rails:
  input:
    flows:
      - check jailbreak
      - mask sensitive data on input
  output:
    flows:
      - self check facts
      - self check hallucination
  config:
    sensitive_data_detection:
      input:
        entities:
          - PERSON
          - EMAIL_ADDRESS

streaming:
  enabled: true

logging:
  verbose: true
```

---

## API

### Python API

```python
from nemoguardrails import LLMRails, RailsConfig

config = RailsConfig.from_path("config/")
rails = LLMRails(config)

# Generate with guardrails
response = rails.generate(
    messages=[{"role": "user", "content": "Hello!"}]
)
```

### Server API

```bash
nemoguardrails server --config config/ --port 8000
```

```json
POST /v1/chat/completions
{
  "config_id": "sample",
  "messages": [{"role": "user", "content": "Hello!"}]
}
```

---

## Evaluation

NeMo includes evaluation tools:

```bash
nemoguardrails evaluate --config config/ --test-file tests.yml
```

**Supported evaluations:**
- Topical rails (topic adherence)
- Fact-checking (hallucination detection)
- Moderation (jailbreak, output moderation)
- Hallucination detection

---

## Integrations

### LangChain

```python
from nemoguardrails.integrations.langchain.runnable_rails import RunnableRails

chain = LLMChain(llm=llm, prompt=prompt)
guarded_chain = RunnableRails(config, chain)
```

### LlamaIndex

```python
from nemoguardrails.integrations.llamaindex.index import RailsQueryEngine
```

### NVIDIA Models

- NeMo Guardrails can use NVIDIA's NIM endpoints
- Supports Llama, Mistral, and other models via NVIDIA API

---

## What RTA-GUARD Can Learn

### Detection Patterns

| NeMo Approach | RTA-GUARD Equivalent |
|---------------|---------------------|
| LLM self-check | Phase B: R1, R12 |
| Presidio PII | ✅ Already using Presidio |
| Pattern matching for jailbreak | ✅ Already have injection detection |
| External API moderation | Could add OpenAI moderation API |
| Hallucination grounding | Phase B: R12 |
| Fact-checking | Phase B: R1 |

### Configuration Patterns

| NeMo Approach | RTA-GUARD Equivalent |
|---------------|---------------------|
| YAML config | ✅ Already have YAML config |
| Colang flows | Could create Colang-like flow language |
| Custom actions | ✅ Already have custom rules |
| Modular composition | ✅ Already have detection layers |

### Architecture Patterns

| NeMo Approach | RTA-GUARD Equivalent |
|---------------|---------------------|
| 5 rail types | Could adopt rail model |
| Async-first | Could adopt async |
| LLM wrapping | ✅ Already wrapping LLM |
| Plugin system | Could add plugin architecture |

---

## NeMo vs RTA-GUARD — Feature Comparison

| Feature | NeMo | RTA-GUARD | Gap |
|---------|------|-----------|-----|
| PII Detection | Presidio (40+ entities) | Presidio (40+ entities) | None |
| Jailbreak Detection | LLM self-check + patterns | Regex patterns | Add LLM check |
| Hallucination | LLM self-check | Not implemented | Add LLM check |
| Fact-checking | LLM self-check | Not implemented | Add LLM check |
| Content Moderation | 10+ APIs | None | Add integrations |
| Dialog Management | Colang | None | Could add |
| Kill-Switch | None | ✅ Unique | NeMo doesn't have |
| Constitutional Rules | None | ✅ Unique | NeMo doesn't have |
| Enterprise Features | Basic | ✅ Full | NeMo lacks |
| Edge Deployment | None | ✅ WASM | NeMo lacks |
| Multi-language | Python only | Python/JS/Go/C/Rust | RTA-GUARD wins |
| Latency | Slow (LLM calls) | Fast (regex, sub-ms) | RTA-GUARD wins |

---

## Strategic Positioning

**NeMo:** "Detection toolkit" — provides many detection methods, user chooses which to use
**RTA-GUARD:** "Enforcement framework" — provides kill-switch + constitutional rules, detection is pluggable

**The opportunity:** RTA-GUARD as the enforcement layer on top of NeMo's detection layer.

```
NeMo Detection → RTA-GUARD Enforcement → User
(LLM checks,     (Kill-switch,           (Safe
 Presidio,        constitutional          output)
 patterns)        rules)
```

---

## Next Steps

1. **Study NeMo's LLM self-check patterns** for R1, R12
2. **Study NeMo's Colang language** for potential adoption
3. **Study NeMo's evaluation tools** for testing
4. **Study NeMo's LangChain integration** for ecosystem
5. **Design RTA-GUARD as NeMo-compatible plugin**

**Goal:** Don't compete with NeMo. Complement it. Be the enforcement layer that NeMo doesn't have.
