# RTA-GUARD — API Reference

> **Version 0.6.1** | Python APIs, Rust APIs, REST Endpoints

---

## Table of Contents

- [Python API — discus](#python-api--discus)
- [Python API — brahmanda](#python-api--brahmanda)
- [Rust API — discus-rs](#rust-api--discus-rs)
- [REST API — Dashboard](#rest-api--dashboard)

---

## Python API — discus

### DiscusGuard

```python
from discus import DiscusGuard, SessionKilledError

guard = DiscusGuard(
    config_path=None,          # Path to rules YAML
    verifier=None,             # BrahmandaVerifier instance
    user_tracker=None,         # UserBehaviorTracker instance
    webhook_manager=None,      # WebhookManager instance
)
```

#### `check_and_forward(user_input, session_id, user_id=None) -> str`

Main entry point. Evaluates input against all rules.

- **Returns:** The input string if safe
- **Raises:** `SessionKilledError` if violation detected

#### `check(user_input, session_id) -> GuardResult`

Non-forwarding check. Returns result without raising.

```python
result = guard.check("some input", session_id="abc")
result.passed        # bool
result.violations    # List[RuleViolation]
result.drift_score   # float
```

### RtaEngine

```python
from discus.rta_engine import RtaEngine

engine = RtaEngine()
results = engine.evaluate(input_text, context={})
# Returns: List[RuleResult]
```

### Models

```python
from discus.models import (
    SessionKilledError,
    ViolationType,     # enum: PII_LEAK, PROMPT_INJECTION, JAILBREAK, ...
    Severity,          # enum: LOW, MEDIUM, HIGH, CRITICAL
    RuleResult,
    GuardResult,
)
```

---

## Python API — brahmanda

### BrahmandaVerifier

```python
from brahmanda import BrahmandaVerifier

verifier = BrahmandaVerifier(db_path=":memory:")

# Add facts
verifier.add_fact(
    claim="The Eiffel Tower is in Paris",
    source="encyclopedia",
    domain="geography"
)

# Verify claims
result = verifier.verify("The Eiffel Tower is in London")
# result.decision → "contradiction"
# result.confidence → 0.95
```

### VerificationPipeline

```python
from brahmanda import VerificationPipeline, create_pipeline

pipeline = create_pipeline(verifier=verifier)
result = pipeline.verify("Paris is the capital of France")
# result.verdict: "supported" | "contradiction" | "unverifiable"
# result.confidence: float
# result.explanation: str
```

### ConfidenceScorer

```python
from brahmanda.confidence import ConfidenceScorer

scorer = ConfidenceScorer()
score = scorer.score(
    claim="...",
    source_confidence=0.9,
    corroborating_sources=3,
    contradiction_count=0,
)
# score.value: float (0-1)
# score.level: ConfidenceLevel
# score.explanation: ConfidenceExplanation
```

### MutationTracker

```python
from brahmanda import MutationTracker

tracker = MutationTracker(db_path=":memory:")
tracker.record_mutation(
    fact_id="fact-001",
    mutation_type="update",
    old_value="...",
    new_value="...",
    actor="admin",
)
history = tracker.get_history(fact_id="fact-001")
```

### ConscienceMonitor

```python
from brahmanda import ConscienceMonitor

monitor = ConscienceMonitor(db_path=":memory:")

monitor.register_agent("agent-001")
monitor.record_interaction(
    agent_id="agent-001",
    confidence=0.85,
    violations=0,
    drift_score=0.1,
)

health = monitor.get_agent_health("agent-001")
# health.status: "healthy" | "degraded" | "unhealthy" | "critical"
```

### TamasDetector

```python
from brahmanda.tamas import TamasDetector, TamasState

detector = TamasDetector(db_path=":memory:")
state = detector.evaluate(
    agent_id="agent-001",
    drift_score=0.6,
    violation_rate=0.4,
    confidence=0.3,
)
# state.current: TamasState (SATTVA | RAJAS | TAMAS | CRITICAL)
```

### EscalationChain

```python
from brahmanda.escalation import EscalationChain, EscalationLevel

chain = EscalationChain()
decision = chain.evaluate(
    drift_score=0.5,
    tamas_level=1,
    temporal_level=2,
    user_risk=0.3,
    violation_rate=0.1,
)
# decision.level: EscalationLevel
# decision.reasons: List[str]
```

### TenantManager

```python
from brahmanda.tenancy import TenantManager

mgr = TenantManager(db_path=":memory:")
ctx = mgr.create_tenant("tenant-001", name="Acme Corp")
# ctx.conscience_db_path, ctx.attribution_db_path, ...
```

### RBACManager

```python
from brahmanda.rbac import RBACManager, Role, Permission

rbac = RBACManager(db_path=":memory:")
rbac.assign_role("user-001", "tenant-001", Role.OPERATOR)
has_perm = rbac.has_permission("user-001", "tenant-001", Permission.VIEW_RULES)
```

### RateLimiter

```python
from brahmanda.rate_limit import RateLimiter, QuotaConfig

limiter = RateLimiter(config=QuotaConfig(requests_per_minute=60, burst=10))
allowed = limiter.check("tenant-001", "user-001")
```

### SLATracker

```python
from brahmanda.sla_monitor import SLATracker

tracker = SLATracker(db_path=":memory:")
tracker.record_request(duration_ms=250, status_code=200)
status = tracker.get_status()
# status.uptime, status.avg_response_time, status.kill_rate, ...
```

### WebhookManager

```python
from brahmanda.webhooks import WebhookManager, WebhookEvent

wh = WebhookManager(db_path=":memory:")
wh.register(
    tenant_id="tenant-001",
    url="https://example.com/hook",
    secret="my-secret",
    events=[WebhookEvent.RULE_VIOLATION, WebhookEvent.DRIFT_ALERT],
)
```

### BackupManager / RestoreManager

```python
from brahmanda.backup import BackupManager
from brahmanda.restore import RestoreManager

bm = BackupManager(storage_path="/backups", encryption_key="key")
result = bm.create_full_backup("/data/rta-guard.db", "/data/config")

rm = RestoreManager(storage_path="/backups", encryption_key="key")
rm.restore_point_in_time("backup-id", "/data/restore", dry_run=False)
```

---

## Rust API — discus-rs

### Python Bindings (PyO3)

```python
import discus_rs

engine = discus_rs.RtaEngine()
result = engine.check("user input text")
# result.passed: bool
# result.violations: list
```

### JavaScript/WASM

```javascript
import init, { RtaEngine } from './pkg/discus_rs.js';

await init();
const engine = new RtaEngine();
const result = engine.check("user input");
console.log(result.passed, result.violations);
```

### C Bindings

```c
#include "discus.h"

DiscusEngine* engine = discus_engine_new();
DiscusResult result = discus_check(engine, "user input", 11);
printf("passed: %d, violations: %d\n", result.passed, result.violation_count);
discus_engine_free(engine);
```

### Go Bindings

```go
import "discus"

engine := discus.NewEngine()
result := engine.Check("user input")
fmt.Printf("passed: %v\n", result.Passed)
```

---

## REST API — Dashboard

Base URL: `http://localhost:8080`

### Health

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |

### Guard

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/check` | Check input against rules |
| GET | `/api/sessions` | List sessions |
| GET | `/api/sessions/{id}` | Get session details |

### Conscience

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/conscience/agents` | List agents |
| GET | `/api/conscience/agents/{id}` | Get agent health |
| GET | `/api/conscience/agents/{id}/anomaly` | Anomaly detection |
| GET | `/api/conscience/sessions/{id}/drift` | Session drift |
| POST | `/api/conscience/tamas/evaluate` | Evaluate Tamas |
| GET | `/api/conscience/tamas/{agent_id}` | Get Tamas state |

### Temporal

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/temporal/{agent_id}` | Get consistency |
| POST | `/api/temporal/{agent_id}/check` | Check consistency |
| POST | `/api/temporal/{agent_id}/add` | Add statement |
| GET | `/api/temporal/{agent_id}/contradictions` | Get contradictions |

### User Monitor

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/users/{user_id}` | User risk profile |
| GET | `/api/users/{user_id}/history` | Anomaly history |
| GET | `/api/users/{user_id}/signals` | Anomaly signals |

### Escalation

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/escalation/evaluate` | Manual evaluation |
| GET | `/api/escalation/{agent_id}` | Agent escalation |
| GET | `/api/escalation/history` | Decision history |
| GET | `/api/escalation/config` | Escalation config |

### Tenants

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/tenants` | Create tenant |
| GET | `/api/tenants` | List tenants |
| GET | `/api/tenants/{id}` | Get tenant |
| DELETE | `/api/tenants/{id}` | Delete tenant |
| GET | `/api/tenants/{id}/health` | Tenant health |

### RBAC

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/rbac/assign` | Assign role |
| POST | `/api/rbac/revoke` | Revoke role |
| GET | `/api/rbac/user/{id}/tenant/{tid}` | User roles |
| GET | `/api/rbac/tenant/{id}` | Tenant assignments |

### Webhooks

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/webhooks` | Register webhook |
| GET | `/api/webhooks` | List webhooks |
| GET | `/api/webhooks/{id}` | Get webhook |
| PUT | `/api/webhooks/{id}` | Update webhook |
| DELETE | `/api/webhooks/{id}` | Delete webhook |
| POST | `/api/webhooks/{id}/test` | Test webhook |

### Reports

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/reports/generate` | Generate compliance report |
| GET | `/api/reports/types` | List report types |

### SLA

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/sla/status` | SLA status |
| GET | `/api/sla/metrics/{name}` | Metric details |
| GET | `/api/sla/breaches` | Breach history |
| GET | `/api/sla/stats` | Aggregate stats |

### SSO

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/sso/login` | SSO login URL |
| POST | `/api/sso/callback` | SSO callback |
| GET | `/api/sso/providers` | List providers |
| POST | `/api/sso/providers` | Add provider |
| DELETE | `/api/sso/providers/{tenant}/{name}` | Remove provider |

### Metrics

| Method | Path | Description |
|--------|------|-------------|
| GET | `/metrics` | Prometheus metrics (if enabled) |

### Authentication

All API endpoints (except `/health` and `/metrics`) require:

```
Authorization: Bearer <token>
X-Tenant-Id: <tenant-id>  # if multi-tenancy enabled
```

### Response Format

```json
{
  "status": "ok",
  "data": { ... },
  "error": null
}
```

Error:

```json
{
  "status": "error",
  "data": null,
  "error": "Description of the error"
}
```
