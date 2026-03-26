# RTA-GUARD — Monitoring & Observability (Phase 6.2)

## Overview

RTA-GUARD exposes Prometheus-compatible metrics for real-time monitoring of the kill-switch.
The monitoring stack includes:

- **Prometheus** — Metrics collection and alerting
- **Grafana** — Dashboards and visualization
- **Custom metrics** — 10 metrics covering kills, checks, drift, Tamas, SLA, and webhooks

## Quick Start

```bash
# Enable metrics (disabled by default)
export METRICS_ENABLED=true

# Start full stack with monitoring
docker compose up -d

# Access points:
# - Prometheus: http://localhost:9090
# - Grafana:    http://localhost:3000 (admin / rta-guard-admin)
# - /metrics:   http://localhost:8080/metrics
```

## Metrics Reference

### Counters

| Metric | Labels | Description |
|--------|--------|-------------|
| `discus_kill_total` | — | Total sessions killed by the guard |
| `discus_check_total` | `result` (pass/warn/kill) | Total guard checks performed |
| `discus_violation_total` | `severity` (low/medium/high/critical) | Total violations detected |
| `discus_webhook_sent_total` | `event_type` | Total webhook notifications sent |

### Gauges

| Metric | Labels | Description |
|--------|--------|-------------|
| `discus_active_sessions` | — | Currently alive sessions |
| `discus_drift_score` | `agent_id` | Current EMA-smoothed drift score (0–1) |
| `discus_tamas_level` | `agent_id` | Tamas level: 0=SATTVA, 1=RAJAS, 2=TAMAS, 3=CRITICAL |

### Histograms

| Metric | Buckets | Description |
|--------|---------|-------------|
| `discus_check_duration_seconds` | 1ms–2.5s | Duration of `guard.check()` calls |
| `discus_sla_response_time_seconds` | 10ms–5s | SLA-tracked API response time |

### Summaries

| Metric | Description |
|--------|-------------|
| `discus_kill_decision_time_seconds` | Time from check start to kill decision |

## Enabling Metrics

Metrics are **opt-in** — set the environment variable:

```bash
export METRICS_ENABLED=true
```

When disabled:
- `/metrics` endpoint returns 404
- No metric recording overhead
- `prometheus_client` not required

## Prometheus Setup

### Docker Compose (recommended)

The `docker-compose.yml` includes Prometheus and Grafana pre-configured:

```bash
docker compose up -d prometheus grafana
```

### Standalone

```bash
# Install Prometheus
# https://prometheus.io/download/

# Copy config
cp monitoring/prometheus.yml /etc/prometheus/prometheus.yml
cp monitoring/alerts.yml /etc/prometheus/

# Start
prometheus --config.file=/etc/prometheus/prometheus.yml
```

### Verify

```bash
# Check metrics are exposed
curl http://localhost:8080/metrics

# Check Prometheus targets
curl http://localhost:9090/api/v1/targets
```

## Grafana Dashboard

### Import (Docker Compose)

The dashboard is auto-provisioned via Docker Compose. Login to http://localhost:3000
with `admin` / `rta-guard-admin`.

### Manual Import

1. Open Grafana → Dashboards → Import
2. Upload `monitoring/grafana/dashboard.json`
3. Select your Prometheus datasource
4. Click Import

### Dashboard Panels

| Panel | Description |
|-------|-------------|
| **Sessions Killed (1h)** | Kill count in the last hour — red if >5 |
| **Guard Checks (1h)** | Total checks in the last hour |
| **Active Sessions** | Currently alive sessions |
| **Drift Score** | Latest drift score per agent — green→red gradient |
| **Kill Rate & Violation Rate** | Time series of kills/min and violations/min |
| **Check Results** | Stacked pass/warn/kill breakdown |
| **SLA Response Time Percentiles** | P50, P95, P99 response times |
| **Guard Check Duration** | Average and P95 check duration |
| **Drift Score Over Time** | Drift trends per agent with threshold bands |
| **Tamas State Over Time** | Tamas state transitions (SATTVA→CRITICAL) |
| **Webhook Delivery Rate** | Webhook delivery rate by event type |
| **Kill Decision Time** | Time from check start to kill |

## Alerting Rules

### Kill Rate

| Alert | Condition | Severity |
|-------|-----------|----------|
| `HighKillRate` | >5 kills/min for 5m | warning |
| `KillStorm` | >20 kills/min for 2m | critical |

### SLA

| Alert | Condition | Severity |
|-------|-----------|----------|
| `SlowResponseTime` | P95 > 1s for 5m | warning |
| `SlowGuardChecks` | Avg check > 500ms for 5m | warning |

### Drift

| Alert | Condition | Severity |
|-------|-----------|----------|
| `CriticalDrift` | Drift > 0.6 for 3m | critical |
| `UnhealthyDrift` | Drift > 0.35 for 5m | warning |

### Tamas

| Alert | Condition | Severity |
|-------|-----------|----------|
| `TamasDetected` | Level ≥ 2 for 2m | warning |
| `TamasCritical` | Level = 3 for 1m | critical |

### Webhooks

| Alert | Condition | Severity |
|-------|-----------|----------|
| `WebhookDeliveryGap` | Kills but no webhooks in 30m | warning |

### Sessions

| Alert | Condition | Severity |
|-------|-----------|----------|
| `HighSessionCount` | >10,000 active sessions for 5m | warning |

### Configuring Alertmanager

Uncomment the `alerting` section in `monitoring/prometheus.yml` and point
to your Alertmanager instance:

```yaml
alerting:
  alertmanagers:
    - static_configs:
        - targets:
            - alertmanager:9093
```

## Architecture

```
┌──────────────────────────────────────────────────┐
│                 RTA-GUARD Stack                   │
│                                                  │
│  ┌────────────┐    ┌─────────────┐    ┌────────┐ │
│  │  Dashboard  │───▶│  Prometheus │───▶│Grafana │ │
│  │  /metrics   │    │  :9090      │    │ :3000  │ │
│  └─────┬──────┘    └─────────────┘    └────────┘ │
│        │                                          │
│  ┌─────▼──────────────────────────────────────┐  │
│  │           brahmanda.metrics.py              │  │
│  │  Counters │ Gauges │ Histograms │ Summaries  │  │
│  └────────────────────────────────────────────┘  │
│        ▲         ▲          ▲           ▲        │
│        │         │          │           │        │
│  ┌─────┴──┐ ┌───┴────┐ ┌──┴────┐ ┌────┴─────┐  │
│  │ guard  │ │ SLA    │ │consc. │ │ webhooks │  │
│  │ .check │ │middleware│ │drift  │ │  .fire   │  │
│  └────────┘ └────────┘ └───────┘ └──────────┘  │
└──────────────────────────────────────────────────┘
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `METRICS_ENABLED` | `false` | Enable Prometheus metrics collection |
| `PROMETHEUS_PORT` | `9090` | Prometheus web UI port |
| `GRAFANA_PORT` | `3000` | Grafana web UI port |
| `GF_ADMIN_USER` | `admin` | Grafana admin username |
| `GF_ADMIN_PASSWORD` | `rta-guard-admin` | Grafana admin password |

## Integration Points

Metrics are recorded at these locations:

1. **`discus/guard.py`** — `check()` method:
   - Every check → `discus_check_total` counter
   - Every kill → `discus_kill_total` counter + `discus_kill_decision_time_seconds`
   - Every violation → `discus_violation_total` counter
   - Every webhook → `discus_webhook_sent_total` counter
   - Check duration → `discus_check_duration_seconds` histogram

2. **`dashboard/app.py`** — SLA middleware:
   - Every request → `discus_sla_response_time_seconds` histogram
   - `/metrics` endpoint → Prometheus scrape target
   - Drift/Tamas gauges updated on API calls

3. **`brahmanda/conscience.py`** — Via dashboard endpoints:
   - Drift recording → `discus_drift_score` gauge
   - Tamas state → `discus_tamas_level` gauge

## Backward Compatibility

- Metrics are **disabled by default** (`METRICS_ENABLED=false`)
- When disabled, no `prometheus_client` import or overhead
- No existing functionality is affected
- All existing tests pass without changes
