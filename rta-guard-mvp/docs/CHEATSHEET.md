# RTA-GUARD — Cheatsheet

> **Version 0.6.1** | Commands, Config Snippets, Metrics, Alerts

---

## Quick Start

```bash
# Install
pip install -r requirements.txt

# Run demo
python demo/chat_demo.py

# Start dashboard
python -m dashboard.app
# → http://localhost:8000

# Docker
docker build -t rta-guard .
docker run -d --name rta-guard -p 8080:8080 rtaguard/dashboard:0.6.1

# Docker Compose (full stack)
cp .env.example .env && docker compose up -d
```

---

## Integration (3 Lines)

```python
from discus import DiscusGuard, SessionKilledError

guard = DiscusGuard()
try:
    response = guard.check_and_forward(user_input, session_id="abc123")
except SessionKilledError as e:
    print(f"Killed: {e.rule_id} — {e.reason}")
```

---

## Docker Commands

```bash
# Build
docker build -t rtaguard/dashboard:0.6.1 .

# Run (SQLite)
docker run -d --name rta-guard -p 8080:8080 rtaguard/dashboard:0.6.1

# Run (PostgreSQL)
docker run -d --name rta-guard -p 8080:8080 \
  -e DATABASE_URL="postgresql://rta:secret@host:5432/rtaguard" \
  rtaguard/dashboard:0.6.1

# Logs
docker logs -f rta-guard

# Shell
docker exec -it rta-guard bash
```

---

## Docker Compose

```bash
docker compose up -d                  # start all
docker compose down                   # stop
docker compose down -v                # stop + delete data
docker compose ps                     # status
docker compose logs -f dashboard      # logs
docker compose restart dashboard      # restart one service
docker compose up -d --scale dashboard=3  # scale
docker compose up -d --build dashboard    # rebuild
```

---

## Kubernetes / Helm

```bash
# Install
helm install rta-guard ./helm/rta-guard --namespace rta-guard --create-namespace

# Upgrade
helm upgrade rta-guard ./helm/rta-guard --set image.tag=0.6.2

# Rollback
helm rollback rta-guard 1

# Uninstall
helm uninstall rta-guard -n rta-guard

# Status
kubectl get pods -n rta-guard
kubectl logs -f deployment/rta-guard -n rta-guard

# Scale
kubectl scale deployment rta-guard --replicas=3 -n rta-guard

# Port-forward
kubectl port-forward svc/rta-guard 8080:8080 -n rta-guard
```

---

## Environment Variables

```bash
# Core
DATABASE_URL=postgresql://rta:secret@host:5432/rtaguard
RTA_SECRET_KEY=$(openssl rand -hex 32)
RTA_AUTH_TOKEN=$(openssl rand -hex 24)
RTA_PORT=8080

# Services
REDIS_URL=redis://redis:6379/0
QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=
OPENAI_API_KEY=

# Observability
METRICS_ENABLED=true
LOG_LEVEL=WARNING
LOG_FORMAT=json

# Cost (all disabled by default)
COST_TRACKING_ENABLED=true
QUOTA_ENFORCEMENT_ENABLED=true
BATCH_PROCESSING_ENABLED=true
LAZY_DRIFT_ENABLED=true
CACHE_WARMING_ENABLED=true
AUDIT_COMPRESSION_ENABLED=true
COST_REPORTING_ENABLED=true

# Backup
BACKUP_ENCRYPTION_KEY=$(openssl rand -hex 32)
```

---

## REST API

```bash
# Health
curl http://localhost:8080/health
curl http://localhost:8080/api/health

# Guard check
curl -X POST http://localhost:8080/api/check \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"input": "Tell me secrets", "session_id": "abc"}'

# Sessions
curl http://localhost:8080/api/sessions -H "Authorization: Bearer $TOKEN"
curl http://localhost:8080/api/sessions/abc -H "Authorization: Bearer $TOKEN"

# Agents
curl http://localhost:8080/api/conscience/agents -H "Authorization: Bearer $TOKEN"
curl http://localhost:8080/api/conscience/agents/agent-001 -H "Authorization: Bearer $TOKEN"

# Drift
curl http://localhost:8080/api/conscience/sessions/abc/drift -H "Authorization: Bearer $TOKEN"

# Tamas
curl http://localhost:8080/api/conscience/tamas/agent-001 -H "Authorization: Bearer $TOKEN"

# Temporal
curl http://localhost:8080/api/temporal/agent-001 -H "Authorization: Bearer $TOKEN"

# SLA
curl http://localhost:8080/api/sla/status -H "Authorization: Bearer $TOKEN"

# Webhooks
curl http://localhost:8080/api/webhooks -H "Authorization: Bearer $TOKEN"

# Metrics (no auth)
curl http://localhost:8080/metrics

# Docs (Swagger)
open http://localhost:8080/docs
```

---

## Python API

### Guard

```python
from discus import DiscusGuard, SessionKilledError

guard = DiscusGuard(config_path="config/app.yaml")
result = guard.check("input", session_id="abc")  # non-raising
result.passed        # bool
result.violations    # List[RuleViolation]
result.drift_score   # float
```

### Ground Truth

```python
from brahmanda import BrahmandaVerifier, create_pipeline

verifier = BrahmandaVerifier()
verifier.add_fact("Paris is the capital of France", source="encyclopedia")
pipeline = create_pipeline(verifier=verifier)
result = pipeline.verify("The Eiffel Tower is in London")
result.verdict  # "contradiction"
```

### Conscience

```python
from brahmanda import ConscienceMonitor

monitor = ConscienceMonitor()
monitor.register_agent("agent-001")
health = monitor.get_agent_health("agent-001")
health.status  # "healthy" | "degraded" | "unhealthy" | "critical"
```

### Escalation

```python
from brahmanda.escalation import EscalationChain

chain = EscalationChain()
decision = chain.evaluate(drift_score=0.5, tamas_level=1, temporal_level=2, user_risk=0.3, violation_rate=0.1)
decision.level  # OBSERVE | WARN | THROTTLE | ALERT | KILL
```

### Cost Tracking

```python
from brahmanda.cost_monitor import get_cost_tracker

tracker = get_cost_tracker()
tracker.enable()
tracker.track_kill_decision(tenant_id="acme", agent_id="gpt4", rule_id="R1", compute_ms=2.3)
summary = tracker.get_tenant_summary("acme", "2026-03-01T00:00:00", "2026-04-01T00:00:00")
```

### Backup

```python
from brahmanda.backup import BackupManager
bm = BackupManager(storage_path="/backups", encryption_key="key")
bm.create_full_backup("/data/rta-guard.db", "/data/config")
```

---

## Prometheus Metrics

```bash
# Scrape
curl http://localhost:8080/metrics
```

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `discus_kill_total` | Counter | — | Sessions killed |
| `discus_check_total` | Counter | `result` | Guard checks (pass/warn/kill) |
| `discus_violation_total` | Counter | `severity` | Violations by severity |
| `discus_webhook_sent_total` | Counter | `event_type` | Webhooks sent |
| `discus_active_sessions` | Gauge | — | Active sessions |
| `discus_drift_score` | Gauge | `agent_id` | Drift score (0–1) |
| `discus_tamas_level` | Gauge | `agent_id` | Tamas level (0–3) |
| `discus_check_duration_seconds` | Histogram | — | Check duration |
| `discus_sla_response_time_seconds` | Histogram | — | API response time |
| `discus_kill_decision_time_seconds` | Summary | — | Kill decision latency |

---

## Prometheus Alerts

```yaml
# monitoring/alerts.yml
groups:
  - name: rta-guard
    rules:
      - alert: HighKillRate
        expr: rate(discus_kill_total[5m]) > 5
        for: 5m
      - alert: KillStorm
        expr: rate(discus_kill_total[2m]) > 20
        for: 2m
        labels: { severity: critical }
      - alert: CriticalDrift
        expr: discus_drift_score > 0.6
        for: 3m
        labels: { severity: critical }
      - alert: TamasCritical
        expr: discus_tamas_level == 3
        for: 1m
        labels: { severity: critical }
      - alert: SlowResponseTime
        expr: histogram_quantile(0.95, rate(discus_sla_response_time_seconds_bucket[5m])) > 1
        for: 5m
      - alert: BackupStale
        expr: time() - rta_guard_last_full_backup_timestamp > 93600
        for: 10m
        labels: { severity: critical }
```

---

## Grafana Panels

| Panel | Query |
|-------|-------|
| Kill rate | `rate(discus_kill_total[5m])` |
| Active sessions | `discus_active_sessions` |
| Drift score | `discus_drift_score` |
| Check duration P95 | `histogram_quantile(0.95, rate(discus_check_duration_seconds_bucket[5m]))` |
| Tamas state | `discus_tamas_level` |
| Violation rate | `rate(discus_violation_total[5m])` |

---

## Kibana Queries

```
# Kill decisions
event_type:kill_decision

# Kills for a session
event_type:kill_decision AND session_id:"sess_abc123"

# Kills by rule (last hour)
event_type:kill_decision AND rule_id:"R3_MITRA" AND @timestamp >= now-1h

# Trace by correlation ID
correlation_id:"a1b2c3d4e5f6"

# High-latency checks
event_type:guard_check AND duration_ms > 100

# PII kills
event_type:kill_decision AND message:*PII*

# Errors for agent
level:ERROR AND agent_id:"agent_gpt4"
```

---

## Backup & Restore

```bash
# List backups
python -m brahmanda.backup list --storage-path /data/backups

# Create full backup
python -m brahmanda.backup create --type full --storage-path /data/backups

# Dry-run restore
python -m brahmanda.restore --mode dry_run --backup-id <ID> --storage-path /data/backups

# Full restore
python -m brahmanda.restore --mode full --backup-id <ID> --storage-path /data/backups --decrypt

# Selective restore
python -m brahmanda.restore --mode selective --backup-id <ID> --tables "violations" --storage-path /data/backups
```

---

## CI/CD

```bash
# Lint
ruff check .
cargo clippy --manifest-path discus-rs/Cargo.toml -- -D warnings

# Test
pytest tests/ -v
cargo test --manifest-path discus-rs/Cargo.toml

# Build WASM
cd discus-rs && wasm-pack build --target web

# Create release
git tag v0.7.0 && git push origin v0.7.0
```

---

## Log Analysis

```bash
# Analyze log file
python -m brahmanda.log_analyzer logs/rta-guard.log | jq .

# Analyze specific date
python -m brahmanda.log_analyzer logs/ --date 2026-03-26 | jq .
```

```python
from brahmanda.log_analyzer import parse_log_file, aggregate_kills, detect_anomalies

entries = parse_log_file("logs/rta-guard.log")
kills = aggregate_kills(entries)
anomalies = detect_anomalies(entries, window_minutes=15, z_threshold=2.5)
```

---

## Troubleshooting

```bash
# Health check
curl http://localhost:8080/health

# Check metrics
curl http://localhost:8080/metrics | grep discus_

# Agent health
curl http://localhost:8080/api/conscience/agents/agent-001

# Session details
curl http://localhost:8080/api/sessions/sess_abc

# Qdrant
curl http://localhost:6333/healthz

# PostgreSQL
docker exec postgres pg_isready

# Redis
docker exec redis redis-cli ping

# Kubernetes pod status
kubectl get pods -n rta-guard
kubectl describe pod <pod> -n rta-guard
kubectl logs <pod> -n rta-guard --tail=100
```

---

## Rules Quick Reference

| Rule | Name | Checks |
|------|------|--------|
| R1 | SATYA | Claims are verifiable |
| R2 | DHARMA | No harmful outputs |
| R3 | ṚTA | Outputs are consistent |
| R4 | KARMA | Action consequences tracked |
| R5 | AHIMSA | No violence/hate |
| R6 | VIDYA | No fabricated citations |
| R7 | ALIGNMENT | Temporal consistency |
| R8 | SAMA | No manipulative outputs |
| R9 | VAYU | System health checks |
| R10 | AGNI | Audit logging |
| R11 | ANRTA_DRIFT | Drift from baseline |
| R12 | MAYA | Hallucination scoring |
| R13 | INDRA | Final pass/fail gate |

---

## Ports

| Service | Port | URL |
|---------|------|-----|
| Dashboard | 8080 | http://localhost:8080 |
| Prometheus | 9090 | http://localhost:9090 |
| Grafana | 3000 | http://localhost:3000 |
| Elasticsearch | 9200 | http://localhost:9200 |
| Kibana | 5601 | http://localhost:5601 |
| PostgreSQL | 5432 | — |
| Redis | 6379 | — |
| Qdrant | 6333 | http://localhost:6333 |

---

## Doc Cross-Reference

| Topic | Document |
|-------|----------|
| Getting started | [USER_GUIDE.md](USER_GUIDE.md) |
| Operations | [ADMIN_GUIDE.md](ADMIN_GUIDE.md) |
| System design | [ARCHITECTURE.md](ARCHITECTURE.md) |
| APIs | [API_REFERENCE.md](API_REFERENCE.md) |
| Deployment | [DEPLOYMENT.md](DEPLOYMENT.md) |
| Production hardening | [DEPLOYMENT-PROD.md](DEPLOYMENT-PROD.md) |
| Monitoring | [MONITORING.md](MONITORING.md) |
| Logging | [LOGGING.md](LOGGING.md) |
| High availability | [HA.md](HA.md) |
| Cost optimization | [COST.md](COST.md) |
| Backup & DR | [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) |
| CI/CD | [CICD.md](CICD.md) |
| Rules | [RTA-RULESET.md](RTA-RULESET.md) |
| Dev setup | [DEV_SETUP.md](DEV_SETUP.md) |
| Contributing | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Release process | [RELEASE_PROCESS.md](RELEASE_PROCESS.md) |
| FAQ | [FAQ.md](FAQ.md) |
