# RTA-GUARD — Production Deployment Hardening

> **Version 0.6.1** | Builds on [DEPLOYMENT.md](DEPLOYMENT.md)

---

## Table of Contents

- [Pre-Production Checklist](#pre-production-checklist)
- [Secrets Management](#secrets-management)
- [TLS & Network Security](#tls--network-security)
- [Database Hardening](#database-hardening)
- [Container Security](#container-security)
- [Resource Limits & Quotas](#resource-limits--quotas)
- [Rate Limiting & DDoS](#rate-limiting--ddos)
- [Logging & Audit](#logging--audit)
- [Monitoring & Alerting](#monitoring--alerting)
- [Backup & Recovery](#backup--recovery)
- [Rolling Updates & Rollback](#rolling-updates--rollback)
- [Compliance](#compliance)

---

## Pre-Production Checklist

Before going live, verify every item:

### Secrets & Config

- [ ] `RTA_SECRET_KEY` — strong random value (≥32 chars, `openssl rand -hex 32`)
- [ ] `POSTGRES_PASSWORD` — strong, unique password
- [ ] `RTA_AUTH_TOKEN` — set for API authentication
- [ ] `QDRANT_API_KEY` — set if Qdrant is exposed
- [ ] `BACKUP_ENCRYPTION_KEY` — AES-256 key for backup encryption
- [ ] No secrets in Git, Dockerfiles, or Helm values committed to repo
- [ ] `.env` file is in `.gitignore`

### Infrastructure

- [ ] PostgreSQL is a managed service (RDS, Cloud SQL, Neon) — not containerized
- [ ] Redis has persistence enabled (AOF) and is HA (Sentinel or Cluster)
- [ ] Qdrant is backed by persistent volumes with replication
- [ ] TLS terminates at ingress (cert-manager or external LB)
- [ ] Network policies restrict pod-to-pod traffic

### Application

- [ ] `LOG_LEVEL=WARNING` (not DEBUG)
- [ ] `METRICS_ENABLED=true` with Prometheus scrape configured
- [ ] CORS origins restricted (not `["*"]`)
- [ ] Health check endpoints verified (`/api/health`)
- [ ] Backup CronJob is running and verified (see [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md))

---

## Secrets Management

### Kubernetes Secrets

Never store secrets in ConfigMaps or plain values files.

```bash
# Create secrets
kubectl create secret generic rta-guard-secrets \
  --namespace rta-guard \
  --from-literal=RTA_SECRET_KEY="$(openssl rand -hex 32)" \
  --from-literal=POSTGRES_PASSWORD="$(openssl rand -base64 24)" \
  --from-literal=RTA_AUTH_TOKEN="$(openssl rand -hex 24)" \
  --from-literal=BACKUP_ENCRYPTION_KEY="$(openssl rand -hex 32)"
```

### External Secrets (Recommended)

For production, use an external secrets operator:

```yaml
# ExternalSecret example (external-secrets.io)
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: rta-guard
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: rta-guard-secrets
  data:
    - secretKey: RTA_SECRET_KEY
      remoteRef:
        key: rta-guard/production
        property: secret_key
    - secretKey: POSTGRES_PASSWORD
      remoteRef:
        key: rta-guard/production
        property: postgres_password
```

### Vault Integration

```bash
# Store secrets in Vault
vault kv put secret/rta-guard/production \
  RTA_SECRET_KEY="$(openssl rand -hex 32)" \
  POSTGRES_PASSWORD="$(openssl rand -base64 24)"
```

---

## TLS & Network Security

### Ingress TLS (cert-manager)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: rta-guard
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
    nginx.ingress.kubernetes.io/ssl-redirect: "true"
    nginx.ingress.kubernetes.io/force-ssl-redirect: "true"
spec:
  tls:
    - hosts:
        - rta-guard.example.com
      secretName: rta-guard-tls
  rules:
    - host: rta-guard.example.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: rta-guard
                port:
                  number: 8080
```

### Network Policies

Restrict inter-pod traffic:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: rta-guard-policy
spec:
  podSelector:
    matchLabels:
      app: rta-guard
  policyTypes:
    - Ingress
    - Egress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              name: ingress
      ports:
        - port: 8080
  egress:
    - to:
        - podSelector:
            matchLabels:
              app: postgres
      ports:
        - port: 5432
    - to:
        - podSelector:
            matchLabels:
              app: redis
      ports:
        - port: 6379
    - to:
        - podSelector:
            matchLabels:
              app: qdrant
      ports:
        - port: 6333
    - to:  # DNS
        - namespaceSelector: {}
      ports:
        - port: 53
          protocol: UDP
```

### Security Headers

Add via ingress annotations or middleware:

```yaml
nginx.ingress.kubernetes.io/configuration-snippet: |
  more_set_headers "X-Content-Type-Options: nosniff";
  more_set_headers "X-Frame-Options: DENY";
  more_set_headers "X-XSS-Protection: 1; mode=block";
  more_set_headers "Strict-Transport-Security: max-age=31536000; includeSubDomains";
  more_set_headers "Content-Security-Policy: default-src 'self'";
```

---

## Database Hardening

### PostgreSQL

```sql
-- Create dedicated user with minimal privileges
CREATE ROLE rta_guard WITH LOGIN PASSWORD 'strong-password';
CREATE DATABASE rta_guard OWNER rta_guard;

-- Enable SSL
-- In postgresql.conf:
-- ssl = on
-- ssl_cert_file = '/path/to/server.crt'
-- ssl_key_file = '/path/to/server.key'

-- Restrict connections
-- In pg_hba.conf:
-- hostssl rta_guard rta_guard 10.0.0.0/8 scram-sha-256
```

### Connection Pooling

Use PgBouncer or built-in SQLAlchemy pooling:

```python
# In application config
engine = create_engine(
    DATABASE_URL,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=300,
)
```

### SQLite (Development Only)

SQLite is not recommended for production. If used:
- Enable WAL mode: `PRAGMA journal_mode=WAL;`
- Set busy timeout: `PRAGMA busy_timeout=5000;`
- Regular backups (see [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md))

---

## Container Security

### Non-Root Execution

The Dockerfile runs as non-root by default. Verify:

```bash
docker run --rm rtaguard/dashboard:0.6.1 id
# uid=1000(rta) gid=1000(rta)
```

### Read-Only Filesystem

```yaml
# Kubernetes
securityContext:
  readOnlyRootFilesystem: true
  runAsNonRoot: true
  runAsUser: 1000
  allowPrivilegeEscalation: false
  capabilities:
    drop:
      - ALL
```

### Image Scanning

CI includes Trivy container scanning (see [CICD.md](CICD.md)). Run manually:

```bash
trivy image rtaguard/dashboard:0.6.1
```

### Image Signing (Optional)

```bash
# Sign with cosign
cosign sign --key cosign.key rtaguard/dashboard:0.6.1

# Verify
cosign verify --key cosign.pub rtaguard/dashboard:0.6.1
```

---

## Resource Limits & Quotas

### Pod Resources

```yaml
resources:
  requests:
    cpu: 250m
    memory: 256Mi
  limits:
    cpu: "1"
    memory: 512Mi
```

### Namespace Quotas

```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: rta-guard-quota
spec:
  hard:
    requests.cpu: "4"
    requests.memory: 4Gi
    limits.cpu: "8"
    limits.memory: 8Gi
    pods: "20"
```

### LimitRange

```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: rta-guard-limits
spec:
  limits:
    - default:
        cpu: 500m
        memory: 256Mi
      defaultRequest:
        cpu: 100m
        memory: 128Mi
      type: Container
```

---

## Rate Limiting & DDoS

### Application-Level

RTA-GUARD includes built-in rate limiting (see [COST.md](COST.md)):

```yaml
# Helm values
rateLimit:
  enabled: true
  defaultRpm: 60
  burst: 10
  perTenant: true
```

### Ingress-Level

```yaml
nginx.ingress.kubernetes.io/limit-rps: "50"
nginx.ingress.kubernetes.io/limit-burst-multiplier: "5"
nginx.ingress.kubernetes.io/limit-connections: "20"
```

### WAF (Optional)

For public-facing deployments, add a WAF layer (AWS WAF, Cloudflare, etc.).

---

## Logging & Audit

### Production Logging Config

```bash
LOG_LEVEL=WARNING
LOG_FORMAT=json
LOG_TO_FILE=true
LOG_MAX_BYTES=10485760  # 10MB
LOG_BACKUP_COUNT=5
```

### Audit Log Integrity

Audit logs use SHA-256 hash chains for tamper evidence. Verify:

```bash
python -c "
from brahmanda.log_analyzer import parse_log_file
entries = parse_log_file('logs/rta-guard.log')
# Hash chain verification built into parser
print(f'Parsed {len(entries)} entries')
"
```

See [LOGGING.md](LOGGING.md) for ELK integration.

---

## Monitoring & Alerting

### Critical Alerts

Ensure these alerts are configured in Prometheus (see [MONITORING.md](MONITORING.md)):

| Alert | Condition | Action |
|-------|-----------|--------|
| `KillStorm` | >20 kills/min | Investigate immediately |
| `CriticalDrift` | Drift > 0.6 | Check agent behavior |
| `BackupStale` | Last backup > 26h | Check backup CronJob |
| `SlowResponseTime` | P95 > 1s | Scale or investigate |
| `TamasCritical` | Agent CRITICAL | Kill or reset agent |

### Grafana Dashboards

Import the pre-built dashboard from `monitoring/grafana/dashboard.json`. Key panels:

- Kill rate (time series)
- Active sessions (gauge)
- Drift score per agent (heatmap)
- SLA response percentiles (time series)
- Tamas state transitions (state timeline)

---

## Backup & Recovery

### Verify Backups Work

```bash
# List backups
kubectl exec -it <pod> -- python -m brahmanda.backup list \
  --storage-path /data/backups

# Dry-run restore
kubectl exec -it <pod> -- python -m brahmanda.restore \
  --mode dry_run \
  --backup-id <LATEST_ID> \
  --storage-path /data/backups \
  --decrypt
```

See [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) for full procedures.

---

## Rolling Updates & Rollback

### Zero-Downtime Deploy

```bash
# Helm upgrade (rolling update)
helm upgrade rta-guard ./helm/rta-guard \
  --set image.tag=0.6.2 \
  --wait \
  --timeout 5m

# Verify
kubectl rollout status deployment/rta-guard
```

### Rollback

```bash
# Rollback to previous revision
helm rollback rta-guard 1

# Or to specific revision
helm history rta-guard
helm rollback rta-guard <REVISION>
```

### Blue-Green (Optional)

For zero-risk deploys:

```bash
# Deploy green alongside blue
helm install rta-guard-green ./helm/rta-guard \
  --set image.tag=0.6.2 \
  --set ingress.host=rta-guard-green.example.com

# Verify green, then switch ingress
# ... test ...
kubectl patch ingress rta-guard -p '{"spec":{"rules":[{"host":"rta-guard.example.com","http":{"paths":[{"path":"/","pathType":"Prefix","backend":{"service":{"name":"rta-guard-green","port":{"number":8080}}}}]}}]}}'

# Remove blue
helm uninstall rta-guard-blue
```

---

## Compliance

### EU AI Act

RTA-GUARD supports EU AI Act compliance reporting:

```bash
curl -X POST http://localhost:8080/api/reports/generate \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"type": "eu_ai_act", "period": "2026-Q1"}'
```

### SOC2

- Audit logs with hash chain integrity
- RBAC with 4 roles (ADMIN, OPERATOR, VIEWER, AUDITOR)
- SSO integration (OIDC/SAML)
- Encrypted backups at rest

### HIPAA

- PHI redaction in logs (default behavior)
- Encrypted backups (AES-256-GCM)
- Audit trail with full provenance
- Access controls via RBAC

See [COST.md](COST.md) for pricing tiers and compliance features per tier.

---

## Summary

| Area | Key Setting | Reference |
|------|-------------|-----------|
| Secrets | External secrets operator | This doc |
| TLS | cert-manager + ingress | This doc |
| Database | Managed PostgreSQL | [DEPLOYMENT.md](DEPLOYMENT.md) |
| Containers | Non-root, read-only FS | This doc |
| Resources | CPU/memory limits | [DEPLOYMENT.md](DEPLOYMENT.md) |
| Rate limiting | App + ingress level | This doc |
| Logging | JSON + ELK | [LOGGING.md](LOGGING.md) |
| Monitoring | Prometheus + Grafana | [MONITORING.md](MONITORING.md) |
| Backup | Encrypted, verified daily | [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) |
| HA | Multi-region with failover | [HA.md](HA.md) |
| CI/CD | GitHub Actions | [CICD.md](CICD.md) |
