"""
RTA-GUARD — Brahmanda Map Package

Ground truth database for AI hallucination prevention.
Phase 2.4: Source attribution, provenance tracking, audit trail.
"""
from .models import (
    GroundTruthFact, Source, SourceAuthority, FactType,
    ClaimMatch, VerifyResult, VerifyDecision,
    FactProvenance, AuditEntry, AuditAction,
    confidence_for_authority, SOURCE_CONFIDENCE_RANGES,
)
from .verifier import BrahmandaMap, BrahmandaVerifier, get_seed_verifier, create_seed_map
from .extractor import extract_claims, ExtractedClaim
from .attribution import (
    SourceRegistry, FactProvenanceTracker, AuditTrail, AttributionManager,
)

# Verification pipeline (Phase 2.3)
try:
    from .pipeline import VerificationPipeline, PipelineResult, ClaimVerification, get_seed_pipeline, create_pipeline
    _PIPELINE_AVAILABLE = True
except ImportError:
    _PIPELINE_AVAILABLE = False

# Confidence scoring (Phase 2.5)
try:
    from .confidence import (
        ConfidenceScorer, ConfidenceExplanation, ConfidenceLevel,
        HIGH_CONFIDENCE_THRESHOLD, MEDIUM_CONFIDENCE_THRESHOLD,
    )
    _CONFIDENCE_AVAILABLE = True
except ImportError:
    _CONFIDENCE_AVAILABLE = False

# Qdrant vector backend (optional — requires qdrant-client + openai)
try:
    from .qdrant_client import QdrantBrahmanda, create_qdrant_seed_map, get_qdrant_verifier
    _QDRANT_AVAILABLE = True
except ImportError:
    _QDRANT_AVAILABLE = False

__all__ = [
    # Models
    "GroundTruthFact",
    "Source",
    "SourceAuthority",
    "FactType",
    "ClaimMatch",
    "VerifyResult",
    "VerifyDecision",
    "FactProvenance",
    "AuditEntry",
    "AuditAction",
    "confidence_for_authority",
    "SOURCE_CONFIDENCE_RANGES",
    # Verifier
    "BrahmandaMap",
    "BrahmandaVerifier",
    "get_seed_verifier",
    "create_seed_map",
    # Extractor
    "extract_claims",
    "ExtractedClaim",
    # Attribution (Phase 2.4)
    "SourceRegistry",
    "FactProvenanceTracker",
    "AuditTrail",
    "AttributionManager",
]

if _PIPELINE_AVAILABLE:
    __all__.extend([
        "VerificationPipeline",
        "PipelineResult",
        "ClaimVerification",
        "get_seed_pipeline",
        "create_pipeline",
    ])

if _CONFIDENCE_AVAILABLE:
    __all__.extend([
        "ConfidenceScorer",
        "ConfidenceExplanation",
        "ConfidenceLevel",
        "HIGH_CONFIDENCE_THRESHOLD",
        "MEDIUM_CONFIDENCE_THRESHOLD",
    ])

if _QDRANT_AVAILABLE:
    __all__.extend([
        "QdrantBrahmanda",
        "create_qdrant_seed_map",
        "get_qdrant_verifier",
    ])
