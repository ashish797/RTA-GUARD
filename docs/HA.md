# RTA-GUARD — High Availability & Multi-Region Guide

**Phase 6.5** | Status: Complete

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                      Global Layer                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ Geo-Router    │  │ Split-Brain  │  │ Failover         │  │
│  │ (region.py)   │  │ Detector     │  │ Orchestrator     │  │
│  └──────┬───────┘  └──────┬───────┘  └────────┬─────────┘  │
│         │                 │                    │             │
│  ┌──────┴─────────────────┴────────────────────┴──────────┐ │
│  │              Leader Election (ha.py)                    │ │
│  └──────────────────────┬──────────────────────────────────┘ │
│                         │                                    │
│  ┌──────────────────────┴──────────────────────────────────┐ │
│  │           Replication Engine (replication.py)            │ │
│  └───┬──────────────┬──────────────┬──────────────┬────────┘ │
│     │              │              │              │           │
│  ┌──┴──┐       ┌──┴──┐       ┌──┴──┐       ┌──┴──┐        │
│  │us-  │       │us-  │       │eu-  │       │ap-  │        │
│  │east │◄─────►│west │◄─────►│west │◄─────►│south│        │
│  │-1   │       │-2   │       │-1   │       │-1   │        │
│  └─────┘       └─────┘       └─────┘       └─────┘        │
└─────────────────────────────────────────────────────────────┘
```

## Key Design Decisions

### 1. HA Is Opt-In
Single-region deployments work exactly as before. Set `ha.enabled: true` in Helm
values to activate multi-region features. All Python modules default to
single-region mode when no multi-region config is provided.

### 2. File-Based Leader Election (Default)
Works without Redis. Writes a lease file with node ID, hostname, PID, and TTL.
For production multi-node, set `leaderElection.redisUrl` to use Redis-based
election with SET NX EX semantics.

### 3. Split-Brain Resolution
Each leader writes heartbeats to a shared directory. If multiple heartbeats
with different node IDs exist and are recent → split-brain detected.
Resolution: highest node_id lexicographically wins, others are demoted.

### 4. Replication Strategy
| Data Type | Strategy | Conflict Resolution |
|-----------|----------|-------------------|
| Session state | Async event-driven | Last-write-wins (highest timestamp) |
| Audit logs | Append-only, guaranteed delivery | Merge by hash, deduplicated |

### 5. Failover Chain
```
Primary (us-east-1) → Secondary (us-west-2) → Tertiary (eu-west-1)
```
Configured by `failoverPriority` in region config. Lower = higher priority.

---

## Region Configuration

### Supported Regions

| Region | Location | Default Latency Budget |
|--------|----------|----------------------|
| us-east-1 | N. Virginia | 100 ms |
| us-west-2 | Oregon | 120 ms |
| eu-west-1 | Ireland | 150 ms |
| ap-south-1 | Mumbai | 150 ms |
| ap-southeast-1 | Singapore | 130 ms |

### Data Residency

EU (eu-west-1) enforces strict data residency by default — no data egress
allowed. Other regions allow telemetry and aggregated metrics to cross
boundaries. Configure via `ha.dataResidency` in Helm values.

### Geo-Routing

Requests are routed to the nearest healthy region using haversine distance
between client coordinates and region centres. If no coordinates are provided,
routing falls back to failover priority order.

---

## Helm Configuration

### Enable HA

```yaml
# values.yaml
ha:
  enabled: true
  regions:
    - name: us-east-1
      endpoint: https://rta-guard-us-east-1.example.com
      primary: true
      failoverPriority: 0
    - name: us-west-2
      endpoint: https://rta-guard-us-west-2.example.com
      primary: false
      failoverPriority: 1

podDisruptionBudget:
  enabled: true
  minAvailable: 2

autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 10
```

### Deploy

```bash
helm install rta-guard ./helm/rta-guard \
  --set ha.enabled=true \
  --set autoscaling.enabled=true \
  --set autoscaling.minReplicas=2 \
  --set podDisruptionBudget.enabled=true
```

---

## Failover Runbooks

### Automatic Failover

1. Health check fails consecutively (default: 3 times)
2. FailoverOrchestrator triggers failover to secondary region
3. Active region switches to secondary
4. Event logged to failover history (disk + in-memory)
5. Registered callbacks notified
6. When primary recovers, auto-failback after configurable delay

### Manual Failover

```python
from brahmanda.failover import FailoverOrchestrator, FailoverConfig

orch = FailoverOrchestrator(FailoverConfig(
    primary_region="us-east-1",
    secondary_region="us-west-2",
))
event = orch.manual_failover(reason="planned maintenance")
print(event.to_dict())
```

### Manual Failback

```python
event = orch.manual_failback(reason="primary recovered")
```

### Check Failover Status

```python
status = orch.get_status()
# {"state": "secondary_active", "active_region": "us-west-2", ...}
history = orch.get_history(limit=10)
```

---

## Graceful Shutdown

On SIGTERM/SIGINT:
1. Drain active connections (registered callbacks run)
2. Finalize pending kills (finalizer callbacks run)
3. Release leadership lease
4. Exit cleanly

```python
from brahmanda.ha import GracefulShutdown

gs = GracefulShutdown(drain_timeout=30.0)
gs.register_drain_callback(my_drain_fn)
gs.register_finalizer(my_finalize_fn)
gs.install_signal_handlers()
# ... run server ...
gs.shutdown(reason="SIGTERM")
gs.wait()
```

---

## Health Check Aggregation

Combines multiple subcomponent checks into a single status. Worst status wins.

```python
from brahmanda.ha import HealthAggregator, HealthCheck, ComponentStatus

agg = HealthAggregator(node_id="node-1")
agg.register_check("database", lambda: HealthCheck(
    name="database", status=ComponentStatus.HEALTHY.value))
agg.register_check("redis", lambda: HealthCheck(
    name="redis", status=ComponentStatus.HEALTHY.value))

result = agg.check_all()
# result.overall_status == "healthy"
```

---

## Replication Lag Monitoring

```python
from brahmanda.replication import Replicator

repl = Replicator(source_region="us-east-1")
repl.register_transport("eu-west-1", my_send_fn)
repl.start()

lags = repl.get_lag()
# [ReplicationLag(source="us-east-1", target="eu-west-1", lag_seconds=0.5, ...)]
```

---

## API Reference

### brahmanda.region
- `Region` — Enum of 5 supported regions
- `RegionConfig` — Per-region configuration dataclass
- `RegionRouter` — Routes requests to nearest healthy region
- `nearest_region(lat, lon)` — Find closest region by coordinates
- `estimate_latency_ms(lat, lon, region)` — Rough latency estimate

### brahmanda.ha
- `LeaderElection` — File-based or Redis-based leader election
- `SplitBrainDetector` — Detect and resolve multiple leaders
- `GracefulShutdown` — Drain + finalize + exit cleanly
- `HealthAggregator` — Combine subcomponent health into single status

### brahmanda.replication
- `Replicator` — Async event-driven data replication
- `ConflictResolver` — LWW for sessions, merge for audit
- `ReplicationLag` — Lag monitoring between regions

### brahmanda.failover
- `FailoverOrchestrator` — Automatic + manual failover
- `FailoverConfig` — Configuration for failover behaviour
- `FailoverEvent` — Recorded failover/failback event
