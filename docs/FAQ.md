# RTA-GUARD — FAQ

> **Version 0.6.1** | Frequently Asked Questions, Common Pitfalls, Troubleshooting

---

## General

### What is RTA-GUARD?

RTA-GUARD (Real-Time Alignment Guardian) is a **deterministic AI safety layer** that wraps your AI application. When a violation is detected — PII leak, prompt injection, jailbreak attempt — the session is killed instantly, not just filtered. Named after the Vedic concept of **Ṛta** (cosmic order).

### How is it different from content filters?

Content filters *redact* or *modify* outputs. RTA-GUARD **kills the session** — a hard stop. This prevents continued exploitation, not just blocking a single response.

### What are the "13 Vedic rules"?

RTA-GUARD enforces 13 safety rules named after Vedic concepts: SATYA (truthfulness), DHARMA (ethics), ṚTA (consistency), KARMA (causality), AHIMSA (non-harm), VIDYA (knowledge), ALIGNMENT (temporal), SAMA (emotional balance), VAYU (health), AGNI (audit), ANRTA_DRIFT (drift), MAYA (hallucination), INDRA (gate synthesis). See [RTA-RULESET.md](RTA-RULESET.md).

### Is RTA-GUARD open source?

Yes — Apache 2.0 license.

---

## Installation & Setup

### What Python version is required?

Python 3.10 or later.

### Do I need Rust installed?

Only if you want to build the WASM engine (`discus-rs`). The Python-only engine works without Rust.

### Can I run it without Docker?

Yes. Install Python dependencies and run directly:
```bash
pip install -r requirements.txt
python -m dashboard.app
```

### What databases are supported?

- **SQLite** (default, automatic fallback) — good for development and small deployments
- **PostgreSQL** (recommended for production)
- **Qdrant** (optional, for semantic search / Brahmanda Map)

### How do I enable the monitoring stack?

```bash
export METRICS_ENABLED=true
docker compose up -d
```
See [MONITORING.md](MONITORING.md).

---

## Usage

### How do I integrate RTA-GUARD into my app?

3 lines of Python:
```python
from discus import DiscusGuard
guard = DiscusGuard()
response = guard.check_and_forward(user_input, session_id="abc123")
```
See [USER_GUIDE.md](USER_GUIDE.md) for more options.

### What happens when a session is killed?

1. `SessionKilledError` is raised
2. Violation is logged (audit trail)
3. Webhooks fire (if configured)
4. Metrics are updated
5. Drift score is updated for the agent

### Can I disable specific rules?

Yes. In config:
```yaml
rta_guard:
  rules:
    enabled: [R1, R2, R3, R5, R7]  # only these rules active
```

### How do I get the violation details?

```python
try:
    guard.check_and_forward(input, session_id="abc")
except SessionKilledError as e:
    print(e.violation_type)  # PII_LEAK, PROMPT_INJECTION, etc.
    print(e.severity)        # LOW, MEDIUM, HIGH, CRITICAL
    print(e.rule_id)         # e.g., "R3_MITRA"
    print(e.reason)          # Human-readable explanation
```

### What is the Brahmanda Map?

The "cosmic egg" ground truth system. It stores known facts and verifies AI claims against them. If the AI says "The Eiffel Tower is in London," Brahmanda flags it as a contradiction. Requires Qdrant for semantic search; works with SQLite for exact matching.

### What is drift scoring?

An-Rta drift measures how far an agent's behavior has drifted from its baseline. It uses an EMA (exponential moving average) over 5 components: semantic drift, alignment drift, consistency drift, confidence drift, and violation trend. Score ranges from 0 (healthy) to 1 (critical).

### What is Tamas detection?

A 4-state behavioral model: SATTVA (healthy) → RAJAS (agitated) → TAMAS (degraded) → CRITICAL. State transitions use hysteresis to prevent flapping.

---

## Configuration

### Where do I put configuration?

Environment variables (see `.env.example`) or a YAML config file (`config/app.yaml`). Environment variables take precedence.

### How do I change the port?

```bash
export RTA_PORT=9090
# or in Docker:
docker run -e RTA_PORT=9090 ...
```

### How do I enable CORS for my frontend?

```bash
export CORS_ORIGINS='["https://myapp.example.com"]'
```

### Can I use multiple LLM providers?

Yes. RTA-GUARD is provider-agnostic — it intercepts input before it reaches the LLM. Configure your LLM client separately.

---

## Troubleshooting

### Sessions are being killed unexpectedly

1. Check which rule triggered: `GET /api/sessions/{id}`
2. Check drift score: `GET /api/conscience/agents/{agent_id}`
3. Check Tamas state: `GET /api/conscience/tamas/{agent_id}`
4. Lower `drift_threshold` if too sensitive (default: 0.35)

### Dashboard won't load

1. Is the service running? `curl http://localhost:8080/health`
2. Check CORS: `CORS_ORIGINS` must include your domain
3. Check port: `netstat -tlnp | grep 8080`
4. Check logs: `docker logs rta-guard`

### Database connection errors

```bash
# Test PostgreSQL from container
docker exec rta-guard python -c "
import sqlalchemy
engine = sqlalchemy.create_engine('$DATABASE_URL')
print(engine.execute('SELECT 1').scalar())
"
```

### Qdrant not connecting

```bash
curl http://localhost:6333/healthz
```
RTA-GUARD degrades gracefully — falls back to keyword-only search without Qdrant.

### High memory usage

- Check active sessions: `discus_active_sessions` metric
- Reduce `pool_size` in database config
- Enable batch processing: `BATCH_PROCESSING_ENABLED=true`
- Check for memory leaks in custom rules

### Backup encryption key not found

```bash
kubectl get secret rta-guard-backup-encryption
# If missing:
kubectl create secret generic rta-guard-backup-encryption \
  --from-literal=key=$(openssl rand -hex 32)
```

### WASM build fails

```bash
# Update Rust
rustup update

# Reinstall wasm target
rustup target add wasm32-unknown-unknown
rustup target add wasm32-wasip1

# Reinstall wasm-pack
cargo install wasm-pack
```

---

## Performance

### What's the overhead of guard checks?

Typical `guard.check()` latency is **1–5ms** (Python) or **<1ms** (Rust/WASM). See `discus_check_duration_seconds` metric.

### How many sessions can it handle?

Depends on infrastructure. Single-node with SQLite: ~1,000 concurrent sessions. With PostgreSQL + Redis + horizontal scaling: 10,000+.

### Does the Brahmanda Map slow things down?

Only when Qdrant is enabled for semantic search (adds ~10-50ms per verification). SQLite-based exact matching is <1ms.

### How do I optimize costs?

Enable cost optimization features:
```bash
export BATCH_PROCESSING_ENABLED=true   # batch kills (20-30% savings)
export LAZY_DRIFT_ENABLED=true          # on-demand drift scoring (40-60%)
export AUDIT_COMPRESSION_ENABLED=true   # gzip logs (70-80% storage)
export CACHE_WARMING_ENABLED=true       # pre-compute rules (20%)
```
See [COST.md](COST.md).

---

## Deployment

### Can I deploy without Kubernetes?

Yes — Docker Compose works fine for single-node deployments. See [DEPLOYMENT.md](DEPLOYMENT.md).

### How do I scale horizontally?

The dashboard is stateless (state in DB/Redis):
```bash
docker compose up -d --scale dashboard=3
# or
kubectl scale deployment rta-guard --replicas=3
```

### How do I do zero-downtime updates?

```bash
helm upgrade rta-guard ./helm/rta-guard --set image.tag=0.6.2 --wait
```

### What about multi-region?

Set `ha.enabled=true` in Helm values. See [HA.md](HA.md).

---

## Security

### How are audit logs protected?

SHA-256 hash chain — each entry includes the hash of the previous entry, making tampering detectable.

### How are backups encrypted?

AES-256-GCM with a separate encryption key. See [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md).

### Is PII stored in logs?

No. PII is redacted by default in structured logs.

### What authentication is supported?

- Bearer tokens (API)
- OIDC (Keycloak, Auth0, etc.)
- SAML
- RBAC with 4 roles: ADMIN, OPERATOR, VIEWER, AUDITOR

---

## Contributing

### How do I add a new rule?

See [DEV_SETUP.md](DEV_SETUP.md#adding-a-new-rule) for the step-by-step process.

### How do I report a bug?

Open a GitHub Issue with reproduction steps. For security vulnerabilities, email security@rta-guard.dev (don't open public issues).

### How do I become a maintainer?

Regular, quality contributions (PRs, reviews, docs) — you'll be invited. See [CONTRIBUTING.md](CONTRIBUTING.md).
