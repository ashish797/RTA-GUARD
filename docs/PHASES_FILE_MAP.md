# RTA-GUARD — Files by Phase

This document maps all files to their respective development phases. It serves as a quick reference for where functionality lives and what's included in each phase.

---

## Phase 0 — Kill-Switch MVP

**Purpose:** Core Wasm kill-switch, basic interceptor, working demo

| File/Directory | Description |
|---|---|
| `discus/guard.py` | Core DiscusGuard middleware (kill-switch logic) |
| `discus/llm.py` | LLM integration (OpenAI/Anthropic) |
| `discus/models.py` | Data models (Session, Block, Kill) |
| `discus/nemo.py` | NeMo Guardrails integration |
| `dashboard/app.py` | Flask dashboard |
| `dashboard/static/index.html` | Dashboard UI |
| `tests/test_discus.py` | Core kill-switch tests (11/11) |
| `README.md` | Project overview |
| `requirements.txt` | Dependencies (Flask, openai, anthropic, nemo) |

---

## Phase 1 — RTA Rules Engine

**Purpose:** Ṛta-based constitutional rules, priority matrix, scoring

| File/Directory | Description |
|---|---|
| `discus/rta_engine.py` | RtaEngine with 13 rules implementation |
| `discus/rules.py` | Individual rule classes (R1-R13) |
| `docs/RTA-RULESET.md` | Enhanced ruleset v1.0-Veda (Saurabh Sir) |
| `docs/MVP-PHASE1-SPEC.md` | Phase 1 specification |
| `tests/test_rta_engine.py` | RTA rule tests (11/11) |

---

## Phase 2 — Brahmanda Map

**Purpose:** Ground truth database with semantic search, source attribution, audit trail

### Subphase 2.1 — Schema Design
| File | Description |
|---|---|
| `brahmanda/models.py` | GroundTruthFact, Source, ClaimMatch, VerifyResult |

### Subphase 2.2 — Qdrant Vector Integration
| File | Description |
|---|---|
| `brahmanda/qdrant_client.py` | QdrantBrahmanda class with OpenAI embeddings |
| `docs/QDRANT-MIGRATION.md` | Migration guide |
| `brahmanda/test_qdrant_search.py` | Semantic search tests |

### Subphase 2.3 — Truth Verification Pipeline
| File | Description |
|---|---|
| `brahmanda/pipeline.py` | VerificationPipeline with claim extraction & contradiction detection |
| `brahmanda/extractor.py` | Verifiable claim extractor |
| `brahmanda/verifier.py` | Enhanced with multi-fact cross-verification |
| `tests/test_satya_pipeline.py` | Integration tests (11/11) |
| `brahmanda/test_pipeline.py` | Pipeline unit tests (11/11) |

### Subphase 2.4 — Source Attribution System
| File | Description |
|---|---|
| `brahmanda/attribution.py` | SourceRegistry, FactProvenanceTracker, AuditTrail, AttributionManager |
| `brahmanda/models.py` | Expanded: FactProvenance, AuditEntry, SourceAuthority enum |
| `brahmanda/test_attribution.py` | 54 tests covering attribution |

### Subphase 2.5 — Confidence Scoring System
| File | Description |
|---|---|
| `brahmanda/confidence.py` | ConfidenceScorer with source/corroboration/recency/contradiction modes |
| `brahmanda/test_confidence.py` | 44 tests for confidence scoring |

### Subphase 2.6 — Mutation Tracking
| File | Description |
|---|---|
| `brahmanda/mutation.py` | MutationTracker (558 lines, SHA-256 hash chain) |
| `brahmanda/test_mutation.py` | 67 tests for mutation lifecycle |

---

## Phase 3 — Conscience Monitor

**Purpose:** Behavioral profiling, drift escalation, longitudinal analysis

### Subphase 3.1 — Behavioral Profiling
| File | Description |
|---|---|
| `brahmanda/profiles.py` | AgentProfile, SessionProfile, UserProfile with online stats, anomaly detection |
| `brahmanda/conscience.py` | ConscienceMonitor orchestrator, BehavioralBaseline, LiveDriftScorer, SQLite persistence |
| `brahmanda/test_conscience.py` | 57 tests covering profiles, anomaly, drift, persistence, integration |

### Subphase 3.2 — Live An-Rta Drift Scoring
| File | Description |
|---|---|
| `brahmanda/conscience.py` | LiveDriftScorer, DriftSnapshot — continuous drift monitoring with sliding window \& EMA |
| `brahmanda/profiles.py` | DriftLevel, DriftComponents, classify_drift — drift thresholds \& component model |
| `brahmanda/test_drift.py` | 54 tests: session/agent drift, trend, components, thresholds, window, EMA, integration |
| `dashboard/app.py` | `/api/conscience/drift/{agent_id}`, drift session \& components endpoints, drift recording |

---

## Phase 4 — Enterprise Features

**Purpose:** RBAC, compliance reports, SSO

| File/Directory | Description |
|---|---|
| `dashboard/auth.py` | Auth (token-based, will expand to SSO) |
| `dashboard/reports.py` | Compliance report generation (EU AI Act) |
| `tests/test_enterprise.py` | Phase 4 tests |

---

## Phase 5 — Sudarshan Wasm

**Purpose:** WebAssembly runtime for browser/edge deployment

| File/Directory | Description |
|---|---|
| `discus/sudarshan/` | Rust/C → Wasm module |
| `discus/wasm_bindings/` | JS/Wasm glue |
| `tests/test_wasm.py` | Wasm tests |

---

## Phase 6 — Ecosystem & Scale

**Purpose:** Open-source release, plugin architecture, production hardening

| File/Directory | Description |
|---|---|
| `plugins/` | Plugin system |
| `docs/PLUGIN_API.md` | Plugin specification |
| `scripts/deploy/` | Production deployment scripts |
| Tests for 6.1-6.8 | Various integration tests |

---

## Shared / Cross-Phase

| File | Purpose |
|---|---|
| `memory/development_log.md` | Detailed progress log (daily updates) |
| `memory/development_progress.json` | Current state tracker |
| `scripts/daily_report.py` | CEO report generator (cron) |
| `docs/BRAHMANDA-MAP-DRAFT.md` | Architecture overview |
| `docs/PROJECT-PHASES.md` | Full phase breakdown |
| `showcase/` | Demo site |
| `tools/update_mission_control.py` | Mission Control updater |

---

## Notes

- **Brahmanda** package houses all ground truth and verification logic (Phases 2-3)
- **Discus** houses the core kill-switch and rule engine (Phases 0-1)
- **Dashboard** is the UI layer (Phases 0-4)
- Phase boundaries are additive; new files do not typically modify old ones

---

*Last updated: 2026-03-26 (Phase 3.2 complete)*
