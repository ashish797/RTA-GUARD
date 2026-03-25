"""
RTA-GUARD — Qdrant Vector Integration for Brahmanda Map

Semantic search backend using Qdrant + OpenAI embeddings.
Same interface as BrahmandaMap (in-memory) so BrahmandaVerifier works unchanged.
"""
import os
import time
import uuid
import logging
from typing import List, Optional, Dict, Any

from .models import (
    GroundTruthFact, Source, SourceAuthority, FactType,
    ClaimMatch, VerifyResult, VerifyDecision
)

logger = logging.getLogger(__name__)

# ─── Lazy imports (optional dependencies) ───────────────────────────

def _get_qdrant():
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance, VectorParams, PointStruct, Filter, FieldCondition,
        MatchValue, MatchAny, PayloadSchemaType,
    )
    return QdrantClient, Distance, VectorParams, PointStruct, Filter, FieldCondition, MatchValue, MatchAny, PayloadSchemaType


def _get_openai():
    from openai import OpenAI
    return OpenAI


# ─── Constants ──────────────────────────────────────────────────────

COLLECTION_NAME = "brahmanda_facts"
VECTOR_SIZE = 1536  # text-embedding-3-small
DEFAULT_MODEL = "text-embedding-3-small"
MAX_RETRIES = 3
RETRY_BACKOFF = 1.5  # seconds, multiplied each retry


# ─── Embedding helper with retry ───────────────────────────────────

class EmbeddingClient:
    """Thin wrapper around OpenAI embedding API with retry logic."""

    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL):
        OpenAI = _get_openai()
        self.client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
        self.model = model

    def embed(self, text: str) -> List[float]:
        """Get embedding for a single text with retry on rate limits."""
        last_err = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = self.client.embeddings.create(input=[text], model=self.model)
                return resp.data[0].embedding
            except Exception as e:
                last_err = e
                if "rate" in str(e).lower() or "429" in str(e):
                    wait = RETRY_BACKOFF * (attempt + 1)
                    logger.warning(f"Embedding rate limited, retry {attempt+1}/{MAX_RETRIES} in {wait}s")
                    time.sleep(wait)
                else:
                    raise
        raise RuntimeError(f"Embedding failed after {MAX_RETRIES} retries: {last_err}")

    def embed_batch(self, texts: List[str], batch_size: int = 100) -> List[List[float]]:
        """Embed multiple texts in batches."""
        all_embeddings = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            last_err = None
            for attempt in range(MAX_RETRIES):
                try:
                    resp = self.client.embeddings.create(input=batch, model=self.model)
                    all_embeddings.extend(e.embedding for e in resp.data)
                    break
                except Exception as e:
                    last_err = e
                    if "rate" in str(e).lower() or "429" in str(e):
                        wait = RETRY_BACKOFF * (attempt + 1)
                        logger.warning(f"Batch embed rate limited, retry {attempt+1}/{MAX_RETRIES} in {wait}s")
                        time.sleep(wait)
                    else:
                        raise
            else:
                raise RuntimeError(f"Batch embedding failed after {MAX_RETRIES} retries: {last_err}")
        return all_embeddings


# ─── QdrantBrahmanda ────────────────────────────────────────────────

class QdrantBrahmanda:
    """
    Qdrant-backed Brahmanda Map with semantic vector search.

    Same public interface as BrahmandaMap (in-memory) so BrahmandaVerifier
    works unchanged via dependency injection.

    Payload fields stored per point:
        claim, normalized, domain, fact_type, confidence,
        source_id, source_name, source_authority, source_url,
        tags, verified_at, version, metadata_json

    Environment variables:
        QDRANT_URL    — e.g. http://localhost:6333 (required)
        QDRANT_API_KEY — optional, for Qdrant Cloud
        OPENAI_API_KEY — required for embedding generation
    """

    def __init__(
        self,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        collection_name: str = COLLECTION_NAME,
        embedding_api_key: Optional[str] = None,
        embedding_model: str = DEFAULT_MODEL,
    ):
        (
            QdrantClient, Distance, VectorParams, PointStruct,
            Filter, FieldCondition, MatchValue, MatchAny, PayloadSchemaType,
        ) = _get_qdrant()

        self._url = url or os.getenv("QDRANT_URL", "http://localhost:6333")
        self._api_key = api_key or os.getenv("QDRANT_API_KEY")
        self._collection = collection_name
        self._Distance = Distance
        self._PointStruct = PointStruct
        self._Filter = Filter
        self._FieldCondition = FieldCondition
        self._MatchValue = MatchValue
        self._MatchAny = MatchAny

        # Connect
        self._client = QdrantClient(url=self._url, api_key=self._api_key, timeout=30)
        logger.info(f"QdrantBrahmanda connected to {self._url}")

        # Embedding client
        self._embedder = EmbeddingClient(
            api_key=embedding_api_key,
            model=embedding_model,
        )

        # Ensure collection exists
        self._ensure_collection(VectorParams, Distance)

        # In-memory index of facts by ID (for fast .get_fact())
        self._facts_cache: Dict[str, GroundTruthFact] = {}
        self._fact_count = 0
        self._sync_cache_from_qdrant()

    # ── Collection management ───────────────────────────────────────

    def _ensure_collection(self, VectorParams, Distance):
        """Create collection if it doesn't exist, with payload indexes."""
        collections = [c.name for c in self._client.get_collections().collections]
        if self._collection not in collections:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
            )
            logger.info(f"Created Qdrant collection '{self._collection}'")
            # Create payload indexes for filtering
            for field, schema in [
                ("domain", PayloadSchemaType.KEYWORD),
                ("fact_type", PayloadSchemaType.KEYWORD),
                ("tags", PayloadSchemaType.KEYWORD),
            ]:
                try:
                    self._client.create_payload_index(
                        collection_name=self._collection,
                        field_name=field,
                        field_schema=schema,
                    )
                except Exception:
                    pass  # Index may already exist
        else:
            logger.info(f"Qdrant collection '{self._collection}' exists")

    def _sync_cache_from_qdrant(self):
        """Load all facts from Qdrant into local cache."""
        try:
            offset = None
            while True:
                points, offset = self._client.scroll(
                    collection_name=self._collection,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for pt in points:
                    fact = self._payload_to_fact(pt.payload)
                    self._facts_cache[fact.id] = fact
                if offset is None:
                    break
            self._fact_count = len(self._facts_cache)
            logger.info(f"Synced {self._fact_count} facts from Qdrant into cache")
        except Exception as e:
            logger.warning(f"Cache sync failed (Qdrant may be empty): {e}")

    # ── Conversion helpers ──────────────────────────────────────────

    @staticmethod
    def _fact_to_payload(fact: GroundTruthFact) -> dict:
        """Convert GroundTruthFact to Qdrant payload."""
        return {
            "claim": fact.claim,
            "normalized": fact.normalized,
            "domain": fact.domain,
            "fact_type": fact.fact_type.value,
            "confidence": fact.confidence,
            "source_id": fact.source.id,
            "source_name": fact.source.name,
            "source_authority": fact.source.authority.value,
            "source_url": fact.source_url or "",
            "tags": fact.tags,
            "verified_at": fact.verified_at,
            "version": fact.version,
            "metadata_json": str(fact.metadata),  # simple serialization
        }

    @staticmethod
    def _payload_to_fact(payload: dict) -> GroundTruthFact:
        """Reconstruct GroundTruthFact from Qdrant payload."""
        source = Source(
            id=payload.get("source_id", ""),
            name=payload.get("source_name", ""),
            authority=SourceAuthority(payload.get("source_authority", "secondary")),
        )
        return GroundTruthFact(
            id=payload.get("id", f"f-{uuid.uuid4().hex[:8]}"),
            claim=payload["claim"],
            normalized=payload.get("normalized", payload["claim"].lower().strip()),
            domain=payload.get("domain", "general"),
            fact_type=FactType(payload.get("fact_type", "entity")),
            confidence=payload.get("confidence", 0.9),
            source=source,
            source_url=payload.get("source_url") or None,
            verified_at=payload.get("verified_at", ""),
            tags=payload.get("tags", []),
            version=payload.get("version", 1),
        )

    # ── Fact Management (same interface as BrahmandaMap) ────────────

    def add_fact(
        self,
        claim: str,
        domain: str = "general",
        fact_type: FactType = FactType.ENTITY,
        confidence: float = 0.9,
        source: Optional[Source] = None,
        source_url: Optional[str] = None,
        tags: Optional[List[str]] = None,
        metadata: Optional[dict] = None,
    ) -> GroundTruthFact:
        """Add a verified fact to Qdrant with embedding."""
        if source is None:
            source = Source(
                name="RTA-GUARD Default",
                authority=SourceAuthority.SECONDARY,
                authority_score=0.7,
            )

        fact = GroundTruthFact(
            claim=claim,
            domain=domain,
            fact_type=fact_type,
            confidence=confidence,
            source=source,
            source_url=source_url,
            tags=tags or [],
            metadata=metadata or {},
        )

        # Generate embedding
        embedding = self._embedder.embed(claim)

        # Upsert to Qdrant
        payload = self._fact_to_payload(fact)
        payload["id"] = fact.id  # Store ID in payload for reconstruction

        self._client.upsert(
            collection_name=self._collection,
            points=[
                self._PointStruct(
                    id=fact.id,
                    vector=embedding,
                    payload=payload,
                )
            ],
        )

        # Update cache
        self._facts_cache[fact.id] = fact
        self._fact_count = len(self._facts_cache)

        logger.info(f"Added fact {fact.id}: {claim[:60]}...")
        return fact

    def get_fact(self, fact_id: str) -> Optional[GroundTruthFact]:
        """Get a fact by ID (from cache)."""
        return self._facts_cache.get(fact_id)

    def find_by_normalized(self, normalized: str) -> Optional[GroundTruthFact]:
        """Find a fact by normalized claim text using Qdrant filter."""
        try:
            results = self._client.scroll(
                collection_name=self._collection,
                scroll_filter=self._Filter(
                    must=[
                        self._FieldCondition(
                            key="normalized",
                            match=self._MatchValue(value=normalized),
                        )
                    ]
                ),
                limit=1,
                with_payload=True,
            )
            points = results[0]
            if points:
                return self._payload_to_fact(points[0].payload)
        except Exception as e:
            logger.warning(f"find_by_normalized failed: {e}")
        return None

    def search(
        self,
        query: str,
        domain: Optional[str] = None,
        limit: int = 5,
    ) -> List[GroundTruthFact]:
        """
        Semantic search using vector similarity.

        If domain is provided, filters results to that domain.
        """
        # Generate query embedding
        query_embedding = self._embedder.embed(query)

        # Build filter
        query_filter = None
        if domain:
            query_filter = self._Filter(
                must=[
                    self._FieldCondition(
                        key="domain",
                        match=self._MatchValue(value=domain),
                    )
                ]
            )

        # Search
        results = self._client.search(
            collection_name=self._collection,
            query_vector=query_embedding,
            limit=limit,
            query_filter=query_filter,
            with_payload=True,
        )

        # Convert to facts
        facts = []
        for hit in results:
            fact = self._payload_to_fact(hit.payload)
            # Store similarity score in metadata for inspection
            fact.metadata["_similarity_score"] = hit.score
            facts.append(fact)

        return facts

    def update_fact(self, fact_id: str, **kwargs) -> Optional[GroundTruthFact]:
        """Update an existing fact (creates new version, retracts old)."""
        old_fact = self._facts_cache.get(fact_id)
        if not old_fact:
            return None

        # Build new version
        new_claim = kwargs.get("claim", old_fact.claim)
        new_fact = GroundTruthFact(
            claim=new_claim,
            normalized=new_claim.lower().strip(),
            domain=kwargs.get("domain", old_fact.domain),
            fact_type=kwargs.get("fact_type", old_fact.fact_type),
            confidence=kwargs.get("confidence", old_fact.confidence),
            source=kwargs.get("source", old_fact.source),
            source_url=kwargs.get("source_url", old_fact.source_url),
            tags=kwargs.get("tags", old_fact.tags),
            metadata=kwargs.get("metadata", old_fact.metadata),
            version=old_fact.version + 1,
        )

        # Mark old version as superseded
        old_fact.superseded_by = new_fact.id
        old_payload = self._fact_to_payload(old_fact)
        old_payload["id"] = old_fact.id
        old_payload["superseded_by"] = new_fact.id
        # Re-upload old with superseded flag
        self._client.upsert(
            collection_name=self._collection,
            points=[
                self._PointStruct(
                    id=old_fact.id,
                    vector=self._embedder.embed(old_fact.claim),
                    payload=old_payload,
                )
            ],
        )

        # Add new version
        new_embedding = self._embedder.embed(new_claim)
        new_payload = self._fact_to_payload(new_fact)
        new_payload["id"] = new_fact.id
        self._client.upsert(
            collection_name=self._collection,
            points=[
                self._PointStruct(
                    id=new_fact.id,
                    vector=new_embedding,
                    payload=new_payload,
                )
            ],
        )

        # Update cache
        self._facts_cache[old_fact.id] = old_fact
        self._facts_cache[new_fact.id] = new_fact

        return new_fact

    def retract_fact(self, fact_id: str, reason: str = "") -> bool:
        """Retract a fact (soft delete — set confidence to 0)."""
        fact = self._facts_cache.get(fact_id)
        if not fact:
            return False

        fact.confidence = 0.0
        fact.metadata["retracted"] = True
        fact.metadata["retraction_reason"] = reason

        payload = self._fact_to_payload(fact)
        payload["id"] = fact.id
        self._client.upsert(
            collection_name=self._collection,
            points=[
                self._PointStruct(
                    id=fact.id,
                    vector=self._embedder.embed(fact.claim),
                    payload=payload,
                )
            ],
        )
        self._facts_cache[fact_id] = fact
        return True

    def delete_fact(self, fact_id: str) -> bool:
        """Hard delete a fact from Qdrant (use retract for soft delete)."""
        try:
            self._client.delete(
                collection_name=self._collection,
                points_selector=[fact_id],
            )
            self._facts_cache.pop(fact_id, None)
            self._fact_count = len(self._facts_cache)
            return True
        except Exception as e:
            logger.error(f"delete_fact failed: {e}")
            return False

    @property
    def fact_count(self) -> int:
        return self._fact_count

    # ── Seed support ────────────────────────────────────────────────

    def seed_from_list(self, facts: List[tuple]) -> int:
        """
        Bulk-seed facts from a list of (claim, domain, confidence) tuples.
        Returns number of facts added.
        """
        added = 0
        claims = [f[0] for f in facts]
        embeddings = self._embedder.embed_batch(claims)

        points = []
        for i, (claim, domain, confidence) in enumerate(facts):
            source = Source(
                name="Seed Dataset",
                authority=SourceAuthority.SECONDARY,
                authority_score=0.8,
            )
            fact = GroundTruthFact(
                claim=claim,
                domain=domain,
                confidence=confidence,
                source=source,
            )
            payload = self._fact_to_payload(fact)
            payload["id"] = fact.id
            points.append(
                self._PointStruct(
                    id=fact.id,
                    vector=embeddings[i],
                    payload=payload,
                )
            )
            self._facts_cache[fact.id] = fact
            added += 1

        if points:
            self._client.upsert(
                collection_name=self._collection,
                points=points,
            )

        self._fact_count = len(self._facts_cache)
        logger.info(f"Seeded {added} facts into Qdrant")
        return added


# ─── Factory functions (mirror verifier.py) ─────────────────────────

def create_qdrant_seed_map(
    url: Optional[str] = None,
    api_key: Optional[str] = None,
) -> QdrantBrahmanda:
    """
    Create a QdrantBrahmanda seeded with the standard 11 facts.
    Uses batch embedding for efficiency.
    """
    brahmanda = QdrantBrahmanda(url=url, api_key=api_key)

    # Only seed if collection is empty
    if brahmanda.fact_count == 0:
        seed_facts = [
            ("Paris is the capital of France", "general", 0.98),
            ("Berlin is the capital of Germany", "general", 0.98),
            ("London is the capital of the United Kingdom", "general", 0.98),
            ("Tokyo is the capital of Japan", "general", 0.98),
            ("Washington D.C. is the capital of the United States", "general", 0.98),
            ("The Earth orbits the Sun", "science", 0.99),
            ("Water boils at 100 degrees Celsius at sea level", "science", 0.99),
            ("The speed of light is approximately 299,792 kilometers per second", "science", 0.99),
            ("Einstein developed the theory of relativity", "history", 0.95),
            ("Python is a programming language", "technology", 0.99),
            ("HTTP stands for HyperText Transfer Protocol", "technology", 0.99),
        ]
        brahmanda.seed_from_list(seed_facts)
        logger.info("Seeded Qdrant with 11 default facts")
    else:
        logger.info(f"Qdrant already has {brahmanda.fact_count} facts, skipping seed")

    return brahmanda


def get_qdrant_verifier(**kwargs) -> "BrahmandaVerifier":
    """
    Get a Qdrant-backed verifier for testing/demo.

    Usage:
        from brahmanda.qdrant_client import get_qdrant_verifier
        verifier = get_qdrant_verifier(url="http://localhost:6333")
        result = verifier.verify("The capital of France is Paris")
    """
    from .verifier import BrahmandaVerifier
    brahmanda = create_qdrant_seed_map(**kwargs)
    return BrahmandaVerifier(brahmanda)
