# RTA-GUARD — Developer Setup Guide

> **Version 0.6.1** | Local Development, Testing, Code Structure

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Setup](#quick-setup)
- [Project Structure](#project-structure)
- [Python Development](#python-development)
- [Rust Development (discus-rs)](#rust-development-discus-rs)
- [Browser Extension](#browser-extension)
- [Running Tests](#running-tests)
- [Docker Development](#docker-development)
- [Configuration](#configuration)
- [Debugging](#debugging)

---

## Prerequisites

### Required

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.10+ | Core application |
| pip | 23+ | Python packages |
| Rust | 1.75+ | WASM engine (`discus-rs`) |
| Docker | 24+ | Containerized development |
| Git | 2.30+ | Version control |

### Optional

| Tool | Purpose |
|------|---------|
| `wasm-pack` | Build WASM browser target |
| `wasm32-wasip1` target | Build WASI target |
| `maturin` | Python-Rust bindings |
| Node.js 18+ | Browser extension development |
| Docker Compose | Full stack local dev |
| PostgreSQL | Production-equivalent DB |
| Redis | Caching/rate limiting |
| Qdrant | Semantic search |

---

## Quick Setup

```bash
# 1. Clone
git clone https://github.com/rta-guard/rta-guard.git
cd rta-guard

# 2. Python environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Run tests (verify setup)
python3 -m pytest tests/ -v
python3 -m pytest brahmanda/ -v

# 4. Start the demo
python demo/chat_demo.py

# 5. Start the dashboard
python -m dashboard.app
# → http://localhost:8000
```

### With Docker Compose (Full Stack)

```bash
cp .env.example .env   # edit values
docker compose up -d
# Dashboard: http://localhost:8080
# Prometheus: http://localhost:9090
# Grafana: http://localhost:3000
# Kibana: http://localhost:5601
```

---

## Project Structure

```
rta-guard/
├── discus/                    # Core Python guard engine
│   ├── __init__.py            # DiscusGuard, SessionKilledError exports
│   ├── guard.py               # Main kill-switch interceptor
│   ├── rules.py               # 13 Vedic-inspired rules (R1-R13)
│   ├── rta_engine.py          # Rule evaluation orchestrator
│   ├── models.py              # ViolationType, Severity, GuardResult
│   ├── nemo.py                # NeMo Guardrails integration
│   └── llm.py                 # LLM client abstractions
│
├── brahmanda/                 # Ground truth + monitoring + enterprise
│   ├── __init__.py            # Public API exports
│   ├── verifier.py            # BrahmandaMap — ground truth DB
│   ├── pipeline.py            # VerificationPipeline
│   ├── qdrant_client.py       # Qdrant vector search
│   ├── confidence.py          # ConfidenceScorer
│   ├── attribution.py         # SourceRegistry, provenance
│   ├── mutation.py            # MutationTracker
│   ├── conscience.py          # ConscienceMonitor, LiveDriftScorer
│   ├── tamas.py               # TamasDetector (4-state model)
│   ├── temporal.py            # TemporalChecker
│   ├── user_monitor.py        # UserBehaviorTracker
│   ├── escalation.py          # EscalationChain
│   ├── tenancy.py             # TenantManager
│   ├── rbac.py                # RBACManager
│   ├── sso.py                 # SSOManager (OIDC/SAML)
│   ├── rate_limit.py          # RateLimiter
│   ├── sla_monitor.py         # SLATracker
│   ├── webhooks.py            # WebhookManager
│   ├── compliance.py          # ReportGenerator
│   ├── metrics.py             # Prometheus metrics
│   ├── logging_config.py      # Structured logging
│   ├── log_analyzer.py        # Log parsing/anomaly detection
│   ├── cost_monitor.py        # Cost tracking
│   ├── cost_report.py         # Cost reports + billing
│   ├── quotas.py              # Quota enforcement
│   ├── efficient_ops.py       # Batch/lazy/cache/compress
│   ├── backup.py              # BackupManager
│   ├── restore.py             # RestoreManager
│   ├── ha.py                  # HA: leader election, graceful shutdown
│   ├── replication.py         # Cross-region replication
│   ├── failover.py            # FailoverOrchestrator
│   ├── region.py              # Region routing
│   ├── config.py              # Configuration management
│   ├── models.py              # Shared data models
│   ├── test_*.py              # Unit tests (685+ tests)
│   └── __pycache__/
│
├── discus-rs/                 # Rust/WASM engine
│   ├── Cargo.toml
│   ├── src/
│   │   ├── lib.rs
│   │   ├── rta_engine.rs      # Core rules in Rust
│   │   └── ...
│   ├── bindings/
│   │   ├── python/            # PyO3 bindings
│   │   └── ...
│   ├── inject/                # Browser extension
│   └── build.sh               # Build script
│
├── dashboard/                 # Web UI + FastAPI server
│   ├── app.py                 # FastAPI application
│   └── static/                # Frontend assets
│
├── demo/                      # Demo applications
│   └── chat_demo.py
│
├── tests/                     # Integration tests
│   ├── test_discus.py
│   ├── test_discus_rs.py
│   ├── test_satya_pipeline.py
│   └── test_deployment.py
│
├── monitoring/                # Prometheus + Grafana configs
│   ├── prometheus.yml
│   ├── alerts.yml
│   └── grafana/
│
├── logging/                   # ELK stack configs
│   ├── logstash.conf
│   ├── kibana/
│   └── ...
│
├── helm/                      # Kubernetes Helm chart
│   └── rta-guard/
│
├── k8s/                       # Standalone K8s manifests
│
├── scripts/                   # Utility scripts
│   └── daily_report.py
│
├── docs/                      # Documentation
│
├── config/                    # Configuration examples
│
├── docker-compose.yml         # Full stack
├── Dockerfile                 # Production image
├── requirements.txt           # Python dependencies
└── .env.example               # Environment template
```

---

## Python Development

### Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Running Locally

```bash
# Dashboard (with auto-reload)
uvicorn dashboard.app:app --reload --host 0.0.0.0 --port 8000

# Demo chat
python demo/chat_demo.py

# With custom config
RTA_CONFIG=config/app.yaml python -m dashboard.app
```

### Code Style

- **Formatter:** `ruff format`
- **Linter:** `ruff check`
- **Security:** `bandit`

```bash
# Format
ruff format .

# Lint
ruff check . --fix

# Security scan
bandit -r discus/ brahmanda/ -ll
```

### Adding a New Rule

1. Define the rule in `discus/rules.py`:
   ```python
   @rule("R14_NEW_RULE", priority=5)
   def check_new_rule(input_text: str, context: dict) -> RuleResult:
       # Implementation
       return RuleResult(passed=True, rule_id="R14_NEW_RULE")
   ```

2. Register in `discus/rta_engine.py`:
   ```python
   from discus.rules import check_new_rule
   engine.register_rule(check_new_rule)
   ```

3. Add tests in `brahmanda/test_new_rule.py`:
   ```python
   def test_new_rule_pass():
       result = check_new_rule("safe input", {})
       assert result.passed

   def test_new_rule_violation():
       result = check_new_rule("bad input", {})
       assert not result.passed
       assert result.severity == Severity.HIGH
   ```

4. Update `docs/RTA-RULESET.md` with rule details.

---

## Rust Development (discus-rs)

### Setup

```bash
# Install Rust
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Add WASM targets
rustup target add wasm32-unknown-unknown
rustup target add wasm32-wasip1

# Install wasm-pack (for browser builds)
cargo install wasm-pack
```

### Build

```bash
cd discus-rs

# Native library (for Python bindings)
cargo build --release

# WASM browser
wasm-pack build --target web --out-dir ../pkg

# WASI
cargo build --target wasm32-wasip1 --release

# Python bindings via maturin
cd bindings/python
maturin develop --release
```

### Test

```bash
cd discus-rs
cargo test

# Run with output
cargo test -- --nocapture
```

### Lint

```bash
cargo clippy -- -D warnings
cargo fmt --check
```

---

## Browser Extension

The browser extension lives in `discus-rs/inject/`.

### Load for Development

1. Build the WASM: `cd discus-rs && wasm-pack build --target web`
2. Open Chrome → `chrome://extensions/`
3. Enable "Developer mode"
4. Click "Load unpacked" → select `discus-rs/inject/`
5. The 🛡️ widget appears on supported AI chat pages

### How It Works

- **Content script** (`content.js`) — monitors text inputs, debounced 500ms
- **Service worker** (`sw.js`) — loads WASM engine, evaluates rules
- **Popup** — shows current status and settings
- On violation: intercepts form submission, shows toast notification

---

## Running Tests

### Python Tests

```bash
# All tests
python3 -m pytest tests/ brahmanda/test_*.py -v

# Specific test file
python3 -m pytest brahmanda/test_conscience.py -v

# With coverage
python3 -m pytest tests/ --cov=discus --cov=brahmanda --cov-report=html

# Single test
python3 -m pytest brahmanda/test_conscience.py::test_drift_scoring -v
```

### Rust Tests

```bash
cd discus-rs
cargo test

# Specific test
cargo test test_engine_check
```

### Integration Tests

```bash
# Full stack test (requires Docker Compose running)
python3 -m pytest tests/test_deployment.py -v
```

### Test Counts

| Suite | Count | Location |
|-------|-------|----------|
| Python unit tests | 685+ | `brahmanda/test_*.py` |
| Rust tests | 26 | `discus-rs/src/` |
| Integration tests | 5 | `tests/` |

---

## Docker Development

### Build Locally

```bash
docker build -t rta-guard:dev .
docker run -d --name rta-guard -p 8080:8080 rta-guard:dev
```

### Full Stack

```bash
cp .env.example .env
docker compose up -d

# View logs
docker compose logs -f dashboard

# Rebuild after changes
docker compose up -d --build dashboard

# Shell into container
docker compose exec dashboard bash
```

### Debug a Container

```bash
# Override entrypoint for debugging
docker run -it --rm rta-guard:dev bash

# With environment
docker run -it --rm \
  -e DATABASE_URL="postgresql://..." \
  -e METRICS_ENABLED=true \
  rta-guard:dev bash
```

---

## Configuration

### Environment Variables

All configuration is via environment variables. See `.env.example` for the full list.

| Variable | Development | Production |
|----------|-------------|------------|
| `DATABASE_URL` | _(empty → SQLite)_ | `postgresql://...` |
| `RTA_SECRET_KEY` | `change-me` | Strong random |
| `LOG_LEVEL` | `DEBUG` | `WARNING` |
| `METRICS_ENABLED` | `false` | `true` |

### Config File (Optional)

Create `config/app.yaml`:

```yaml
rta_guard:
  engine: "python"
  rules:
    enabled: [R1, R2, R3, R4, R5, R6, R7, R8, R9, R10, R11, R12, R13]
  kill_switch:
    strict_mode: false  # true for production
  conscience:
    drift_threshold: 0.35
```

Set `RTA_CONFIG=config/app.yaml` to use it.

---

## Debugging

### Python

```bash
# With debugger
python -m debugpy --listen 5678 --wait-for-client -m dashboard.app

# Verbose logging
LOG_LEVEL=DEBUG python -m dashboard.app
```

### VS Code Launch Config

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Dashboard",
      "type": "python",
      "request": "launch",
      "module": "dashboard.app",
      "env": {"LOG_LEVEL": "DEBUG"}
    },
    {
      "name": "Tests",
      "type": "python",
      "request": "launch",
      "module": "pytest",
      "args": ["-v", "brahmanda/"]
    }
  ]
}
```

### Common Issues

| Problem | Fix |
|---------|-----|
| Import errors | Activate venv: `source .venv/bin/activate` |
| Port 8080 in use | `lsof -i :8080` or change `RTA_PORT` |
| Qdrant connection refused | Start Qdrant: `docker compose up -d qdrant` |
| WASM build fails | Update Rust: `rustup update` |
| Tests fail with SQLite lock | Ensure no other process is using the DB |

---

## Further Reading

- [Contributing Guide](CONTRIBUTING.md) — PR process, code review
- [Architecture](ARCHITECTURE.md) — System design
- [API Reference](API_REFERENCE.md) — All APIs
- [Release Process](RELEASE_PROCESS.md) — Versioning, changelog
- [Cheatsheet](CHEATSHEET.md) — Quick reference
