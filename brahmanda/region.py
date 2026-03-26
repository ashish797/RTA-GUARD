"""
RTA-GUARD — Region-Aware Configuration (Phase 6.5)

Multi-region support with geo-routing, latency budgets, data residency
rules, and automatic region failover. Opt-in: defaults to single-region.
"""

from __future__ import annotations

import math
import time
import threading
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Region definitions
# ---------------------------------------------------------------------------

class Region(Enum):
    """Supported deployment regions."""
    US_EAST_1 = "us-east-1"
    US_WEST_2 = "us-west-2"
    EU_WEST_1 = "eu-west-1"
    AP_SOUTH_1 = "ap-south-1"
    AP_SOUTHEAST_1 = "ap-southeast-1"


# Approximate lat/lon centres for geo-routing distance calculations
_REGION_COORDS: Dict[Region, Tuple[float, float]] = {
    Region.US_EAST_1: (39.0438, -77.4874),      # N. Virginia
    Region.US_WEST_2: (45.5945, -121.1787),      # Oregon
    Region.EU_WEST_1: (53.3498, -6.2603),        # Ireland
    Region.AP_SOUTH_1: (19.0760, 72.8777),       # Mumbai
    Region.AP_SOUTHEAST_1: (1.3521, 103.8198),   # Singapore
}

# Default latency budgets in milliseconds
_DEFAULT_LATENCY_BUDGETS: Dict[Region, int] = {
    Region.US_EAST_1: 100,
    Region.US_WEST_2: 120,
    Region.EU_WEST_1: 150,
    Region.AP_SOUTH_1: 150,
    Region.AP_SOUTHEAST_1: 130,
}

# Data residency constraints: list of data classifications allowed to leave
# the region. Empty list = all data must stay local.
_DEFAULT_RESIDENCY_RULES: Dict[Region, List[str]] = {
    Region.US_EAST_1: ["telemetry", "aggregated_metrics"],
    Region.US_WEST_2: ["telemetry", "aggregated_metrics"],
    Region.EU_WEST_1: [],  # GDPR strict — no data egress
    Region.AP_SOUTH_1: ["telemetry"],
    Region.AP_SOUTHEAST_1: ["telemetry", "aggregated_metrics"],
}


# ---------------------------------------------------------------------------
# Region-local config
# ---------------------------------------------------------------------------

@dataclass
class RegionConfig:
    """Configuration for a single region."""
    region: Region
    endpoint: str = ""
    latency_budget_ms: int = 100
    data_residency_allowlist: List[str] = field(default_factory=list)
    is_primary: bool = False
    failover_priority: int = 0  # 0 = highest priority
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "region": self.region.value,
            "endpoint": self.endpoint,
            "latency_budget_ms": self.latency_budget_ms,
            "data_residency_allowlist": self.data_residency_allowlist,
            "is_primary": self.is_primary,
            "failover_priority": self.failover_priority,
            "enabled": self.enabled,
        }


# ---------------------------------------------------------------------------
# Geo-routing helpers
# ---------------------------------------------------------------------------

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km between two lat/lon points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def nearest_region(client_lat: float, client_lon: float,
                   available: Optional[List[Region]] = None) -> Region:
    """Return the region geographically closest to the client."""
    candidates = available or list(Region)
    best: Optional[Region] = None
    best_dist = float("inf")
    for r in candidates:
        lat, lon = _REGION_COORDS[r]
        d = _haversine_km(client_lat, client_lon, lat, lon)
        if d < best_dist:
            best_dist = d
            best = r
    assert best is not None
    return best


def estimate_latency_ms(client_lat: float, client_lon: float,
                        region: Region) -> float:
    """Rough latency estimate based on distance (light-in-fibre ≈ 5 µs/km)."""
    lat, lon = _REGION_COORDS[region]
    dist_km = _haversine_km(client_lat, client_lon, lat, lon)
    # ~5 µs/km in fibre + 20 ms base overhead
    return dist_km * 0.005 + 20.0


# ---------------------------------------------------------------------------
# Region health tracking
# ---------------------------------------------------------------------------

@dataclass
class RegionHealth:
    """Health snapshot for a region."""
    region: Region
    healthy: bool = True
    latency_ms: float = 0.0
    last_check: float = 0.0
    consecutive_failures: int = 0

    def to_dict(self) -> dict:
        return {
            "region": self.region.value,
            "healthy": self.healthy,
            "latency_ms": round(self.latency_ms, 2),
            "last_check": self.last_check,
            "consecutive_failures": self.consecutive_failures,
        }


# ---------------------------------------------------------------------------
# Region Router
# ---------------------------------------------------------------------------

class RegionRouter:
    """
    Routes requests to the nearest healthy region with automatic failover.

    Usage:
        router = RegionRouter(regions_config)
        target = router.route(client_lat=19.07, client_lon=72.88)
    """

    def __init__(self, configs: Optional[List[RegionConfig]] = None,
                 failover_threshold: int = 3):
        self._lock = threading.Lock()
        self._failover_threshold = failover_threshold
        self._health: Dict[Region, RegionHealth] = {}

        if configs:
            self._configs = {c.region: c for c in configs}
        else:
            # Default single-region config
            self._configs = {
                Region.US_EAST_1: RegionConfig(
                    region=Region.US_EAST_1,
                    latency_budget_ms=_DEFAULT_LATENCY_BUDGETS[Region.US_EAST_1],
                    data_residency_allowlist=_DEFAULT_RESIDENCY_RULES[Region.US_EAST_1],
                    is_primary=True,
                    failover_priority=0,
                )
            }

        for r in self._configs:
            self._health[r] = RegionHealth(region=r)

    # -- public API --

    def route(self, client_lat: Optional[float] = None,
              client_lon: Optional[float] = None) -> Region:
        """
        Route to the nearest healthy region.

        If no coordinates are provided, returns the primary region (or first
        healthy region by failover priority).
        """
        with self._lock:
            healthy_regions = [
                r for r, h in self._health.items()
                if h.healthy and self._configs[r].enabled
            ]
            if not healthy_regions:
                # Desperate: return any configured region
                logger.error("No healthy regions available — returning primary")
                return self._primary_region()

            if client_lat is not None and client_lon is not None:
                return nearest_region(client_lat, client_lon, healthy_regions)

            # No geo info → pick by failover priority
            return min(
                healthy_regions,
                key=lambda r: self._configs[r].failover_priority,
            )

    def report_health(self, region: Region, healthy: bool,
                      latency_ms: float = 0.0) -> None:
        """Report health check result for a region."""
        with self._lock:
            h = self._health.get(region)
            if h is None:
                return
            h.last_check = time.time()
            h.latency_ms = latency_ms
            if healthy:
                h.healthy = True
                h.consecutive_failures = 0
            else:
                h.consecutive_failures += 1
                if h.consecutive_failures >= self._failover_threshold:
                    h.healthy = False
                    logger.warning(
                        "Region %s marked unhealthy after %d failures",
                        region.value, h.consecutive_failures,
                    )

    def get_failover_chain(self) -> List[Region]:
        """Return regions ordered by failover priority."""
        return sorted(
            self._configs.keys(),
            key=lambda r: self._configs[r].failover_priority,
        )

    def get_region_config(self, region: Region) -> Optional[RegionConfig]:
        return self._configs.get(region)

    def all_health(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [h.to_dict() for h in self._health.values()]

    def check_data_residency(self, region: Region,
                             data_classification: str) -> bool:
        """Check whether a data classification is allowed to leave the region."""
        cfg = self._configs.get(region)
        if cfg is None:
            return False
        return data_classification in cfg.data_residency_allowlist

    # -- internals --

    def _primary_region(self) -> Region:
        for r, c in self._configs.items():
            if c.is_primary:
                return r
        return next(iter(self._configs))


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_router: Optional[RegionRouter] = None


def get_router(configs: Optional[List[RegionConfig]] = None) -> RegionRouter:
    """Get or create the module-level RegionRouter singleton."""
    global _router
    if _router is None:
        _router = RegionRouter(configs)
    return _router


def reset_router() -> None:
    """Reset singleton (for testing)."""
    global _router
    _router = None
