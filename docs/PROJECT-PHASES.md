# RTA-GUARD — Project Phases

## Overview
RTA-GUARD is a constitutional AI governance framework inspired by the Vedic concept of Ṛta (Cosmic Order). It enforces invariant laws on AI agents, detects deviation from truth, and kills sessions that violate the cosmic order.

---

## ✅ PHASE 0 — Kill-Switch MVP (COMPLETE)

**Goal:** Build a working session terminator that detects violations and kills sessions.

**Status:** ✅ Built, tested (11/11 tests passing), committed locally.

| Component | Status | Details |
|-----------|--------|---------|
| DiscusGuard (core engine) | ✅ Done | Pattern-based detection: PII, prompt injection, jailbreak, keywords |
| Rule Engine | ✅ Done | Regex patterns for injection, PII, sensitive keywords |
| Dashboard (FastAPI) | ✅ Done | Real-time event log, stats, test buttons, dark-mode UI |
| Dashboard Auth | ✅ Done | Token-based Bearer auth on all API endpoints |
| LLM Integration | ✅ Done | OpenAI, Anthropic, OpenAI-compatible providers. Input + output protection |
| NeMo Hybrid Detection | ✅ Done | Optional ML layer on top of pattern-based rules |
| Demo Apps | ✅ Done | CLI chat, real LLM chat, hybrid detection showcase |
| Tests | ✅ Done | 11/11 passing |
| Docker | ✅ Done | docker-compose ready |
| Showcase Page | ✅ Done | Published at here.now (24h link) |

**What it is:** A functional security tool. The "Sudarshan Firewall" — the kill mechanism.
**What it isn't:** Not yet the constitutional governance layer. Pattern-based, not principle-based.

---

## 🔄 PHASE 1 — RTA Rules Engine (IN PROGRESS)

**Goal:** Replace pattern-based rules with Vedic principle-based rules. Codify R1-R13 into enforceable code.

**Status:** 📋 Ruleset documented (`docs/RTA-RULESET.md`). Saurabh enhancing with Claude Code. Code not yet written.

| Task | Status | Owner |
|------|--------|-------|
| Research Vedic principles | ✅ Done | RTA_CTO |
| Codify 13 rules (R1-R13) | ✅ Documented | RTA_CTO |
| Enhance with verse references | 🔄 In Progress | Saurabh + Claude Code |
| Implement RtaEngine (Python) | ❌ Not Started | RTA_CTO |
| An-Rta Drift Scoring | ❌ Not Started | — |
| Rule Priority & Conflict Resolution | ❌ Not Started | — |
| Temporal Consistency Check (R7) | ❌ Not Started | — |
| Hallucination Scoring (R12 Maya) | ❌ Not Started | — |
| Health Monitoring (R9 Vayu) | ❌ Not Started | — |

**What this delivers:** The AI's "conscience" — not just catching bad patterns, but enforcing the laws of truth and order.

---

## 📋 PHASE 2 — Brahmanda Map (Ground Truth)

**Goal:** Build the ground truth database that the AI must verify its "thoughts" against before speaking.

**Status:** ❌ Not Started

| Task | Status | Details |
|------|--------|---------|
| Design ground truth schema | ❌ | What constitutes "verified truth"? |
| Knowledge base architecture | ❌ | Vector DB? Graph DB? Hybrid? |
| Truth verification pipeline | ❌ | How outputs get checked against ground truth |
| Source attribution system | ❌ | Every claim traceable to a source |
| Confidence scoring | ❌ | How certain is the AI about each output? |
| Update/mutation tracking | ❌ | How does ground truth evolve over time? |

**What this delivers:** The "Satya" layer — the AI can't just say things, it must verify them against reality.

---

## 📋 PHASE 3 — Conscience Monitor (Behavioral Tracking)

**Goal:** Persistent monitoring of AI behavior over time, not just per-message checks.

**Status:** ❌ Not Started

| Task | Status | Details |
|------|--------|---------|
| Session behavioral profiling | ❌ | Track patterns across multiple interactions |
| An-Rta drift scoring (live) | ❌ | Continuous 0-1 measurement of deviation from order |
| Tamas detection protocol | ❌ | Auto-detect when system enters "darkness" |
| Temporal consistency (R7) | ❌ | Detect contradictions across conversation history |
| User behavior anomaly detection | ❌ | Detect adversarial users, not just adversarial inputs |
| Escalation protocols | ❌ | Auto-throttle → alert human → kill |

**What this delivers:** The persistent "conscience" — watches the AI over time, not just instant-by-instant.

---

## 📋 PHASE 4 — Enterprise Features

**Goal:** Make RTA-GUARD production-ready for enterprise deployment.

**Status:** ❌ Not Started

| Task | Status | Details |
|------|--------|---------|
| Multi-tenant support | ❌ | Multiple orgs, isolated rule sets |
| RBAC (Role-Based Access Control) | ❌ | Who can modify rules? Who can view logs? |
| Compliance reporting | ❌ | EU AI Act, SOC2, HIPAA audit trails |
| Webhook system | ❌ | Notify external systems on violations |
| SSO integration | ❌ | SAML, OIDC for dashboard access |
| Rate limiting & quotas | ❌ | Per-org, per-user limits |
| SLA monitoring | ❌ | Uptime, response time, kill rate metrics |
| API documentation | ❌ | OpenAPI spec, SDKs |

**What this delivers:** A product enterprises can actually buy and deploy.

---

## 📋 PHASE 5 — Sudarshan Wasm Module

**Goal:** Compile the kill-switch into a WebAssembly module that can be injected anywhere.

**Status:** ❌ Not Started (Phase 2 of original roadmap)

| Task | Status | Details |
|------|--------|---------|
| Core engine in Rust/C | ❌ | Rewrite DiscusGuard for Wasm compilation |
| Wasm compilation pipeline | ❌ | Build .wasm artifacts |
| Browser injection | ❌ | Run in browser extensions |
| Server-side injection | ❌ | Run as middleware in any server |
| CLI injection | ❌ | Wrap CLI tools |
| WASI integration | ❌ | System-level capabilities |

**What this delivers:** The embeddable kill-switch — works anywhere, any platform, any language.

---

## 📋 PHASE 6 — Ecosystem & Scale

**Goal:** Build the ecosystem around RTA-GUARD. Community, plugins, integrations.

**Status:** ❌ Not Started

| Task | Status | Details |
|------|--------|---------|
| Open-source core | ❌ | Apache 2.0 license, public repo |
| Plugin system | ❌ | Custom rules, custom validators |
| NeMo/Bedrock/LangChain integrations | ❌ | First-class support for major frameworks |
| Rule marketplace | ❌ | Share and discover rule sets |
| Community rulesets | ❌ | Industry-specific rule packs (healthcare, finance, legal) |
| Documentation site | ❌ | Full docs, tutorials, examples |
| CI/CD integration | ❌ | GitHub Actions, GitLab CI for rule testing |

**What this delivers:** A platform, not just a product. The "Airbrake of AI security."

---

## Timeline (Estimated)

| Phase | Duration | Dependencies |
|-------|----------|-------------|
| Phase 0 ✅ | Done | — |
| Phase 1 🔄 | 2-3 weeks | Saurabh's research → code implementation |
| Phase 2 📋 | 3-4 weeks | Phase 1 complete |
| Phase 3 📋 | 3-4 weeks | Phase 1 + 2 complete |
| Phase 4 📋 | 4-6 weeks | Phase 1-3 complete, pilot customers |
| Phase 5 📋 | 4-6 weeks | Core stable, demand for embeddable module |
| Phase 6 📋 | Ongoing | Community adoption |

---

## Current Focus

**Right now:** Phase 1 — codifying the Vedic rules into Python.
**Next milestone:** RtaEngine v0.1 — the first principle-based AI governance engine.
**Blocking item:** Saurabh's enhanced ruleset from Claude Code.

---

*Last updated: 2026-03-25*
*Document owner: RTA_CTO*
