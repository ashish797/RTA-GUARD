# RTA-GUARD — Admin Guide

> **Version 0.6.1** | Operations, Monitoring, Backup/Restore, Troubleshooting

---

## Table of Contents

- [Operations Overview](#operations-overview)
- [Starting & Stopping](#starting--stopping)
- [Monitoring](#monitoring)
- [Logging](#logging)
- [Backup & Restore](#backup--restore)
- [Disaster Recovery](#disaster-recovery)
- [High Availability](#high-availability)
- [Security](#security)
- [Troubleshooting](#troubleshooting)

---

## Operations Overview

RTA-GUARD is a stateful service that requires operational attention in several areas:

| Area | Frequency | Reference |
|------|-----------|-----------|
| Metrics & alerts | Continuous | [MONITORING.md](MONITORING.md) |
| Log review | Daily | [LOGGING.md](LOGGING.md) |
| Backup verification | Daily | [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) |
| SLA review | Weekly | [COST.md](COST.md) |
| DR drill | Quarterly | [DISASTER_RECOVERY.md#dr-drill-instructions](DISASTER_RECOVERY.md) |
| Certificate rotation | Per policy | [DEPLOYMENT-PROD.md](DEPLOYMENT-PROD.md) |

---

## Starting & Stopping

### Docker

```bash
# Start
docker compose up -d

# Stop (graceful — drains active sessions)
docker compose stop

# Stop (immediate)
docker compose down

# Restart
docker compose restart rta-guard
```

### Kubernetes

```bash
# Start
helm install rta-guard ./helm/rta-guard

# Rolling restart (zero-downtime)
kubectl rollout restart deployment/rta-guard

# Scale
kubectl scale deployment rta-guard --replicas=3

# Stop
helm uninstall rta-guard
```

### Direct

```bash
# Start dashboard
python -m dashboard.app --host 0.0.0.0 --port 8080

# Start with config
RTA_CONFIG=config/app.yaml python -m dashboard.app
```

---

## Monitoring

See [MONITORING.md](MONITORING.md) for full details.

### Key Metrics to Watch

| Metric | Alert Threshold | Meaning |
|--------|----------------|---------|
| `discus_kill_total` | > 50/hour | Unusual kill spike |
| `discus_drift_score` | > 0.6 | Agent drift critical |
| `discus_tamas_level` | == 3 | Agent in CRITICAL state |
| `discus_check_duration_seconds` | p99 > 1s | Performance degradation |
| `discus_active_sessions` | > 1000 | Capacity alert |

### Quick Health Check

```bash
# API health
curl http://localhost:8080/health

# Metrics endpoint
curl http://localhost:8080/metrics

# Agent health
curl http://localhost:8080/api/conscience/agents
```

### Prometheus Alerts

The `monitoring/alerts.yml` includes pre-configured alerts:

- **HighKillRate** — kill rate > 10/min for 5 minutes
- **CriticalDrift** — drift score > 0.9
- **TamasCritical** — any agent in CRITICAL state
- **SlowResponse** — p95 response > 2 seconds
- **BackupStale** — last backup > 26 hours ago

---

## Logging

See [LOGGING.md](LOGGING.md) for full details.

### Log Levels

| Level | When Used |
|-------|-----------|
| DEBUG | Rule evaluation details, internal state |
| INFO | Guard checks (pass), session lifecycle |
| WARNING | Drift warnings, Tamas RAJAS, rate limit near |
| ERROR | Rule violations (kill), backup failures |
| CRITICAL | System failures, Tamas CRITICAL, split-brain |

### Structured Log Fields

Every log includes: `timestamp`, `level`, `message`, `service`, `session_id`, `agent_id`, `correlation_id`.

### Log Locations

| Deployment | Log Location |
|-----------|-------------|
| Docker | `docker logs rta-guard` / ELK stack |
| Kubernetes | `kubectl logs deployment/rta-guard` |
| Direct | stdout + `logs/rta-guard.log` (if configured) |

---

## Backup & Restore

See [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) for full procedures.

### Backup Schedule

| Type | Frequency | Retention | Encrypted |
|------|-----------|-----------|-----------|
| Full | Daily 02:00 UTC | 30 days | AES-256-GCM |
| Incremental | Every 6 hours | 7 days | AES-256-GCM |
| WAL/Snapshot | Continuous | Until next full | Yes |

### Manual Backup

```bash
# Via Python
python -c "
from brahmanda.backup import BackupManager
bm = BackupManager(storage_path='/backups', encryption_key='your-key')
result = bm.create_full_backup('/data/rta-guard.db', '/data/config')
print(result)
"

# Via API
curl -X POST http://localhost:8080/api/backup/create \
  -H "Authorization: Bearer $TOKEN"
```

### Restore

```bash
# Point-in-time restore
python -c "
from brahmanda.restore import RestoreManager
rm = RestoreManager(storage_path='/backups', encryption_key='your-key')
result = rm.restore_point_in_time(
    backup_id='backup-2026-03-25-0200',
    target_path='/data/restore',
    dry_run=False
)
print(result)
"
```

---

## Disaster Recovery

### RPO / RTO Targets

| Target | Value |
|--------|-------|
| RPO (Recovery Point Objective) | ≤ 6 hours |
| RTO (Recovery Time Objective) | ≤ 1 hour |

### DR Drill

Quarterly DR drills are mandatory. See [DISASTER_RECOVERY.md#dr-drill-instructions](DISASTER_RECOVERY.md) for the full runbook.

Quick drill:

```bash
# 1. Create test backup
# 2. Simulate failure
# 3. Restore from backup
# 4. Verify data integrity
# 5. Document results
```

---

## High Availability

See [HA.md](HA.md) for full details.

### Single-Node (Default)

- SQLite for state, file-based leader election
- Suitable for dev/staging and low-traffic production

### Multi-Region

- PostgreSQL for shared state
- Redis-based leader election
- Async replication with last-write-wins
- Geo-routing with latency budgets
- Automatic failover with split-brain detection

```yaml
# Helm values for HA
ha:
  enabled: true
  regions:
    - name: us-east-1
      primary: true
    - name: us-west-2
      failoverPriority: 1
    - name: eu-west-1
      failoverPriority: 2
```

---

## Security

### Authentication

- **Token auth** — Bearer tokens for API access
- **SSO** — OIDC (Keycloak, Auth0) and SAML supported
- **RBAC** — 4 roles: ADMIN, OPERATOR, VIEWER, AUDITOR

### Data Protection

- All backups encrypted with AES-256-GCM
- TLS 1.3 for all connections (recommended)
- Secrets via Kubernetes Secrets or Vault
- No PII stored in logs (redacted by default)

### Audit Trail

Every action is logged with SHA-256 hash chain:
- Tamper-evident append-only log
- Full provenance tracking
- Compliance report generation (EU AI Act, SOC2, HIPAA)

---

## Troubleshooting

### Common Issues

#### Session killed unexpectedly

```bash
# Check violation details
curl http://localhost:8080/api/sessions/{session_id}

# Check drift score
curl http://localhost:8080/api/conscience/agents/{agent_id}
```

#### High drift score

1. Check agent's recent interactions: `GET /api/conscience/agents/{id}`
2. Review Tamas state: `GET /api/conscience/tamas/{id}`
3. Check temporal consistency: `GET /api/temporal/{id}`
4. Consider resetting agent if stuck: `DELETE /api/conscience/agents/{id}`

#### Backup failing

1. Check encryption key is set: `echo $BACKUP_ENCRYPTION_KEY`
2. Check disk space: `df -h /backups`
3. Check logs: `grep "backup" logs/rta-guard.log`
4. Verify permissions: `ls -la /backups/`

#### Dashboard not loading

1. Check service is running: `curl http://localhost:8080/health`
2. Check CORS: `CORS_ORIGINS` must include your domain
3. Check port binding: `netstat -tlnp | grep 8080`

#### Qdrant connection issues

```bash
# Check Qdrant is reachable
curl http://qdrant:6333/health

# Disable Qdrant (graceful fallback)
unset QDRANT_URL
```

### Getting Help

- **Docs**: `docs/` directory
- **FAQ**: [FAQ.md](FAQ.md)
- **Cheatsheet**: [CHEATSHEET.md](CHEATSHEET.md)
- **Issues**: GitHub Issues
