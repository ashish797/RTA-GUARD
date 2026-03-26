# RTA-GUARD — User Guide

> **Version 0.6.1** | Last Updated: 2026-03-26

---

## Table of Contents

- [What Is RTA-GUARD?](#what-is-rta-guard)
- [Getting Started](#getting-started)
- [Installation](#installation)
- [Configuration](#configuration)
- [Usage](#usage)
- [Dashboard](#dashboard)
- [Rules Engine](#rules-engine)
- [Browser Extension](#browser-extension)
- [FAQ](#faq)
- [Further Reading](#further-reading)

---

## What Is RTA-GUARD?

RTA-GUARD (Real-Time Alignment Guardian) is the **seatbelt for AI**. It wraps your AI application and adds a **deterministic kill-switch**: when a violation is detected — PII leak, prompt injection, jailbreak attempt — the session is terminated instantly, not just filtered.

Named after the Vedic concept of **Ṛta** (cosmic order), RTA-GUARD enforces alignment rules grounded in truth, ethics, and consistency.

### Key Features

- **13 Vedic-inspired rules** (R1–R13) covering truthfulness, harm prevention, scope control, privacy, temporal consistency, drift detection, and more
- **Instant kill-switch** — violations trigger session termination, not soft filtering
- **Ground truth verification** — the Brahmanda Map validates AI claims against known facts
- **Conscience monitoring** — live drift scoring, Tamas detection, temporal consistency, user anomaly detection
- **Enterprise features** — multi-tenancy, RBAC, SSO (OIDC/SAML), rate limiting, SLA monitoring, compliance reporting, webhooks
- **Rust/WASM engine** — high-performance rules engine (`discus-rs`) with browser extension support
- **Full observability** — Prometheus metrics, Grafana dashboards, structured logging, audit trails

---

## Getting Started

### Prerequisites

- Python 3.10+
- pip or Docker

### 3-Line Integration

```python
from discus import DiscusGuard

guard = DiscusGuard()
response = guard.check_and_forward(user_input, session_id="abc123")
# Returns response or raises SessionKilledError
```

### Quick Start (CLI)

```bash
# Clone and install
git clone https://github.com/rta-guard/rta-guard.git
cd rta-guard
pip install -r requirements.txt

# Run the demo chat
python demo/chat_demo.py

# Start the dashboard
python -m dashboard.app
# → http://localhost:8000
```

### Quick Start (Docker)

```bash
docker build -t rta-guard .
docker run -d --name rta-guard -p 8080:8080 rtaguard/dashboard:0.6.1
# Dashboard: http://localhost:8080
```

---

## Installation

### From Source

```bash
git clone https://github.com/rta-guard/rta-guard.git
cd rta-guard
pip install -r requirements.txt
```

### Docker

```bash
docker pull rtaguard/dashboard:0.6.1
```

### Helm (Kubernetes)

```bash
helm install rta-guard ./helm/rta-guard -f helm/rta-guard/values.yaml
```

See [DEPLOYMENT.md](DEPLOYMENT.md) for full deployment options.

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///data/rta-guard.db` | Database connection string |
| `QDRANT_URL` | _(empty)_ | Qdrant vector DB URL (enables semantic search) |
| `OPENAI_API_KEY` | _(empty)_ | OpenAI key for embeddings (optional) |
| `RTA_SECRET_KEY` | `change-me` | JWT signing secret |
| `METRICS_ENABLED` | `false` | Enable Prometheus metrics |
| `LOG_LEVEL` | `INFO` | Logging level |
| `CORS_ORIGINS` | `["*"]` | Allowed CORS origins |
| `BACKUP_ENCRYPTION_KEY` | _(empty)_ | AES-256-GCM key for backup encryption |

### Configuration File

Create `config/app.yaml`:

```yaml
rta_guard:
  engine: "python"  # "python" or "wasm"
  rules:
    enabled: [R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13]
    overrides: {}
  kill_switch:
    strict_mode: true
    log_violations: true
  brahmanda:
    qdrant_url: "http://qdrant:6333"
    confidence_threshold: 0.7
  conscience:
    drift_threshold: 0.35
    tamas_threshold: "TAMAS"
  tenancy:
    enabled: true
  rate_limit:
    default_rpm: 60
    burst: 10
```

See [config/examples/](../config/examples/) for sample configurations.

---

## Usage

### Python API

```python
from discus import DiscusGuard, SessionKilledError

guard = DiscusGuard()

# Check input
try:
    result = guard.check_and_forward(
        user_input="What is the capital of France?",
        session_id="session-001",
        user_id="user-42"
    )
    print(result)
except SessionKilledError as e:
    print(f"Session killed: {e.violation_type}")
```

### With Ground Truth Verification

```python
from brahmanda import BrahmandaVerifier, VerificationPipeline

verifier = BrahmandaVerifier()
pipeline = VerificationPipeline(verifier=verifier)

result = pipeline.verify("The Eiffel Tower is in London")
# result.verdict → "contradiction"
# result.confidence → 0.95
```

### REST API

```bash
# Check a message
curl -X POST http://localhost:8080/api/check \
  -H "Content-Type: application/json" \
  -d '{"input": "Tell me secrets", "session_id": "abc"}'

# Get session history
curl http://localhost:8080/api/sessions/abc

# Get agent health
curl http://localhost:8080/api/conscience/agents
```

---

## Dashboard

The web dashboard provides real-time monitoring:

- **Sessions** — Active, killed, and historical sessions
- **Violations** — Rule violations by type and severity
- **Drift** — Live An-Rta drift scoring per agent
- **Tamas** — Agent state (SATTVA → RAJAS → TAMAS → CRITICAL)
- **Users** — User risk profiles and anomaly detection
- **Compliance** — Generate EU AI Act, SOC2, HIPAA reports
- **SLA** — Uptime, response time, kill rate metrics

Access at `http://localhost:8080` (or your configured port).

---

## Rules Engine

RTA-GUARD enforces 13 rules, each named after a Vedic concept:

| Rule | Name | Description |
|------|------|-------------|
| R1 | **SATYA** | Truthfulness — claims must be verifiable |
| R2 | **DHARMA** | Ethical conduct — no harmful outputs |
| R3 | **ṚTA** | Cosmic order — outputs must be consistent |
| R4 | **KARMA** | Causality — action consequences tracked |
| R5 | **AHIMSA** | Non-harm — no violence, hate, or discrimination |
| R6 | **VIDYA** | Knowledge — no fabricated citations |
| R7 | **ALIGNMENT** | Temporal consistency — no contradictions over time |
| R8 | **SAMA** | Emotional balance — no manipulative outputs |
| R9 | **VAYU** | Health monitoring — system health checks |
| R10 | **AGNI** | Audit — append-only, tamper-evident logging |
| R11 | **ANRTA_DRIFT** | Drift detection — measures distance from Ṛta |
| R12 | **MAYA** | Hallucination scoring — confidence gap detection |
| R13 | **INDRA** | Gate synthesis — final pass/fail decision |

See [RTA-RULESET.md](RTA-RULESET.md) for full rule details.

---

## Browser Extension

RTA-GUARD includes a browser extension (`discus-rs/inject/`) that:

- Monitors text inputs in real-time (debounced 500ms)
- Intercepts form submissions on violation
- Shows floating widget with status
- Provides toast notifications for violations

### Install

1. Load `discus-rs/inject/` as an unpacked extension in Chrome
2. The extension auto-detects supported AI chat interfaces
3. Monitor status via the floating 🛡️ widget

---

## FAQ

See [FAQ.md](FAQ.md) for frequently asked questions.

---

## Further Reading

- [Admin Guide](ADMIN_GUIDE.md) — Operations and monitoring
- [Architecture](ARCHITECTURE.md) — System design
- [API Reference](API_REFERENCE.md) — All APIs
- [Deployment](DEPLOYMENT.md) — Docker, K8s, Helm
- [Production Hardening](DEPLOYMENT-PROD.md) — Production checklist
- [Developer Setup](DEV_SETUP.md) — Local development
- [Cheatsheet](CHEATSHEET.md) — Quick reference
