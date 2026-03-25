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
