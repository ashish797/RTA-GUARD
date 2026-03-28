<div align="center">

<img src="https://github.com/ashish797/RTA-GUARD/blob/main/logo.svg?raw=true" alt="RTA-GUARD Logo" width="300">

# 🛡️ RTA-GUARD

**The Last Line of Defense for AI Agents**

*Enforce cosmic order (Ṛta) on your AI agents — deterministic kill-switch, constitutional governance, real-time threat detection.*

*Inspired by the **Rig Veda** (ऋग्वेद), the oldest of the four Vedas. Our 13 constitutional rules (R0–R13) are rooted in Vedic deities and principles of cosmic law.*

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Rust](https://img.shields.io/badge/Rust-1.94+-orange.svg)](https://rust-lang.org)
[![Python](https://img.shields.io/badge/Python-3.11+-green.svg)](https://python.org)
[![WASM](https://img.shields.io/badge/WASM-ready-blueviolet.svg)](https://webassembly.org)
[![Tests](https://img.shields.io/badge/tests-2000%2B-brightgreen.svg)](#testing)

[Quick Start](#quick-start) •
[Architecture](#architecture) •
[Documentation](#documentation) •
[Contributing](#contributing) •
[Roadmap](#roadmap)

---

</div>

## What is RTA-GUARD?

**RTA-GUARD** is a production-grade AI agent security layer. It intercepts every interaction between your AI agent and the outside world, applies a deterministic rule engine, and **kills sessions** when violations are detected — not just filters.

Named after the Vedic concept of **Ṛta** (cosmic order), RTA-GUARD enforces structural integrity on AI behavior. When an agent steps out of line — leaking PII, attempting injection, hallucinating dangerously, or exhibiting chaotic behavior — RTA-GUARD terminates the session instantly.

### Why RTA-GUARD?

| Problem | RTA-GUARD Solution |
|---------|-------------------|
| AI agents leaking PII (emails, SSNs, credit cards) | **Deterministic kill** on PII detection — session terminated, not just blocked |
| Prompt injection & jailbreak attacks | **13 Vedic rules** detect and neutralize attack vectors in real-time |
| No observability into AI agent behavior | **Prometheus metrics + ELK stack** with real-time dashboards and alerting |
| Enterprise compliance requirements | **SOC2, HIPAA, EU AI Act** templates with deterministic audit trails |
| Deploying AI agents at scale | **Docker, Kubernetes, Helm** with HA, multi-region, auto-scaling out of the box |
| Cost spiraling from unchecked AI usage | **Micro-cent cost tracking**, quotas, and optimization recommendations |
| No human-readable rule authoring | **Rule DSL** — write rules in plain English, hot-reload from file |
| Untested security posture | **Red Team Mode** — 105 built-in attack patterns, CI pipeline, variant fuzzing |
| Static thresholds cause false positives | **Adaptive Thresholds** — learns per-deployment, auto-tunes to P95 baseline |
| Can't prove ROI to stakeholders | **A/B Testing & Analytics** — shadow guard, ROI reporting, experiment runner |
| Framework lock-in | **6 Framework Integrations** — LangChain, LlamaIndex, Haystack, SK, CrewAI, AutoGen |

---

## ⚡ Quick Start

### 3-Line Integration

```python
from discus import DiscusGuard

guard = DiscusGuard()
response = guard.check_and_forward(user_input, session_id="abc123")
# Returns response or raises SessionKilledError on violation
```

### Install & Run

```bash
# Clone
git clone https://github.com/ashish797/RTA-GUARD.git && cd RTA-GUARD

# Install Python dependencies
pip install -r requirements.txt

# Run the demo
python demo/chat_demo.py

# Start the dashboard
python -m dashboard.app
# → Visit http://localhost:8000
```

### Docker

```bash
# Build & run full stack (dashboard + Postgres + Redis + Qdrant)
docker-compose up -d

# Visit http://localhost:8000
```

### Kubernetes (Helm)

```bash
# Deploy to your cluster
helm install rta-guard ./helm/rta-guard \
  --set ha.enabled=true \
  --set autoscaling.minReplicas=2

# Or with full enterprise features
helm install rta-guard ./helm/rta-guard \
  -f config/examples/large.yml
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         YOUR AI APPLICATION                         │
│    (LLM / Chatbot / Agent / Copilot)                               │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
              ┌─────────────────────────────┐
              │      RTA-GUARD (Discus)      │
              │   Deterministic Kill-Switch  │
              │                             │
              │  ┌───────────────────────┐  │
              │  │  RTA Rules Engine     │  │
              │  │  13 Vedic Rules (R0-R12) │
              │  │  ├─ SATYA (Truth)     │  │
              │  │  ├─ YAMA (Restriction)│  │
              │  │  ├─ MITRA (PII)       │  │
              │  │  ├─ AGNI (Audit)      │  │
              │  │  ├─ DHARMA (Role)     │  │
              │  │  ├─ VARUṆA (Lifecycle)│  │
              │  │  ├─ ALIGNMENT (Consistency)│  │
              │  │  ├─ SARASVATĪ (Injection)│  │
              │  │  ├─ VĀYU (Health)     │  │
              │  │  ├─ INDRA (Destruction)│  │
              │  │  ├─ AN-ṚTA (Drift)    │  │
              │  │  ├─ MĀYĀ (Hallucination)│  │
              │  │  └─ TAMAS (Chaos)      │  │
              │  └───────────────────────┘  │
              │                             │
              │  ┌───────────────────────┐  │
              │  │  Brahmanda Map        │  │
              │  │  Vector + SQLite      │  │
              │  └───────────────────────┘  │
              │                             │
              │  ┌───────────────────────┐  │
              │  │  Conscience Monitor   │  │
              │  │  Drift & Behavioral   │  │
              │  └───────────────────────┘  │
              └─────────────┬───────────────┘
                            │
                ┌───────────┼───────────┐
                │           │           │
            ✅ Pass    ⚠️ Warn    🛑 Kill
                │           │           │
                └───────────┴───────────┘
                            │
                            ▼
              ┌─────────────────────────────┐
              │    Enterprise Layer          │
              │  ├─ Prometheus Metrics (10)  │
              │  ├─ ELK Logging (9 panels)   │
              │  ├─ Multi-Tenant Isolation   │
              │  ├─ RBAC + SSO              │
              │  ├─ Webhook Notifications    │
              │  ├─ Cost Optimization        │
              │  ├─ Backup & DR              │
              │  └─ HA Multi-Region          │
              └─────────────────────────────┘
```

---

## 🧠 The 13 Rules

RTA-GUARD's rule engine implements **13 constitutional rules** inspired by Vedic principles of cosmic order (Ṛta):

| Rule | Name | What It Enforces | Severity |
|------|------|------------------|----------|
| R0 | **ṚTA** | Meta-rule — all rules must be enforced | CRITICAL |
| R1 | **SATYA** | Truthfulness — no unverified claims | WARNING → KILL |
| R2 | **YAMA** | Restriction — no unauthorized actions | KILL |
| R3 | **MITRA** | PII protection — emails, SSNs, credit cards | KILL |
| R4 | **AGNI** | Audit logging — all decisions recorded | KILL |
| R5 | **DHARMA** | Role integrity — agents stay in lane | KILL |
| R6 | **VARUṆA** | Lifecycle — killed sessions stay dead | KILL |
| R7 | **ALIGNMENT** | Temporal consistency — no contradictions | KILL |
| R8 | **SARASVATĪ** | Injection defense — jailbreak/poisoning | KILL |
| R9 | **VĀYU** | System health — monitor degradation | WARN → KILL |
| R10 | **INDRA** | Destructive action — prevent data loss | KILL |
| R11 | **AN-ṚTA** | Drift detection — behavioral analysis | WARN → KILL |
| R12 | **MĀYĀ** | Hallucination detection — grounded output | WARNING |
| R13 | **TAMAS** | Chaos — halt on systemic failure | KILL |

---

## 📦 Tech Stack

### Core Engine
- **Rust** — High-performance rule engine (26 tests, <1ms latency)
- **Python** — Enterprise layer, dashboard, integration
- **WebAssembly** — Browser/WASI runtime for edge deployment

### Enterprise
- **Docker + Kubernetes + Helm** — Production deployment
- **Prometheus + Grafana** — 10 metrics, 12 dashboard panels
- **Elasticsearch + Logstash + Kibana** — Structured logging, 9 panels
- **PostgreSQL + Redis + Qdrant** — Storage, caching, vector search
- **GitHub Actions** — CI/CD, security scanning, automated releases

### Multi-Language
- **Python** (pyo3 bindings)
- **JavaScript/TypeScript** (ES modules)
- **Go** (cgo bindings)
- **C** (FFI)
- **Rust** (native crate)

---

## 📊 Testing

```
✅ 26    Rust core tests
✅ 972+  Python unit tests
✅ 95    Browser injection tests
✅ 64    Multi-language binding tests
✅ 48    Backup & DR tests
─────────────────────────
✅ 1,000+ total tests passing
```

```bash
# Run all tests
cd discus-rs && cargo test       # Rust
python -m pytest tests/ -q       # Python
```

---

## 🚀 Deployment Options

| Option | Command | Best For |
|--------|---------|----------|
| **Local** | `python demo/chat_demo.py` | Development & testing |
| **Docker** | `docker-compose up -d` | Local production preview |
| **Helm** | `helm install rta-guard ./helm/rta-guard` | Kubernetes clusters |
| **WASM** | Load in browser via `<script type="module">` | Browser extensions, edge |
| **Multi-Region** | `helm install -f config/examples/large.yml` | Enterprise, global scale |

**Example configs available in `config/examples/`:**
- `small.yml` — Single-node, dev/test
- `medium.yml` — HA, 2 regions, autoscaling
- `large.yml` — Full enterprise, 4 regions, all features

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [User Guide](docs/USER_GUIDE.md) | Getting started, installation, configuration |
| [Admin Guide](docs/ADMIN_GUIDE.md) | Operations, monitoring, backup/restore |
| [Architecture](docs/ARCHITECTURE.md) | System design, data flow, components |
| [API Reference](docs/API_REFERENCE.md) | Python, Rust, REST APIs |
| [Deployment](docs/DEPLOYMENT.md) | Docker, Compose, Helm, Kubernetes |
| [Production Hardening](docs/DEPLOYMENT-PROD.md) | Secrets, TLS, compliance |
| [Monitoring](docs/MONITORING.md) | Prometheus metrics, Grafana dashboards |
| [Logging](docs/LOGGING.md) | ELK stack, structured logging |
| [High Availability](docs/HA.md) | Multi-region, leader election, failover |
| [Cost Optimization](docs/COST.md) | Pricing tiers, quotas, cost reports |
| [Disaster Recovery](docs/DISASTER_RECOVERY.md) | Backup, restore, DR drills |
| [CI/CD](docs/CICD.md) | Pipeline configuration, release process |
| [FAQ](docs/FAQ.md) | Common questions and troubleshooting |
| [Cheat Sheet](docs/CHEATSHEET.md) | Commands, metrics, alerts |
| [Training](docs/TRAINING_README.md) | Courses, workshops, video topics |

---

## 🤝 Contributing

We welcome contributors! RTA-GUARD is built on the principle of **Ṛta** — cosmic order through collaborative effort.

**Good first issues:**
- [ ] Add new rule implementations (R14–R20)
- [ ] Improve WASM binary size (target: <500KB)
- [ ] Add more language bindings (Java, C#, Ruby)
- [ ] Enhance dashboard UI
- [ ] Write additional test coverage

**How to contribute:**
1. Fork the repo
2. Create a feature branch: `git checkout -b feat/amazing-feature`
3. Write tests for your changes
4. Ensure `cargo test` + `pytest` pass
5. Submit a PR with a clear description

See [CONTRIBUTING.md](docs/CONTRIBUTING.md) for detailed guidelines.

### Development Setup

```bash
# Clone & install
git clone https://github.com/ashish797/RTA-GUARD.git
cd RTA-GUARD
pip install -r requirements.txt

# Install Rust toolchain (for WASM)
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
rustup target add wasm32-unknown-unknown

# Build Rust core
cd discus-rs && cargo build && cd ..

# Run tests
python -m pytest tests/ -v
cd discus-rs && cargo test
```

---

## 🗺️ Roadmap

### ✅ Completed (Phases 0–18)
- [x] **Phase 0** — Kill-Switch MVP (DiscusGuard, pattern-based detection)
- [x] **Phase 1** — RTA Rules Engine (13 Vedic rules, priority matrix, chaos scoring)
- [x] **Phase 2** — Brahmanda Map (Qdrant vector DB, truth verification, source attribution, mutation tracking)
- [x] **Phase 3** — Conscience Monitor (behavioral profiling, drift scoring, Tamas detection, escalation)
- [x] **Phase 4** — Enterprise Features (RBAC, SSO, compliance, webhooks, rate limiting, SLA)
- [x] **Phase 5** — Sudarshan WASM (Rust→WASM, browser injection, WASI, multi-language bindings)
- [x] **Phase 6** — Ecosystem & Scale (Docker, K8s, Helm, Prometheus, ELK, CI/CD, HA, DR)
- [x] **Phase 7** — React Dashboard (15 pages, WebSocket live events, dark theme)
- [x] **Phase 8** — Agent Marketplace (plugin system, sandbox, registry, 8 seed plugins)
- [x] **Phase 9** — Federated Learning (behavioral fingerprinting, differential privacy, threat intel)
- [x] **Phase 10** — Quantum-Resistant Crypto (ML-KEM-768, ML-DSA-65, SLH-DSA, hybrid mode)
- [x] **Phase 11** — LangChain + LlamaIndex Integration (drop-in wrappers, streaming support)
- [x] **Phase 12** — Streaming & Real-Time Protection (per-chunk checking, early termination)
- [x] **Phase 13** — Conversation Memory & Multi-Turn Defense (temporal consistency, drift tracking)
- [x] **Phase 14** — Custom Rules & Multi-Tenant (YAML profiles, rule inheritance)
- [x] **Phase 15** — RAG Intelligence (grounding checker, hallucination detector, citation enforcer)
- [x] **Phase 16** — Observability & Tracing (SQLite traces, violation analytics, cost tracking, OTel)
- [x] **Phase 17** — Framework Ecosystem (Haystack, Semantic Kernel, CrewAI, AutoGen + unified interface)
- [x] **Phase 18** — Advanced Features (adaptive thresholds, rule DSL, red team mode, A/B testing)

---

## 📊 Stats

| Metric | Value |
|--------|-------|
| Phases Completed | **18** (all) |
| Subphases | **57** |
| Python Files | **175** |
| Code Lines | **~70,000** |
| Test Lines | **~10,400** |
| Test Count | **2,000+** |
| Languages | 6 (Rust, Python, JS, Go, C, TypeScript) |
| Framework Integrations | 6 (LangChain, LlamaIndex, Haystack, Semantic Kernel, CrewAI, AutoGen) |
| Attack Patterns | 105 (8 categories) |
| WASM Binary | <1MB (browser), <800KB (WASI) |
| Check Latency | <1ms (1KB input) |
| PII Detection | <100μs |

---

## 🙏 Philosophy & Inspiration

> *"Ṛta" (ऋत) — cosmic order, the natural law that maintains harmony.*

RTA-GUARD draws its foundational philosophy from the **Rig Veda** (ऋग्वेद), the oldest of the four Vedas and one of humanity's earliest texts on cosmic law and order. The concept of **Ṛta** — the principle of natural order, truth, and righteousness that governs the universe — is central to the Rig Veda's worldview.

The **13 constitutional rules** (R0–R13) that form RTA-GUARD's core are inspired by Vedic deities and principles from the Rig Veda:

| Rule | Vedic Deity/Principle | Rig Veda Connection |
|------|----------------------|---------------------|
| R0 | **Ṛta** (ऋत) | Cosmic order itself — the meta-law |
| R1 | **Satya** (सत्य) | Truth — Rig Veda 1.164.46 "Truth is one, sages call it by various names" |
| R2 | **Yama** (यम) | Restraint and moral conduct — first mortal who became lord of the dead |
| R3 | **Mitra** (मित्र) | Friendship and protection — guardian of oaths and agreements |
| R4 | **Agni** (अग्नि) | Fire and witness — divine messenger who carries offerings to gods |
| R5 | **Dharma** (धर्म) | Duty and righteousness — the cosmic law of proper conduct |
| R6 | **Varuṇa** (वरुण) | Cosmic sovereignty — keeper of natural and moral law |
| R7 | **Alignment** | Ṛta as consistency — temporal harmony across actions |
| R8 | **Sarasvatī** (सरस्वती) | Knowledge and wisdom — protection from false knowledge |
| R9 | **Vāyu** (वायु) | Wind and life force — health and vitality of systems |
| R10 | **Indra** (इन्द्र) | Warrior king — protection from destructive forces |
| R11 | **An-Ṛta** (अनृत) | Disorder — the opposite of Ṛta, drift from truth |
| R12 | **Māyā** (माया) | Illusion — detection of hallucination and false reality |
| R13 | **Tamas** (तमस) | Darkness and chaos — the final state of systemic failure |

Just as the Rig Veda describes Ṛta as the principle that maintains cosmic harmony — where devas (gods) uphold order against asuras (forces of chaos) — RTA-GUARD enforces structural boundaries on AI agents. When an agent violates its dharma, RTA-GUARD acts as the cosmic enforcer, restoring order instantly and unconditionally.

Every kill decision is deterministic. Every violation is logged. Every session has a constitutional contract. RTA-GUARD doesn't just filter — it enforces the natural law of AI behavior, rooted in the oldest wisdom tradition on Earth.

---

## 📄 License

Apache License 2.0 — see [LICENSE](LICENSE) for details.

---

<div align="center">

**[⬆ Back to Top](#️-rta-guard)**

Made with ❤️ by the RTA-GUARD community

*The last line of defense.*

</div>
