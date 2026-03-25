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

# Verification pipeline (Phase 2.3)
try:
    from .pipeline import VerificationPipeline, PipelineResult, ClaimVerification, get_seed_pipeline, create_pipeline
    _PIPELINE_AVAILABLE = True
except ImportError:
    _PIPELINE_AVAILABLE = False

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

if _PIPELINE_AVAILABLE:
    __all__.extend([
        "VerificationPipeline",
        "PipelineResult",
        "ClaimVerification",
        "get_seed_pipeline",
        "create_pipeline",
    ])

if _QDRANT_AVAILABLE:
    __all__.extend([
        "QdrantBrahmanda",
        "create_qdrant_seed_map",
        "get_qdrant_verifier",
    ])
