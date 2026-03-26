# RTA-GUARD — Cost Optimization Guide (Phase 6.6)

## Overview

RTA-GUARD's cost optimization system provides production-grade cost tracking, quota enforcement, operation efficiency, and billing integration. All features are **opt-in** — disabled by default to maintain backward compatibility.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Cost Optimization Layer                   │
├──────────┬──────────┬──────────────────┬────────────────────┤
│  Cost    │  Quotas  │  Efficient Ops   │  Cost Reports      │
│  Monitor │  System  │  (Batch/Lazy/    │  (Daily/Weekly/    │
│          │          │   Cache/Compress) │   Monthly + CSV)   │
├──────────┴──────────┴──────────────────┴────────────────────┤
│                 SQLite Persistence Layer                     │
└─────────────────────────────────────────────────────────────┘
```

## Feature Flags

All cost optimization features are disabled by default. Enable via environment variables:

| Feature | Env Variable | Default | Description |
|---------|-------------|---------|-------------|
| Cost Tracking | `COST_TRACKING_ENABLED` | `false` | Track per-event costs |
| Quota Enforcement | `QUOTA_ENFORCEMENT_ENABLED` | `false` | Enforce per-tenant limits |
| Batch Processing | `BATCH_PROCESSING_ENABLED` | `false` | Batch kill decisions |
| Lazy Drift Scoring | `LAZY_DRIFT_ENABLED` | `false` | Compute drift on-demand |
| Cache Warming | `CACHE_WARMING_ENABLED` | `false` | Pre-compute common rules |
| Audit Compression | `AUDIT_COMPRESSION_ENABLED` | `false` | gzip audit log storage |
| Cost Reporting | `COST_REPORTING_ENABLED` | `false` | Generate cost reports |

```bash
# Enable all cost features
export COST_TRACKING_ENABLED=true
export QUOTA_ENFORCEMENT_ENABLED=true
export BATCH_PROCESSING_ENABLED=true
export LAZY_DRIFT_ENABLED=true
export CACHE_WARMING_ENABLED=true
export AUDIT_COMPRESSION_ENABLED=true
export COST_REPORTING_ENABLED=true
```

---

## Pricing Model

### Unit Costs

Costs are tracked in **micro-cents** (1/1,000,000 of a cent) for precision:

| Resource Type | Unit Cost (μ¢) | Approx USD | Description |
|--------------|----------------|------------|-------------|
| `kill_decision` | 50 | $0.0005 | Per session termination |
| `drift_check` | 10 | $0.0001 | Per drift score evaluation |
| `api_call` | 5 | $0.00005 | Per API request |
| `storage_mb_hour` | 2 | $0.00002 | Per MB-hour of storage |
| `webhook_delivery` | 15 | $0.00015 | Per webhook sent |
| `compliance_report` | 500 | $0.005 | Per report generated |
| `drift_score_compute` | 20 | $0.0002 | Per drift computation |
| `audit_log_entry` | 1 | $0.00001 | Per audit log entry |
| `session_tracking` | 3 | $0.00003 | Per session tracked |

### Cost Categories

Resources are grouped into categories for reporting:

- **COMPUTE** — Kill decisions, drift scoring, rule evaluation
- **STORAGE** — Audit logs, DB entries, state persistence
- **NETWORK** — API calls, webhooks, replication
- **REPORTING** — Compliance and cost reports
- **MONITORING** — SLA checks, session tracking

---

## Pricing Tiers

| Feature | Free | Starter | Pro | Enterprise |
|---------|------|---------|-----|------------|
| Kills/hour | 5 | 50 | 500 | Unlimited |
| Kills/day | 50 | 500 | 5,000 | Unlimited |
| Checks/hour | 100 | 1,000 | 10,000 | Unlimited |
| Checks/day | 1,000 | 10,000 | 100,000 | Unlimited |
| API calls/hour | 200 | 2,000 | 20,000 | Unlimited |
| Storage | 100 MB | 1 GB | 10 GB | Unlimited |
| Agents | 3 | 20 | 100 | Unlimited |
| Webhooks/hour | 10 | 100 | 1,000 | Unlimited |
| Concurrent sessions | 10 | 50 | 200 | Unlimited |
| Monthly cap | $0 (free) | $49 | $199 | Custom |

### Quota Enforcement

Quotas have two levels:

- **Soft limit** (80% of hard limit): Triggers a warning callback but allows the operation
- **Hard limit**: Blocks the operation and records a violation

```python
from brahmanda.quotas import get_quota_manager

manager = get_quota_manager()
manager.enable()

# Create tenant with Pro tier
manager.create_tenant("acme", tier="pro")

# Check and consume quota before an operation
allowed = manager.check_and_consume("acme", "max_kills_per_hour")
if not allowed:
    raise QuotaExceeded("Kill hourly quota exceeded")

# Get current usage status
status = manager.get_usage_status("acme")
```

---

## Cost Tracking

### Basic Usage

```python
from brahmanda.cost_monitor import get_cost_tracker

tracker = get_cost_tracker()
tracker.enable()

# Track a kill decision
tracker.track_kill_decision(
    tenant_id="acme",
    agent_id="gpt4",
    rule_id="R1",
    compute_ms=2.3,
)

# Track an API call
tracker.track_api_call("acme", endpoint="/api/check")

# Get cost summary
summary = tracker.get_tenant_summary("acme", "2026-03-01T00:00:00", "2026-04-01T00:00:00")
print(f"Total cost: ${summary['total_cost_dollars']:.4f}")
print(f"By category: {summary['by_category']}")
```

### Cost Attribution

Costs are attributed to:
- **Tenant** — Primary grouping
- **Agent** — Which AI agent generated the cost
- **Rule** — Which rule triggered the operation
- **Resource type** — What kind of operation (kill, check, etc.)

### Anomaly Detection

The anomaly detector uses z-score spike detection and trend analysis:

```python
from brahmanda.cost_monitor import CostAnomalyDetector

detector = CostAnomalyDetector(store=cost_store)
anomalies = detector.detect_anomalies("acme", lookback_days=30)

for a in anomalies:
    print(f"{a.anomaly_type}: {a.description} (severity: {a.severity})")
```

Detects:
- **Spikes** — Sudden cost increases (z-score > 2.0)
- **Drift** — Gradual cost increases over time (>30% over baseline)

### Optimization Recommendations

```python
from brahmanda.cost_monitor import CostOptimizer

optimizer = CostOptimizer(store=cost_store)
recs = optimizer.generate_recommendations("acme", "2026-03-01", "2026-04-01")

for r in recs:
    print(f"{r.title}: saves ~{r.estimated_savings_pct}% (${r.estimated_savings_usd:.4f})")
```

Typical recommendations:
1. **Batch kill decisions** — 20-30% savings on kill-heavy workloads
2. **Lazy drift scoring** — 40-60% savings for infrequently-checked agents
3. **Compress audit logs** — 70-80% storage savings
4. **Rate-limit webhooks** — 50-70% webhook cost reduction
5. **Cache warming** — 20% savings on high-frequency agents
6. **Off-peak scheduling** — 10-15% on compute

---

## Efficient Operations

### Batch Kill Processing

Groups kills by tenant and flushes in batches to reduce per-decision overhead:

```python
from brahmanda.efficient_ops import BatchKillProcessor, PendingKill

def handle_batch(kills: List[PendingKill]):
    # Process all kills in a single transaction
    for kill in kills:
        perform_kill(kill)

processor = BatchKillProcessor(
    max_batch_size=50,
    flush_interval_seconds=5.0,
    handler=handle_batch,
)
processor.start()

processor.enqueue(PendingKill(
    tenant_id="acme", agent_id="gpt4", session_id="sess_1",
    rule_id="R1", reason="High drift", severity="high",
))
```

### Lazy Drift Scoring

Drift scores are computed only when requested, with configurable TTL:

```python
from brahmanda.efficient_ops import LazyDriftScorer

scorer = LazyDriftScorer(default_ttl=300)  # 5-minute cache

# First call computes, subsequent calls use cache
result = scorer.get_drift_score("agent_001", compute_fn=my_compute_fn)
# result = (0.35, {"semantic": 0.4, "alignment": 0.3, ...})
```

### Cache Warming

Pre-computes common rule evaluations based on access patterns:

```python
from brahmanda.efficient_ops import CacheWarmer

warmer = CacheWarmer()

# Record accesses to build pattern
warmer.record_access("R1", "agent_001", "ctx_hash")

# Warm cache for top-N accessed rules
warmer.warm(compute_fn=lambda rule, agent, ctx: evaluate_rule(rule, agent, ctx))
```

### Audit Log Compression

gzip compression for audit log storage (typically 70-80% reduction):

```python
from brahmanda.efficient_ops import CompressedAuditLog

log = CompressedAuditLog()
log.append({"event": "kill", "agent": "gpt4", "rule": "R1"}, tenant_id="acme")

# Read back
entries = log.read_all(tenant_id="acme")

# Check compression stats
stats = log.get_compression_stats()
# {"entries": 10000, "raw_bytes": 5000000, "compressed_bytes": 1200000, "compression_ratio": 0.76}
```

---

## Cost Reporting

### Generate Reports

```python
from brahmanda.cost_report import CostReportGenerator

generator = CostReportGenerator(cost_tracker=tracker)

# Daily report
daily = generator.generate_daily_report("acme", "2026-03-26")

# Weekly report
weekly = generator.generate_weekly_report("acme", "2026-03-24")

# Monthly report
monthly = generator.generate_monthly_report("acme", 2026, 3)
```

### Export Formats

```python
# CSV (for billing import)
csv_data = generator.export_csv(report)

# JSON (for API/automation)
json_data = generator.export_json(report)

# Markdown (for documentation/email)
md_data = generator.export_markdown(report)
```

### ROI Calculation

Each report includes ROI analysis:

```
Kill Cost:            $0.0250
Est. Violation Cost:  $5.0000  (100 kills × $0.05/violation)
ROI Ratio:            199.00x
Net Savings:          $4.9750
```

The default estimated violation cost is $0.50 per prevented violation. Override:

```python
generator = CostReportGenerator(
    cost_tracker=tracker,
    violation_cost_micro_cents=100_000_000,  # $1.00 per violation
)
```

---

## Billing Integration

### Stripe

```python
from brahmanda.cost_report import BillingAdapter

adapter = BillingAdapter(platform="stripe")
payload = adapter.generate_stripe_payload(report)

# POST to Stripe API
# requests.post("https://api.stripe.com/v1/invoices", json=payload)
```

### Paddle

```python
adapter = BillingAdapter(platform="paddle")
payload = adapter.generate_paddle_payload(report)

# POST to Paddle API
# requests.post("https://api.paddle.com/transactions", json=payload)
```

---

## Configuration Reference

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `COST_TRACKING_ENABLED` | `false` | Enable cost tracking |
| `QUOTA_ENFORCEMENT_ENABLED` | `false` | Enable quota enforcement |
| `BATCH_PROCESSING_ENABLED` | `false` | Enable batch processing |
| `LAZY_DRIFT_ENABLED` | `false` | Enable lazy drift scoring |
| `CACHE_WARMING_ENABLED` | `false` | Enable cache warming |
| `AUDIT_COMPRESSION_ENABLED` | `false` | Enable audit compression |
| `COST_REPORTING_ENABLED` | `false` | Enable cost reporting |
| `COST_DB_PATH` | `data/cost.db` | Cost tracking database path |
| `QUOTA_DB_PATH` | `data/quotas.db` | Quota database path |
| `AUDIT_LOG_DB_PATH` | `data/audit_compressed.db` | Compressed audit log path |

---

## Testing

All cost optimization modules include comprehensive test suites:

```bash
# Run cost-related tests
python3 -m pytest brahmanda/test_cost*.py -v

# Run all tests (verify no regressions)
python3 -m pytest brahmanda/ -v
```

---

## Backward Compatibility

- All features are **disabled by default**
- No changes to existing APIs or behavior when disabled
- Existing test suites (26 Rust, 685+ Python) unaffected
- Database migrations are additive (CREATE IF NOT EXISTS)
- Existing `__init__.py` exports remain unchanged until explicitly imported

---

## Next Steps

- **Phase 7** — Marketplace (rule sharing, community rulesets)
- **Phase 8** — Advanced ML anomaly detection for cost patterns
- **Phase 9** — Multi-cloud cost comparison and optimization
