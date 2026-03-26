# RTA-GUARD Deployment Guide

> Phase 6.1 — Ecosystem Integration (Docker / Docker Compose / Helm / Kubernetes)

---

## Table of Contents

- [Quick Start (Docker)](#1-quick-start-docker)
- [Docker Compose (Full Stack)](#2-docker-compose-full-stack)
- [Kubernetes (Helm)](#3-kubernetes-helm)
- [Kubernetes (Standalone Manifests)](#4-kubernetes-standalone-manifests)
- [Environment Variables](#environment-variables)
- [Health Checks](#health-checks)
- [Scaling](#scaling)
- [Troubleshooting](#troubleshooting)

---

## 1. Quick Start (Docker)

Single container — dashboard + Discus guard engine only.

```bash
# Build
docker build -t rtaguard/dashboard:0.6.1 .

# Run (with SQLite fallback)
docker run -d \
  --name rta-guard \
  -p 8080:8080 \
  -v rta-data:/app/data \
  rtaguard/dashboard:0.6.1

# Run (with PostgreSQL)
docker run -d \
  --name rta-guard \
  -p 8080:8080 \
  -e DATABASE_URL="postgresql://rta:secret@host:5432/rtaguard" \
  -e RTA_SECRET_KEY="your-secret" \
  -v rta-data:/app/data \
  rtaguard/dashboard:0.6.1
```

Dashboard available at `http://localhost:8080`.

---

## 2. Docker Compose (Full Stack)

Full production stack: Dashboard + PostgreSQL + Redis + Qdrant.

```bash
# Copy environment template
cp .env.example .env   # edit values

# Start all services
docker compose up -d

# View logs
docker compose logs -f dashboard

# Stop
docker compose down

# Stop + remove data
docker compose down -v
```

### Services

| Service    | Port  | Purpose                          |
|------------|-------|----------------------------------|
| dashboard  | 8080  | RTA-GUARD web UI + API           |
| postgres   | 5432  | Primary database (Brahmanda)     |
| redis      | 6379  | Caching + rate limiting          |
| qdrant     | 6333  | Vector database (semantic search)|

### Volumes

Data is persisted under `./data/`:
- `./data/pgdata` — PostgreSQL data
- `./data/redis` — Redis AOF
- `./data/qdrant` — Qdrant storage
- `./data/dashboard` — Dashboard data (SQLite fallback, audit logs)

---

## 3. Kubernetes (Helm)

Recommended for production. Uses the Helm chart at `helm/rta-guard/`.

```bash
# Add dependencies (if using subchart Postgres/Redis)
helm dependency update helm/rta-guard/

# Install
helm install rta-guard helm/rta-guard/ \
  --namespace rta-guard \
  --create-namespace \
  --set image.tag=0.6.1 \
  --set ingress.enabled=true \
  --set ingress.hosts[0].host=rta-guard.example.com

# Upgrade
helm upgrade rta-guard helm/rta-guard/ \
  --namespace rta-guard \
  --set image.tag=0.6.2

# Uninstall
helm uninstall rta-guard -n rta-guard
```

### Helm Values (Key)

```yaml
# values.yaml overrides
replicaCount: 2
image:
  tag: "0.6.1"
resources:
  requests:
    cpu: 250m
    memory: 256Mi
  limits:
    cpu: "1"
    memory: 512Mi
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
ingress:
  enabled: true
  hosts:
    - host: rta-guard.example.com
      paths:
        - path: /
          pathType: Prefix
secrets:
  RTA_SECRET_KEY: "your-production-secret"
  POSTGRES_PASSWORD: "secure-password"
```

### Lint & Validate

```bash
helm lint helm/rta-guard/
helm template rta-guard helm/rta-guard/ | kubectl apply --dry-run=client -f -
```

---

## 4. Kubernetes (Standalone Manifests)

For environments without Helm. Apply directly with kubectl.

```bash
# Create namespace
kubectl create namespace rta-guard

# Edit secrets first!
vi k8s/secret.yaml

# Apply all manifests
kubectl apply -f k8s/ -n rta-guard

# Check status
kubectl get pods -n rta-guard
kubectl logs -f deployment/rta-guard -n rta-guard
```

### Manifests

| File            | Description                    |
|-----------------|--------------------------------|
| deployment.yaml | 2-replica deployment           |
| service.yaml    | ClusterIP service on :8080     |
| configmap.yaml  | Non-sensitive env vars         |
| secret.yaml     | Secrets (edit before applying!)|
| pvc.yaml        | 5Gi persistent volume          |
| ingress.yaml    | nginx ingress (edit host)      |
| hpa.yaml        | HPA: 1-5 replicas, 75% CPU    |

---

## Environment Variables

### Required

| Variable         | Description                     | Default              |
|------------------|---------------------------------|----------------------|
| `DATABASE_URL`   | PostgreSQL connection string    | SQLite fallback      |
| `RTA_SECRET_KEY` | Secret key for auth/signing     | `change-me` (⚠️)     |

### Optional

| Variable          | Description                         | Default             |
|-------------------|-------------------------------------|---------------------|
| `REDIS_URL`       | Redis connection string             | —                   |
| `QDRANT_URL`      | Qdrant endpoint                     | —                   |
| `QDRANT_API_KEY`  | Qdrant API key                      | —                   |
| `OPENAI_API_KEY`  | OpenAI key (for embeddings)         | —                   |
| `RTA_AUTH_TOKEN`  | Bearer token for API auth           | —                   |
| `PYTHONUNBUFFERED`| Disable Python output buffering     | `1`                 |

### Database Fallback

RTA-GUARD supports **PostgreSQL** (recommended for production) and **SQLite** (automatic fallback):

- If `DATABASE_URL` is set → uses PostgreSQL
- If `DATABASE_URL` is empty → uses SQLite at `/app/data/rta-guard.db`
- If `REDIS_URL` is set → uses Redis for caching/rate limiting
- If `REDIS_URL` is empty → in-memory cache (single-process only)
- If `QDRANT_URL` is set → vector search enabled (Brahmanda)
- If `QDRANT_URL` is empty → keyword-only search (degraded but functional)

---

## Health Checks

### Endpoints

| Endpoint         | Description                              |
|------------------|------------------------------------------|
| `GET /api/health`| Liveness/readiness — returns 200 if OK   |
| `GET /`          | Dashboard UI (WebSocket live updates)    |
| `GET /docs`      | Swagger UI (OpenAPI)                     |

### Docker

Built-in `HEALTHCHECK` in Dockerfile:
```dockerfile
HEALTHCHECK --interval=30s --timeout=5s \
    CMD curl -f http://localhost:8080/api/health || exit 1
```

### Kubernetes

Both liveness and readiness probes configured:
```yaml
livenessProbe:
  httpGet:
    path: /api/health
    port: 8080
  initialDelaySeconds: 15
  periodSeconds: 20
readinessProbe:
  httpGet:
    path: /api/health
    port: 8080
  initialDelaySeconds: 10
  periodSeconds: 10
```

---

## Scaling

### Horizontal Scaling

**Dashboard** is stateless (state in DB/Redis), so safe to scale horizontally:
```bash
# Docker Compose
docker compose up -d --scale dashboard=3

# Kubernetes
kubectl scale deployment rta-guard --replicas=3 -n rta-guard

# Helm
helm upgrade rta-guard helm/rta-guard/ --set replicaCount=3
```

### HPA (Auto-scaling)

Enabled via Helm:
```yaml
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
  targetCPUUtilizationPercentage: 75
```

### Database Scaling

- **PostgreSQL**: Use managed services (RDS, Cloud SQL, Neon) for production
- **Redis**: Use Redis Sentinel or Redis Cluster for HA
- **Qdrant**: Qdrant Cloud or multi-node deployment

### Resource Estimates

| Component  | CPU (req/lim) | Memory (req/lim) |
|------------|---------------|------------------|
| Dashboard  | 250m / 1      | 256Mi / 512Mi    |
| PostgreSQL | 250m / 1      | 256Mi / 1Gi      |
| Redis      | 100m / 250m   | 128Mi / 256Mi    |
| Qdrant     | 250m / 1      | 256Mi / 1Gi      |

---

## Troubleshooting

### Dashboard won't start

```bash
# Check logs
docker logs rta-guard-dashboard
kubectl logs deployment/rta-guard -n rta-guard

# Common issues:
# 1. Missing DATABASE_URL → falls back to SQLite (OK)
# 2. PostgreSQL not ready → add depends_on / init containers
# 3. Port conflict → change RTA_PORT
```

### Database connection errors

```bash
# Test PostgreSQL from dashboard container
docker exec rta-guard-dashboard python -c "
import sqlalchemy
engine = sqlalchemy.create_engine('$DATABASE_URL')
print(engine.execute('SELECT 1').scalar())
"
```

### Qdrant not connecting

```bash
# Verify Qdrant is running
curl http://localhost:6333/healthz

# Dashboard degrades gracefully without Qdrant (keyword search only)
```

---

## Production Checklist

- [ ] Change `RTA_SECRET_KEY` to a strong random value
- [ ] Set `POSTGRES_PASSWORD` to a strong value
- [ ] Enable TLS via ingress (cert-manager or manual)
- [ ] Set up database backups
- [ ] Configure monitoring (Prometheus/Grafana)
- [ ] Set up log aggregation
- [ ] Review RBAC and auth settings
- [ ] Test failover and scaling
- [ ] Set `image.pullPolicy: IfNotPresent` in air-gapped environments
