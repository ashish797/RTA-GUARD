"""
RTA-GUARD — Environment Configuration (Phase 6.6)

Shared environment settings and feature flags for production deployments.
"""

import os
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Environment detection
# ---------------------------------------------------------------------------

def get_environment() -> str:
    """Return current environment: development, staging, or production."""
    return os.getenv("RTA_ENV", "development").lower()


def is_production() -> bool:
    return get_environment() == "production"


def is_development() -> bool:
    return get_environment() == "development"


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

class FeatureFlags:
    """Central feature flag management. All flags are opt-in (disabled by default)."""

    # Cost tracking
    COST_TRACKING_ENABLED = os.getenv("COST_TRACKING_ENABLED", "false").lower() in ("true", "1", "yes")

    # Quota enforcement
    QUOTA_ENFORCEMENT_ENABLED = os.getenv("QUOTA_ENFORCEMENT_ENABLED", "false").lower() in ("true", "1", "yes")

    # Batch processing
    BATCH_PROCESSING_ENABLED = os.getenv("BATCH_PROCESSING_ENABLED", "false").lower() in ("true", "1", "yes")

    # Lazy drift scoring
    LAZY_DRIFT_ENABLED = os.getenv("LAZY_DRIFT_ENABLED", "false").lower() in ("true", "1", "yes")

    # Cache warming
    CACHE_WARMING_ENABLED = os.getenv("CACHE_WARMING_ENABLED", "false").lower() in ("true", "1", "yes")

    # Audit log compression
    AUDIT_COMPRESSION_ENABLED = os.getenv("AUDIT_COMPRESSION_ENABLED", "false").lower() in ("true", "1", "yes")

    # Cost reporting
    COST_REPORTING_ENABLED = os.getenv("COST_REPORTING_ENABLED", "false").lower() in ("true", "1", "yes")

    @classmethod
    def as_dict(cls) -> dict:
        return {
            "cost_tracking": cls.COST_TRACKING_ENABLED,
            "quota_enforcement": cls.QUOTA_ENFORCEMENT_ENABLED,
            "batch_processing": cls.BATCH_PROCESSING_ENABLED,
            "lazy_drift": cls.LAZY_DRIFT_ENABLED,
            "cache_warming": cls.CACHE_WARMING_ENABLED,
            "audit_compression": cls.AUDIT_COMPRESSION_ENABLED,
            "cost_reporting": cls.COST_REPORTING_ENABLED,
            "environment": get_environment(),
        }


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path(os.getenv("RTA_DATA_DIR", "data"))
DB_DIR = DATA_DIR / "db"
REPORT_DIR = DATA_DIR / "reports"
AUDIT_DIR = DATA_DIR / "audit"

def ensure_dirs():
    """Create data directories if they don't exist."""
    for d in [DATA_DIR, DB_DIR, REPORT_DIR, AUDIT_DIR]:
        d.mkdir(parents=True, exist_ok=True)
