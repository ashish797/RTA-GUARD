"""
RTA-GUARD — Brahmanda Map Package

Ground truth database for AI hallucination prevention.
"""
from .models import (
    GroundTruthFact, Source, SourceAuthority, FactType,
    ClaimMatch, VerifyResult, VerifyDecision
)
from .verifier import BrahmandaMap, BrahmandaVerifier, get_seed_verifier, create_seed_map
from .extractor import extract_claims, ExtractedClaim

# Qdrant vector backend (optional — requires qdrant-client + openai)
try:
    from .qdrant_client import QdrantBrahmanda, create_qdrant_seed_map, get_qdrant_verifier
    _QDRANT_AVAILABLE = True
except ImportError:
    _QDRANT_AVAILABLE = False

__all__ = [
    "GroundTruthFact",
    "Source",
    "SourceAuthority",
    "FactType",
    "ClaimMatch",
    "VerifyResult",
    "VerifyDecision",
    "BrahmandaMap",
    "BrahmandaVerifier",
    "get_seed_verifier",
    "create_seed_map",
    "extract_claims",
    "ExtractedClaim",
]

if _QDRANT_AVAILABLE:
    __all__.extend([
        "QdrantBrahmanda",
        "create_qdrant_seed_map",
        "get_qdrant_verifier",
    ])
