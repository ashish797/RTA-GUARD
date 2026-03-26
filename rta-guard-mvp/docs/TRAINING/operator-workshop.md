# RTA-GUARD Operator Workshop — 2-Day Agenda

> **Duration:** 2 days (16 hours) | **Level:** Intermediate | **Version 0.6.1**

---

## Day 1 — Architecture, Deployment & Core Operations

### Session 1 — Architecture Deep Dive (09:00–10:30)

**Topics:**
- RTA-GUARD system architecture — 6 subsystems
- Discus Guard engine — kill-switch mechanics
- Brahmanda Map — ground truth verification
- Conscience Monitor — behavioral profiling
- Enterprise Layer — tenancy, RBAC, SSO
- Sudarshan WASM Engine — Rust/WASM execution model

**Lab 1.1 — Architecture Walkthrough**
- Walk through the component diagram from [ARCHITECTURE.md](../ARCHITECTURE.md)
- Trace a request through: API → Discus → Brahmanda → Conscience → Response
- Identify failure modes for each component

**Reading:** [ARCHITECTURE.md](../ARCHITECTURE.md)

---

### ☕ Break (10:30–10:45)

---

### Session 2 — Deployment Methods (10:45–12:15)

**Topics:**
- Docker single-container deployment
- Docker Compose full stack (Guard + PostgreSQL + Redis)
- Kubernetes with Helm charts
- Environment variables and secrets management
- Health checks and readiness probes

**Lab 2.1 — Docker Deployment**
```bash
# Deploy full stack with Docker Compose
git clone https://github.com/your-org/rta-guard.git
cd rta-guard
docker compose -f docker-compose.yml up -d

# Verify
docker compose ps
curl http://localhost:8080/health
```

**Lab 2.2 — Kubernetes Deployment**
```bash
# Install with Helm
helm install rta-guard ./helm/rta-guard \
  --namespace rta-guard --create-namespace \
  --set postgresql.enabled=true \
  --set ingress.enabled=true \
  --set ingress.host=rta.example.com

# Verify
kubectl get pods -n rta-guard
kubectl get svc -n rta-guard
```

**Reading:** [DEPLOYMENT.md](../DEPLOYMENT.md)

---

### 🍽️ Lunch (12:15–13:15)

---

### Session 3 — Rules Engine Mastery (13:15–14:45)

**Topics:**
- The 13 Vedic rules (R1–R13) — purpose and internals
- Rule configuration YAML syntax
- Severity levels: info → warning → critical → kill
- Actions: log → warn → block → kill
- Hot-reloading rules without downtime
- Writing custom rules with regex and context matching

**Lab 3.1 — Rule Analysis**
```bash
# List all active rules
docker compose exec rta-guard rta rules list

# Inspect a specific rule
docker compose exec rta-guard rta rules show R4_PRIVACY

# Test a rule against sample input
echo "The SSN is 123-45-6789" | docker compose exec -T rta-guard rta rules test R4_PRIVACY
```

**Lab 3.2 — Custom Rule Creation**
```yaml
# Write a custom rule for credit card detection
rules:
  R4_CREDIT_CARD:
    enabled: true
    severity: "critical"
    action: "kill"
    patterns:
      - '\b(?:4\d{3}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4})\b'  # Visa
      - '\b(?:5[1-5]\d{2}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4})\b'  # Mastercard
    description: "Detects credit card numbers in agent output"
```

**Lab 3.3 — Hot-Reload**
```bash
# Modify rules.yml, then reload
docker compose exec rta-guard rta rules reload
# Verify change is live — no restart required
docker compose exec rta-guard rta rules list | grep R4_CREDIT_CARD
```

**Reading:** [RTA-RULESET.md](../RTA-RULESET.md)

---

### ☕ Break (14:45–15:00)

---

### Session 4 — Monitoring & Alerting (15:00–16:30)

**Topics:**
- Prometheus metrics exposed by RTA-GUARD
- Grafana dashboard provisioning
- Alert rules for SLA violations
- Log structure and ELK/Loki integration
- Conscience Monitor alerting on behavioral drift

**Lab 4.1 — Prometheus Metrics**
```bash
# View raw metrics
curl http://localhost:8080/metrics | grep rta_

# Key metrics:
# rta_requests_total          — total requests processed
# rta_kills_total             — sessions killed
# rta_latency_seconds         — request latency histogram
# rta_rule_activations_total  — per-rule activation count
# rta_conscience_drift_score  — behavioral drift (0–1)
```

**Lab 4.2 — Grafana Dashboard Import**
```bash
# If Grafana is running on port 3000:
# 1. Open http://localhost:3000
# 2. Import dashboard JSON from helm/rta-guard/dashboards/
# 3. Set Prometheus datasource
# 4. Verify panels populate
```

**Lab 4.3 — Create a Kill-Rate Alert**
```yaml
# prometheus-rules.yml
groups:
  - name: rta-guard-alerts
    rules:
      - alert: HighKillRate
        expr: rate(rta_kills_total[5m]) > 10
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Kill rate exceeds 10/min for 2+ minutes"
```

**Reading:** [MONITORING.md](../MONITORING.md), [LOGGING.md](../LOGGING.md)

---

### Day 1 Wrap-Up (16:30–17:00)

- Q&A
- Review Day 1 concepts
- Preview Day 2 topics
- **Homework:** Deploy RTA-GUARD to a test Kubernetes cluster using the medium config example

---

## Day 2 — HA, Security, Cost Optimization & Incident Response

### Session 5 — High Availability & Multi-Region (09:00–10:30)

**Topics:**
- HA architecture: leader election, failover, split-brain detection
- Multi-region deployment: geo-routing, replication
- PostgreSQL HA: streaming replication, automatic failover
- Redis HA: Sentinel or Cluster mode
- Autoscaling configuration (HPA/VPA)

**Lab 5.1 — Simulate Failover**
```bash
# Kill the leader pod
kubectl delete pod -n rta-guard -l role=leader

# Watch failover
kubectl get pods -n rta-guard -w
# Verify: new leader elected within 30s
curl http://localhost:8080/health
```

**Lab 5.2 — Multi-Region Config**
```bash
# Deploy second region
helm install rta-guard-east ./helm/rta-guard \
  --namespace rta-guard-east --create-namespace \
  --set global.region=us-east-1 \
  --set replication.peerUrl=https://rta-west.internal:8443

# Verify cross-region replication
kubectl exec -n rta-guard-east deploy/rta-guard -- rta replication status
```

**Reading:** [HA.md](../HA.md)

---

### ☕ Break (10:30–10:45)

---

### Session 6 — Backup, DR & Incident Response (10:45–12:15)

**Topics:**
- Backup strategies: pg_dump, WAL archiving, S3 snapshots
- RPO/RTO targets and achieving them
- Disaster recovery drills
- Incident response playbook
- Post-mortem process

**Lab 6.1 — Backup & Restore**
```bash
# Full backup
docker compose exec postgres pg_dump -U rta rtaguard > backup_$(date +%Y%m%d).sql

# Verify backup
psql -f backup_*.sql --set ON_ERROR_STOP=on -d rtaguard_test

# Point-in-time recovery
docker compose exec postgres pg_basebackup -D /backup -Ft -z -P
```

**Lab 6.2 — DR Drill**
```bash
# Follow the DR drill procedure
# 1. Simulate primary failure
# 2. Promote standby
# 3. Verify data integrity
# 4. Measure RTO
# 5. Failback to primary
```

**Reading:** [DISASTER_RECOVERY.md](../DISASTER_RECOVERY.md)

---

### 🍽️ Lunch (12:15–13:15)

---

### Session 7 — Security Hardening (13:15–14:45)

**Topics:**
- TLS termination and certificate management
- RBAC and SSO integration (SAML/OIDC)
- Secrets management (Vault, Kubernetes secrets)
- Network policies and firewall rules
- Audit logging and compliance

**Lab 7.1 — RBAC Configuration**
```yaml
# rbac.yml
roles:
  - name: operator
    permissions: [rules:read, rules:reload, metrics:read, events:read]
  - name: admin
    permissions: ["*"]
  - name: viewer
    permissions: [metrics:read, events:read]
```

**Lab 7.2 — TLS Setup**
```bash
# Generate self-signed cert for testing
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout tls.key -out tls.crt -subj "/CN=rta.local"

# Configure in Helm
helm upgrade rta-guard ./helm/rta-guard \
  --set tls.enabled=true \
  --set tls.certName=rta-tls
```

**Reading:** [ADMIN_GUIDE.md#security](../ADMIN_GUIDE.md#security)

---

### ☕ Break (14:45–15:00)

---

### Session 8 — Cost Optimization & Capacity Planning (15:00–16:00)

**Topics:**
- Resource sizing guidelines (small/medium/large)
- Cost modeling and optimization strategies
- Right-sizing: CPU, memory, storage
- Autoscaling thresholds and tuning
- Multi-tenant cost allocation

**Lab 8.1 — Capacity Planning Exercise**
```
Given:
- 10,000 API calls/hour
- Average latency target: < 50ms
- Kill rate: ~2%
- 3 regions required

Calculate:
- Number of replicas per region
- CPU/memory requests and limits
- PostgreSQL instance size
- Redis memory allocation
```

**Lab 8.2 — Autoscaling Tuning**
```bash
# View current HPA
kubectl get hpa -n rta-guard

# Adjust scaling thresholds
kubectl edit hpa -n rta-guard rta-guard
# Set: targetCPUUtilizationPercentage: 60
# Set: minReplicas: 2, maxReplicas: 10
```

**Reading:** [COST.md](../COST.md)

---

### Session 9 — Graduation & Certification (16:00–16:30)

**Final Exercise — Full Incident Simulation**

Teams of 2–3 simulate a production incident:

1. **Alert fires:** Kill rate spikes to 50/min
2. **Diagnosis:** Identify the cause (bad rule? attack? bug?)
3. **Response:** Apply fix (rule reload, traffic shift, rollback)
4. **Verification:** Confirm resolution via metrics
5. **Post-mortem:** Write a 1-page incident report

**Evaluation Criteria:**
- Time to detection: < 5 min
- Time to resolution: < 15 min
- Correct root cause identification
- Post-mortem quality

---

## Workshop Materials

| Resource | Location |
|----------|----------|
| Quick Start Course | [quickstart-course.md](quickstart-course.md) |
| Architecture Docs | [../ARCHITECTURE.md](../ARCHITECTURE.md) |
| Deployment Guide | [../DEPLOYMENT.md](../DEPLOYMENT.md) |
| Admin Guide | [../ADMIN_GUIDE.md](../ADMIN_GUIDE.md) |
| API Reference | [../API_REFERENCE.md](../API_REFERENCE.md) |
| Example Configs | [../../config/examples/](../../config/examples/) |

---

*RTA-GUARD v0.6.1 — The seatbelt for AI.*
