# RTA-GUARD — Architecture

> **Version 0.6.1** | System Design, Data Flow, Component Interactions

---

## Table of Contents

- [Overview](#overview)
- [High-Level Architecture](#high-level-architecture)
- [Component Map](#component-map)
- [Data Flow](#data-flow)
- [Rules Engine](#rules-engine)
- [Brahmanda Map](#brahmanda-map)
- [Conscience Monitor](#conscience-monitor)
- [Enterprise Layer](#enterprise-layer)
- [Sudarshan WASM Engine](#sudarshan-wasm-engine)
- [Deployment Architecture](#deployment-architecture)
- [Database Design](#database-design)
- [Security Architecture](#security-architecture)

---

## Overview

RTA-GUARD is a **deterministic AI safety layer** that intercepts AI agent outputs and kills sessions when violations are detected. It is named after the Vedic concept of **Ṛta** (cosmic order).

The system has 6 major subsystems:

```
┌──────────────────────────────────────────────────────────────┐
│                     RTA-GUARD                                │
│                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────┐ │
│  │ Discus      │  │ Brahmanda    │  │ Conscience         │ │
│  │ Guard       │  │ Map          │  │ Monitor            │ │
│  │ (Kill-      │  │ (Ground      │  │ (Behavioral        │ │
│  │  Switch)    │  │  Truth)      │  │  Profiling)        │ │
│  └──────┬──────┘  └──────┬───────┘  └────────┬───────────┘ │
│         │                │                     │             │
│  ┌──────┴────────────────┴─────────────────────┴──────────┐ │
│  │              Enterprise Layer                           │ │
│  │  Tenancy │ RBAC │ SSO │ Rate Limit │ SLA │ Webhooks   │ │
│  └──────────────────────────┬──────────────────────────────┘ │
│                             │                                │
│  ┌──────────────────────────┴──────────────────────────────┐ │
│  │         Sudarshan Engine (Rust/WASM)                     │ │
│  │  Native │ WASM Browser │ WASI │ Python Bindings         │ │
│  └─────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## High-Level Architecture

```
                    ┌─────────────┐
                    │  User/App   │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │  API Layer  │ (FastAPI)
                    │  Dashboard  │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
       ┌──────▼─────┐ ┌───▼────┐ ┌─────▼──────┐
       │ Discus     │ │ Auth   │ │ Rate       │
       │ Guard      │ │ (SSO/  │ │ Limiter    │
       │            │ │ RBAC)  │ │            │
       └──────┬─────┘ └────────┘ └────────────┘
              │
    ┌─────────┼─────────┐
    │         │         │
┌───▼──┐ ┌───▼──┐ ┌───▼──────┐
│Rules │ │Truth │ │Conscience│
│Engine│ │Check │ │Monitor   │
│(R1-  │ │(Brah-│ │(Drift/   │
│ R13) │ │manda)│ │ Tamas)   │
└───┬──┘ └───┬──┘ └────┬─────┘
    │        │          │
    └────────┴──────────┘
              │
       ┌──────▼──────┐
       │  Storage    │
       │ SQLite/Qdrant│
       └─────────────┘
```

---

## Component Map

### Phase 1: RtaEngine (Rules Engine)

| Component | File | Description |
|-----------|------|-------------|
| Rules (R1–R13) | `discus/rules.py` | 13 Vedic-inspired safety rules |
| RtaEngine | `discus/rta_engine.py` | Rule evaluation orchestrator |
| DiscusGuard | `discus/guard.py` | Main kill-switch interceptor |
| Models | `discus/models.py` | Violation types, session state |

### Phase 2: Brahmanda Map (Ground Truth)

| Component | File | Description |
|-----------|------|-------------|
| BrahmandaMap | `brahmanda/verifier.py` | In-memory ground truth DB |
| QdrantBrahmanda | `brahmanda/qdrant_client.py` | Vector-based semantic search |
| VerificationPipeline | `brahmanda/pipeline.py` | Claim → verify → verdict |
| SourceRegistry | `brahmanda/attribution.py` | Source hierarchy, provenance |
| ConfidenceScorer | `brahmanda/confidence.py` | Multi-mode confidence scoring |
| MutationTracker | `brahmanda/mutation.py` | Fact mutation audit trail |

### Phase 3: Conscience Monitor

| Component | File | Description |
|-----------|------|-------------|
| ConscienceMonitor | `brahmanda/conscience.py` | Orchestrator for behavioral monitoring |
| LiveDriftScorer | `brahmanda/conscience.py` | Sliding-window + EMA drift scoring |
| TamasDetector | `brahmanda/tamas.py` | 4-state model (SATTVA→CRITICAL) |
| TemporalChecker | `brahmanda/temporal.py` | Contradiction detection over time |
| UserBehaviorTracker | `brahmanda/user_monitor.py` | 6 anomaly detection categories |
| EscalationChain | `brahmanda/escalation.py` | Weighted multi-signal escalation |

### Phase 4: Enterprise

| Component | File | Description |
|-----------|------|-------------|
| TenantManager | `brahmanda/tenancy.py` | Multi-tenant isolation |
| RBACManager | `brahmanda/rbac.py` | Role-based access control |
| SSOManager | `brahmanda/sso.py` | OIDC/SAML integration |
| RateLimiter | `brahmanda/rate_limit.py` | Token bucket + fixed window |
| SLATracker | `brahmanda/sla_monitor.py` | 6 SLA metrics, breach detection |
| WebhookManager | `brahmanda/webhooks.py` | Event-driven notifications |
| ReportGenerator | `brahmanda/compliance.py` | EU AI Act, SOC2, HIPAA reports |

### Phase 5: Sudarshan (Rust/WASM)

| Component | File | Description |
|-----------|------|-------------|
| Rust engine | `discus-rs/src/rta_engine.rs` | Core rules in Rust |
| WASM build | `discus-rs/build.sh` | Browser + WASI compilation |
| Browser ext | `discus-rs/inject/` | Content script + service worker |
| Python bindings | `discus-rs/bindings/python/` | PyO3 integration |

### Phase 6: Ecosystem

| Component | File | Description |
|-----------|------|-------------|
| Dashboard | `dashboard/app.py` | FastAPI web UI + API |
| Helm chart | `helm/rta-guard/` | Kubernetes deployment |
| Monitoring | `monitoring/` | Prometheus + Grafana |
| Logging | `logging/` | ELK stack config |
| Backup/DR | `brahmanda/backup.py`, `restore.py` | Encrypted backup + point-in-time restore |

---

## Data Flow

### 1. Guard Check Flow

```
User Input
    │
    ▼
DiscusGuard.check_and_forward()
    │
    ├── Rate Limit Check
    │   └── Reject if exceeded
    │
    ├── Rule Evaluation (RtaEngine)
    │   ├── R1-R13 evaluated in priority order
    │   ├── Highest severity violation wins
    │   └── Shadow violations logged
    │
    ├── Ground Truth Check (Brahmanda)
    │   ├── Extract claims from output
    │   ├── Semantic search (Qdrant) or exact match (SQLite)
    │   ├── Cross-verify against known facts
    │   └── Return confidence + verdict
    │
    ├── Conscience Evaluation
    │   ├── Update drift score (sliding window)
    │   ├── Check Tamas state
    │   ├── Temporal consistency check
    │   └── User behavior anomaly scan
    │
    ├── Escalation Chain
    │   ├── Collect signals from all subsystems
    │   ├── Weighted aggregate score
    │   └── Decision: OBSERVE / WARN / THROTTLE / ALERT / KILL
    │
    └── Final Decision
        ├── PASS → Forward to LLM
        ├── WARN → Forward with warning logged
        └── KILL → Terminate session, fire webhooks
```

### 2. Truth Verification Flow

```
Claim
    │
    ▼
VerificationPipeline.verify()
    │
    ├── Extract claims (NLP)
    ├── Search ground truth (Qdrant/SQLite)
    ├── Score confidence
    ├── Detect contradictions (5 heuristics)
    └── Return verdict + explanation
```

### 3. Escalation Flow

```
Signal Sources:
    Drift Score ─────┐
    Tamas State ─────┤
    Temporal Level ──┼──→ EscalationChain.evaluate()
    User Risk ───────┤         │
    Violation Rate ──┘         │
                               ▼
                    Weighted Aggregate Score
                    Multi-signal boost
                               │
                               ▼
                    Decision (OBSERVE → KILL)
                               │
                    ┌──────────┼──────────┐
                    │          │          │
                Handler    Webhook    Session
                Callback   Dispatch   Kill
```

---

## Rules Engine

13 rules organized in priority order. Each rule evaluates independently, producing a `RuleResult` with `passed`, `severity`, and `message`.

**Priority Matrix:**

```
Highest ──────── Lowest
AHIMSA > DHARMA > SATYA > MAYA > ALIGNMENT > VIDYA > ...
```

**Conflict Resolution:** Highest-priority rule wins. Shadow violations (lower priority but also triggered) are logged for audit.

See [RTA-RULESET.md](RTA-RULESET.md) for full rule specifications.

---

## Brahmanda Map

The "cosmic egg" ground truth system:

```
┌─────────────────────────────┐
│       Brahmanda Map         │
│                             │
│  ┌────────┐  ┌───────────┐ │
│  │ SQLite │  │ Qdrant    │ │
│  │ Facts  │  │ Vectors   │ │
│  └───┬────┘  └─────┬─────┘ │
│      │             │       │
│  ┌───┴─────────────┴─────┐ │
│  │   Verifier / Pipeline │ │
│  └───────────┬───────────┘ │
│              │             │
│  ┌───────────▼───────────┐ │
│  │ Source Attribution    │ │
│  │ + Provenance Tracking │ │
│  └───────────┬───────────┘ │
│              │             │
│  ┌───────────▼───────────┐ │
│  │ Confidence Scoring    │ │
│  │ + Mutation Tracking   │ │
│  └───────────────────────┘ │
└─────────────────────────────┘
```

---

## Conscience Monitor

Behavioral profiling system with 4 scoring dimensions:

| Dimension | Weight | Source |
|-----------|--------|--------|
| Drift | 0.25 | LiveDriftScorer (EMA, 5 components) |
| Tamas | 0.25 | TamasDetector (4-state hysteresis) |
| Temporal | 0.15 | TemporalConsistencyChecker (sliding window) |
| User Risk | 0.20 | UserBehaviorTracker (6 categories) |
| Violation Rate | 0.15 | Guard check history |

Escalation chain produces: OBSERVE → WARN → THROTTLE → ALERT → KILL

---

## Enterprise Layer

```
┌────────────────────────────────────────────┐
│            Request                         │
│               │                            │
│    ┌──────────▼──────────┐                 │
│    │ Auth (SSO / Token)  │                 │
│    └──────────┬──────────┘                 │
│               │                            │
│    ┌──────────▼──────────┐                 │
│    │ Tenant Resolution   │                 │
│    └──────────┬──────────┘                 │
│               │                            │
│    ┌──────────▼──────────┐                 │
│    │ RBAC Check          │                 │
│    └──────────┬──────────┘                 │
│               │                            │
│    ┌──────────▼──────────┐                 │
│    │ Rate Limiter        │                 │
│    └──────────┬──────────┘                 │
│               │                            │
│    ┌──────────▼──────────┐                 │
│    │ SLA Middleware      │                 │
│    └──────────┬──────────┘                 │
│               │                            │
│    ┌──────────▼──────────┐                 │
│    │ Guard Handler       │                 │
│    └─────────────────────┘                 │
└────────────────────────────────────────────┘
```

---

## Sudarshan WASM Engine

Rust implementation of the rules engine with multiple targets:

| Target | Binary | Size | Use Case |
|--------|--------|------|----------|
| Native (.so) | `libdiscus_rs.so` | ~2MB | Python bindings via PyO3 |
| WASM Browser | `discus_rs.wasm` | ~1.7MB | Browser extension |
| WASI | `discus_rs.wasm` | ~1.8MB | Standalone WASM runtime |

Fallback: Pure-JS engine when WASM unavailable.

---

## Deployment Architecture

### Small (Development)

```
┌─────────────┐
│  rta-guard  │ ← Single container
│  + SQLite   │
└─────────────┘
```

### Medium (Production)

```
┌──────────────┐     ┌──────────┐
│  rta-guard   │────►│ Postgres │
│  (3 replicas)│     └──────────┘
└──────┬───────┘
       │         ┌──────────┐
       └────────►│ Qdrant   │
                 └──────────┘
```

### Large (Enterprise)

```
┌──────────┐  ┌──────────┐  ┌──────────┐
│ rta-guard│  │ rta-guard│  │ rta-guard│
│ us-east  │  │ us-west  │  │ eu-west  │
└────┬─────┘  └────┬─────┘  └────┬─────┘
     │             │             │
     └──────┬──────┴──────┬──────┘
            │             │
     ┌──────▼──────┐ ┌───▼─────┐
     │  Postgres   │ │  Redis  │
     │  (primary)  │ │  (HA)   │
     └─────────────┘ └─────────┘
```

See [DEPLOYMENT.md](DEPLOYMENT.md), [HA.md](HA.md), and [DEPLOYMENT-PROD.md](DEPLOYMENT-PROD.md) for deployment details.

---

## Database Design

### SQLite Tables (Single-node)

| Table | Purpose |
|-------|---------|
| `facts` | Ground truth facts (Brahmanda) |
| `audit_log` | Append-only hash-chain audit |
| `conscience_agents` | Agent behavioral profiles |
| `conscience_sessions` | Session state |
| `tamas_events` | Tamas state transitions |
| `temporal_statements` | Temporal consistency window |
| `user_profiles` | User behavior profiles |
| `user_signals` | Anomaly signals |
| `mutations` | Fact mutation history |
| `escalation_decisions` | Escalation chain decisions |
| `webhooks` | Webhook configurations |
| `webhook_events` | Webhook delivery log |
| `role_assignments` | RBAC assignments |
| `sla_requests` | SLA request tracking |
| `sla_breaches` | SLA breach records |
| `sso_sessions` | SSO session state |
| `rate_limit_windows` | Rate limit counters |

### Qdrant Collections

| Collection | Vectors | Purpose |
|-----------|---------|---------|
| `ground_truth` | 1536-dim (OpenAI) | Semantic fact search |

---

## Security Architecture

```
┌──────────────────────────────────────┐
│         Security Layers              │
│                                      │
│  ┌────────────────────────────────┐  │
│  │ Transport: TLS 1.3             │  │
│  └────────────────────────────────┘  │
│  ┌────────────────────────────────┐  │
│  │ Auth: SSO (OIDC/SAML) + Token │  │
│  └────────────────────────────────┘  │
│  ┌────────────────────────────────┐  │
│  │ Authorization: RBAC (4 roles)  │  │
│  └────────────────────────────────┘  │
│  ┌────────────────────────────────┐  │
│  │ Isolation: Multi-tenant        │  │
│  └────────────────────────────────┘  │
│  ┌────────────────────────────────┐  │
│  │ Audit: SHA-256 hash chain      │  │
│  └────────────────────────────────┘  │
│  ┌────────────────────────────────┐  │
│  │ Encryption: AES-256-GCM        │  │
│  │ (backups at rest)              │  │
│  └────────────────────────────────┘  │
└──────────────────────────────────────┘
```
