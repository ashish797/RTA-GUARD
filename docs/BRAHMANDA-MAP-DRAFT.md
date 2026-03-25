# RTA-GUARD — Brahmanda Map (Phase 2)
## Ground Truth Database Architecture

*"The AI must verify its thoughts against verified reality before speaking."*

---

## 1. Overview

The Brahmanda Map is RTA-GUARD's ground truth database. It stores verified facts with source attribution, enabling RtaEngine's **Satya rule (R1)** to verify AI outputs against established reality before returning them to users.

**Core principle:** Every factual claim in an AI output must be traceable to a verified source. If it can't be verified, it must be flagged.

---

## 2. Architecture Components

```
┌─────────────────────────────────────────────────┐
│                  RTA-GUARD Stack                │
│                                                 │
│  User Input → DiscusGuard → RtaEngine → AI Model│
│                                    ↓            │
│  AI Output ← DiscusGuard ← SatyaRule ← Output   │
│                    ↓                            │
│            Brahmanda Map Query                  │
│                    ↓                            │
│  ┌──────────────────────────────────────┐       │
│  │        Brahmanda Map Core            │       │
│  │                                      │       │
│  │  ┌──────────┐  ┌──────────────────┐  │       │
│  │  │ Vector   │  │ Ground Truth     │  │       │
│  │  │ Store    │  │ Facts Store      │  │       │
│  │  │ (embed-  │  │ (exact-match     │  │       │
│  │  │  ings)   │  │  lookup)         │  │       │
│  │  └──────────┘  └──────────────────┘  │       │
│  │                                      │       │
│  │  ┌──────────────────────────────────┐│       │
│  │  │ Verification Pipeline            ││       │
│  │  │  - Claim extraction              ││       │
│  │  │  - Matching engine               ││       │
│  │  │  - Confidence scoring            ││       │
│  │  │  - Conflict resolution           ││       │
│  │  └──────────────────────────────────┘│       │
│  │                                      │       │
│  │  ┌──────────────────────────────────┐│       │
│  │  │ Source Attribution & Audit        ││       │
│  │  │  - Source registry               ││       │
│  │  │  - Fact provenance chains        ││       │
│  │  │  - Mutation/version history      ││       │
│  │  └──────────────────────────────────┘│       │
│  └──────────────────────────────────────┘       │
└─────────────────────────────────────────────────┘
```

---

## 3. Technology Stack

### Storage Layer (Hybrid Approach)

| Component | Technology | Why |
|---|---|---|
| **Embeddings Store** | Qdrant (self-hosted) | Fastest for cosine similarity, easy to self-host, Python-native client |
| **Facts Store** | SQLite (MVP) → PostgreSQL (production) | Simple for MVP, ACID for fact integrity, JSONB for flexible schemas |
| **Audit Log** | SQLite WAL mode | Append-only, corruption-resistant, lightweight |
| **Embeddings** | OpenAI `text-embedding-3-small` | Cheap, fast, good quality for fact matching |

**Rationale:** We don't need a heavy graph DB for MVP. A vector store for semantic search + a relational store for exact lookups gives us the best of both worlds. Neo4j can be added later for relationship-heavy domains.

### Verification Pipeline

| Stage | Technology | Purpose |
|---|---|---|
| Claim extraction | Rule-based (NLP) | Pull verifiable claims from AI output |
| Semantic search | Qdrant | Find closest known facts |
| Exact matching | PostgreSQL/SQLite | Known entity lookup |
| Confidence scoring | Custom Python | Aggregate confidence based on source authority + match quality |
| Conflict resolution | Priority-weighted | Newer sources > older, primary > secondary |

---

## 4. Data Model

### Ground Truth Fact

```sql
CREATE TABLE facts (
    id              TEXT PRIMARY KEY,  -- UUID
    domain          TEXT NOT NULL,     -- "general", "medical", "legal", "financial"
    claim           TEXT NOT NULL,     -- The verified statement (e.g., "Paris is the capital of France")
    normalized      TEXT NOT NULL,     -- Lowercased, trimmed claim for dedup
    fact_type       TEXT NOT NULL,     -- "entity", "relationship", "metric", "definition"
    confidence      REAL DEFAULT 0.9,  -- 0.0-1.0, based on source authority
    source_id       TEXT NOT NULL,     -- FK to sources table
    source_url      TEXT,              -- Direct URL if available
    verified_at     TEXT NOT NULL,     -- ISO timestamp of verification
    expires_at      TEXT,              -- Optional expiry (e.g., stats that change)
    domain_tags     TEXT,              -- JSON array of tags
    embedding       BLOB,              -- Pre-computed embedding vector
    version         INTEGER DEFAULT 1, -- For mutation tracking
    superseded_by   TEXT,              -- If updated, points to new fact ID
    metadata        TEXT               -- JSON blob for arbitrary data
);
```

### Source Registry

```sql
CREATE TABLE sources (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,     -- e.g., "Wikipedia", "WHO", "Internal Doc"
    authority       TEXT NOT NULL,     -- "primary", "secondary", "tertiary"
    authority_score REAL DEFAULT 0.5,  -- 0.0-1.0
    url             TEXT,
    verified_by     TEXT,              -- Who verified this source
    verified_at     TEXT,
    notes           TEXT
);
```

### Audit Log

```sql
CREATE TABLE audit_log (
    id              TEXT PRIMARY KEY,
    fact_id         TEXT NOT NULL,
    action          TEXT NOT NULL,     -- "create", "update", "retract", "query", "verify"
    old_value       TEXT,              -- JSON before change
    new_value       TEXT,              -- JSON after change
    performed_by    TEXT,              -- User/system that performed action
    performed_at    TEXT NOT NULL,
    reason          TEXT               -- Why the change
);
```

### Vector Store (Qdrant Collection)

```json
{
  "collection_name": "brahmanda_facts",
  "vector_config": {
    "size": 1536,
    "distance": "Cosine"
  },
  "payload_schema": {
    "domain": "keyword",
    "claim": "keyword",
    "fact_id": "keyword",
    "confidence": "float",
    "source_id": "keyword"
  }
}
```

---

## 5. API Specification

### Core Endpoints

#### `POST /api/v1/facts` — Add a Ground Truth Fact
```json
Request:
{
  "claim": "Paris is the capital of France",
  "domain": "general",
  "fact_type": "entity",
  "source_id": "src-wiki-paris",
  "source_url": "https://en.wikipedia.org/wiki/Paris",
  "confidence": 0.95,
  "metadata": {}
}

Response:
{
  "fact_id": "f-001",
  "claim": "Paris is the capital of France",
  "confidence": 0.95,
  "embedding_id": "vec-xyz",
  "created_at": "2026-03-26T00:55:00Z"
}
```

#### `POST /api/v1/verify` — Verify AI Output Against Ground Truth
```json
Request:
{
  "text": "The capital of France is Berlin.",
  "domain": "general",
  "threshold": 0.85
}

Response:
{
  "verified": false,
  "overall_confidence": 0.12,
  "claims": [
    {
      "claim": "The capital of France is Berlin",
      "matched_fact": {
        "claim": "Paris is the capital of France",
        "confidence": 0.95,
        "source": "Wikipedia",
        "similarity": 0.89
      },
      "contradicted": true,
      "reason": "Claim contradicts verified ground truth"
    }
  ],
  "decision": "block",  // "pass", "warn", "block"
  "details": "Contradicts verified fact: Paris is the capital of France"
}
```

#### `GET /api/v1/facts/{fact_id}` — Get Fact Details
```json
Response:
{
  "fact_id": "f-001",
  "claim": "Paris is the capital of France",
  "domain": "general",
  "confidence": 0.95,
  "source": {
    "id": "src-wiki-paris",
    "name": "Wikipedia",
    "authority": "secondary",
    "url": "https://en.wikipedia.org/wiki/Paris"
  },
  "verified_at": "2026-03-26T00:55:00Z",
  "version": 1,
  "audit_trail": [...]
}
```

#### `PUT /api/v1/facts/{fact_id}` — Update a Fact
```json
Request:
{
  "claim": "The Eiffel Tower is in Paris",
  "confidence": 0.98,
  "reason": "Updating claim for clarity"
}

Response:
{
  "fact_id": "f-001",
  "version": 2,
  "previous_version": 1,
  "updated_at": "2026-03-26T01:00:00Z"
}
```

#### `POST /api/v1/extract-claims` — Extract Verifiable Claims from AI Output
```json
Request:
{
  "text": "Paris is the capital of France. The population is 2.1 million. It was founded in the 3rd century BC."
}

Response:
{
  "claims": [
    {"text": "Paris is the capital of France", "type": "entity", "extractable": true},
    {"text": "The population is 2.1 million", "type": "metric", "extractable": true},
    {"text": "It was founded in the 3rd century BC", "type": "historical", "extractable": true}
  ],
  "total_claims": 3,
  "verifiable": 3
}
```

#### `POST /api/v1/import` — Bulk Import Facts
```json
Request:
{
  "facts": [
    {"claim": "...", "domain": "...", "source_id": "..."},
    ...
  ],
  "batch_size": 100
}

Response:
{
  "imported": 100,
  "skipped": 3,
  "errors": 0
}
```

---

## 6. Verification Pipeline

### How It Works

```
AI Output Text
     ↓
[1] Claim Extraction
     ↓ (extracted claims)
[2] For each claim:
     ↓
[3a] Exact Match Lookup ──→ If exact match found → return result
     ↓ (no exact match)
[3b] Semantic Search (Qdrant)
     ↓ (top-k similar facts)
[4] Similarity Scoring
     ↓ (similarity >= threshold?)
[5] Contradiction Check
     ↓ (does claim contradict matched fact?)
[6] Confidence Aggregation
     ↓
[7] Final Verdict (pass/warn/block)
```

### Scoring Algorithm

```python
def verify_claim(claim: str, matched_fact: Fact, similarity: float) -> VerifyResult:
    # 1. Check if the claim contradicts the fact
    if contradictions_detected(claim, matched_fact.claim):
        return VerifyResult(
            verified=False,
            confidence=matched_fact.confidence * similarity,
            decision="block",
            reason="Contradicts verified ground truth"
        )

    # 2. Calculate verification confidence
    # confidence = fact_confidence * similarity
    # e.g., fact_confidence=0.9, similarity=0.85 → final=0.765
    verification_confidence = matched_fact.confidence * similarity

    # 3. Decision based on confidence threshold
    if verification_confidence >= 0.7:
        decision = "pass"
    elif verification_confidence >= 0.5:
        decision = "warn"
    else:
        decision = "block"

    return VerifyResult(
        verified=True,
        confidence=verification_confidence,
        decision=decision,
        matched_fact=matched_fact
    )
```

### Conflict Resolution (When Multiple Sources Disagree)

Priority order:
1. **Primary sources** (original documents, official records) > secondary > tertiary
2. **Newer** > older (if same authority level)
3. **Higher confidence** > lower confidence
4. **Multiple corroborating sources** boost confidence by 0.1 per additional source

---

## 7. Confidence Scoring

### Source Authority Levels

| Level | Score | Examples |
|---|---|---|
| **Primary** | 0.9-1.0 | Official records, peer-reviewed papers, direct observation |
| **Secondary** | 0.6-0.9 | Wikipedia, textbooks, encyclopedias |
| **Tertiary** | 0.3-0.6 | Blog posts, social media, unverified sources |
| **Uncertain** | 0.1-0.3 | Rumor, speculation, unverified claims |

### Fact Confidence Calculation

```
fact_confidence = source_authority_score * recency_factor * corroboration_bonus

where:
  recency_factor = 1.0 if < 1 year old, else decays by 0.05 per year
  corroboration_bonus = 0.1 per additional confirming source (max +0.3)
```

### Decay Over Time

```python
def calculate_recency_factor(verified_at: datetime) -> float:
    age_years = (datetime.now() - verified_at).days / 365.25
    return max(0.5, 1.0 - (age_years * 0.05))
```

---

## 8. Mutation Tracking & Versioning

### How Facts Change

- **CREATE**: New fact added, version 1
- **UPDATE**: Creates new version, old version marked `superseded_by`
- **RETRACT**: Fact marked as retracted (confidence → 0.0), audit log entry
- **NO DELETE**: Facts are never physically deleted, only soft-deleted via retraction

### Version Chain

```
f-001 v1 (original) → f-001 v2 (update) → f-001 v3 (correction)
```

### Audit Trail Example

```json
{
  "fact_id": "f-001",
  "history": [
    {"version": 1, "claim": "Paris is the capital", "at": "2026-03-01", "by": "system"},
    {"version": 2, "claim": "Paris is the capital of France", "at": "2026-03-15", "by": "admin", "reason": "Added specificity"}
  ]
}
```

---

## 9. Implementation Plan

### Phase 2.1: MVP (Weeks 1-2)
- [ ] SQLite facts store + basic schema
- [ ] Embedding generation (OpenAI `text-embedding-3-small`)
- [ ] Qdrant setup (local Docker)
- [ ] Basic `/verify` endpoint
- [ ] Claim extraction (simple rule-based)
- [ ] Integration with SatyaRule in RtaEngine

### Phase 2.2: Source Attribution (Week 3)
- [ ] Source registry with authority scoring
- [ ] Fact provenance chains
- [ ] Confidence decay over time

### Phase 2.3: Verification Pipeline (Week 3-4)
- [ ] Contradiction detection (NLP)
- [ ] Semantic similarity matching
- [ ] Conflict resolution for disagreeing sources
- [ ] Confidence aggregation algorithm

### Phase 2.4: Bulk Import (Week 4)
- [ ] CSV/JSON import endpoints
- [ ] Wikipedia seed dataset
- [ ] Domain-specific fact packs (medical, legal)

### Phase 2.5: Mutation Tracking (Week 5)
- [ ] Fact versioning system
- [ ] Retraction handling
- [ ] Audit log with full history
- [ ] Export/backup capabilities

### Phase 2.6: Production Hardening (Week 5-6)
- [ ] PostgreSQL migration (from SQLite)
- [ ] Redis caching for hot facts
- [ ] Rate limiting
- [ ] Monitoring & alerting
- [ ] Performance optimization (index tuning)

---

## 10. Edge Cases & Failure Modes

| Scenario | Handling |
|---|---|
| **No matching fact found** | Pass with warning (AI may be speculating) |
| **Multiple contradicting sources** | Return all with confidence-weighted verdict |
| **Outdated fact** | Decay confidence, warn if > 2 years old |
| **Embedding API down** | Fall back to exact-match only |
| **Fact deleted/retracted** | Audit trail shows retraction, not blank |
| **Conflicting domain facts** | Isolate by domain (medical facts don't contradict general facts) |
| **Adversarial claim injection** | Source authority scoring prevents low-quality facts from reaching production |

---

## 11. Seed Datasets (MVP)

| Dataset | Source | Facts | Domain |
|---|---|---|---|
| **Wikipedia Entities** | DBpedia/Wikidata dump | ~500K | General |
| **Country Capitals** | Rest Countries API | ~250 | General |
| **Scientific Constants** | NIST reference | ~50 | Science |
| **Medical Facts** | WHO/CDC public data | ~10K | Medical |

For MVP, we'll start with Wikipedia entities and country capitals to demonstrate the concept.

---

## 12. Integration with RtaEngine

```python
class SatyaRule(RtaRule):
    def __init__(self, brahmanda_client: BrahmandaMapClient):
        self.brahmanda = brahmanda_client

    def check(self, context: RtaContext) -> RuleResult:
        if context.role != "assistant" or not context.output_text:
            return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})

        # Verify output against Brahmanda Map
        result = self.brahmanda.verify(context.output_text)

        if result.decision == "block":
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.KILL,
                Severity.CRITICAL,
                f"Satya violation: {result.details}",
                {"confidence": result.confidence, "matched_facts": result.matches}
            )
        elif result.decision == "warn":
            return RuleResult(
                self.rule_id,
                True,
                KillDecision.WARN,
                Severity.HIGH,
                f"Satya warning: unverifiable claims detected",
                {"confidence": result.confidence}
            )

        return RuleResult(self.rule_id, False, KillDecision.PASS, Severity.LOW, "", {})
```

---

## Summary

The Brahmanda Map is the ground truth backbone of RTA-GUARD. By storing verified facts with source attribution and confidence scoring, it enables RtaEngine's Satya rule to detect hallucinations before they reach users. The hybrid approach (vector + relational) gives us both semantic matching and exact lookup, while the audit trail ensures EU AI Act compliance.

**Status:** Architecture drafted, ready for Phase 2.1 implementation.
**Next:** Wire up Qdrant + SQLite, seed with Wikipedia entities, integrate with SatyaRule.

---

*"The AI must verify its thoughts against verified reality before speaking."*
