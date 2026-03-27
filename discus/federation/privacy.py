"""
RTA-GUARD Federation — Differential Privacy

Implements the Laplace mechanism for differential privacy.
Adds calibrated noise to numerical data before sharing between nodes.
"""
import math
import secrets
import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

logger = logging.getLogger("discus.federation.privacy")


class PrivacyMode(Enum):
    """Privacy modes for the federation."""
    OFF = "off"         # No privacy (development only)
    STRICT = "strict"   # Maximum privacy, high noise
    BALANCED = "balanced"  # Good privacy/utility tradeoff
    OPEN = "open"       # Minimal privacy, better utility


@dataclass
class PrivacyConfig:
    """Configuration for differential privacy."""
    mode: PrivacyMode = PrivacyMode.BALANCED
    epsilon: float = 1.0          # Privacy budget per query
    delta: float = 1e-5           # Approximate DP parameter
    sensitivity: float = 1.0      # Global sensitivity of queries
    max_budget: float = 10.0      # Total privacy budget per node
    clip_bound: float = 10.0      # Clipping bound for values

    @classmethod
    def for_mode(cls, mode: PrivacyMode) -> "PrivacyConfig":
        """Create config for a specific privacy mode."""
        configs = {
            PrivacyMode.OFF: cls(epsilon=float("inf"), sensitivity=0.0, max_budget=float("inf")),
            PrivacyMode.STRICT: cls(epsilon=0.1, sensitivity=1.0, max_budget=1.0, clip_bound=5.0),
            PrivacyMode.BALANCED: cls(epsilon=1.0, sensitivity=1.0, max_budget=10.0, clip_bound=10.0),
            PrivacyMode.OPEN: cls(epsilon=8.0, sensitivity=1.0, max_budget=50.0, clip_bound=20.0),
        }
        return configs[mode]


class PrivacyBudget:
    """
    Tracks privacy budget consumption per node.

    Each query consumes epsilon from the budget.
    When budget is exhausted, no more queries are allowed
    (privacy is guaranteed by not leaking more data).
    """

    def __init__(self, max_budget: float = 10.0):
        self.max_budget = max_budget
        self._spent: Dict[str, float] = {}  # node_id -> spent epsilon
        self._query_count: Dict[str, int] = {}

    def can_spend(self, node_id: str, epsilon: float) -> bool:
        """Check if node has enough budget."""
        spent = self._spent.get(node_id, 0.0)
        return spent + epsilon <= self.max_budget

    def spend(self, node_id: str, epsilon: float) -> bool:
        """Spend budget. Returns False if insufficient."""
        if not self.can_spend(node_id, epsilon):
            logger.warning(f"Privacy budget exhausted for node {node_id}")
            return False
        self._spent[node_id] = self._spent.get(node_id, 0.0) + epsilon
        self._query_count[node_id] = self._query_count.get(node_id, 0) + 1
        return True

    def remaining(self, node_id: str) -> float:
        """Get remaining budget for a node."""
        return self.max_budget - self._spent.get(node_id, 0.0)

    def used(self, node_id: str) -> float:
        """Get used budget for a node."""
        return self._spent.get(node_id, 0.0)

    def query_count(self, node_id: str) -> int:
        """Get number of queries for a node."""
        return self._query_count.get(node_id, 0)

    def reset(self, node_id: Optional[str] = None):
        """Reset budget for a node or all nodes."""
        if node_id:
            self._spent.pop(node_id, None)
            self._query_count.pop(node_id, None)
        else:
            self._spent.clear()
            self._query_count.clear()

    def stats(self) -> Dict[str, Any]:
        """Get budget statistics."""
        return {
            "max_budget": self.max_budget,
            "nodes": {
                node_id: {
                    "spent": self._spent.get(node_id, 0.0),
                    "remaining": self.max_budget - self._spent.get(node_id, 0.0),
                    "queries": self._query_count.get(node_id, 0),
                }
                for node_id in set(list(self._spent.keys()) + list(self._query_count.keys()))
            },
        }


class DifferentialPrivacy:
    """
    Laplace mechanism for differential privacy.

    Adds calibrated Laplace noise to numerical values before sharing.
    The noise scale is: sensitivity / epsilon.

    Privacy guarantee:
    For any two neighboring datasets D and D' (differing in one record),
    the probability of any output differs by at most exp(epsilon).
    """

    def __init__(self, config: Optional[PrivacyConfig] = None):
        self.config = config or PrivacyConfig()
        self.budget = PrivacyBudget(self.config.max_budget)

    def add_noise_scalar(self, value: float, epsilon: Optional[float] = None,
                         sensitivity: Optional[float] = None) -> float:
        """Add Laplace noise to a single scalar value."""
        eps = epsilon or self.config.epsilon
        sens = sensitivity or self.config.sensitivity

        if self.config.mode == PrivacyMode.OFF:
            return value

        # Clip value to bound
        clipped = max(-self.config.clip_bound, min(self.config.clip_bound, value))

        # Laplace noise: scale = sensitivity / epsilon
        scale = sens / eps
        noise = np.random.laplace(0, scale)

        return clipped + noise

    def add_noise_vector(self, values: List[float], epsilon: Optional[float] = None,
                         sensitivity: Optional[float] = None) -> List[float]:
        """Add Laplace noise to a vector of values."""
        eps = epsilon or self.config.epsilon
        sens = sensitivity or self.config.sensitivity

        if self.config.mode == PrivacyMode.OFF:
            return values

        # Split budget across dimensions
        per_dim_eps = eps / max(1, len(values))
        per_dim_sens = sens  # Per-component sensitivity

        return [self.add_noise_scalar(v, per_dim_eps, per_dim_sens) for v in values]

    def anonymize_fingerprint(self, feature_vector: List[float],
                               node_id: str) -> Optional[List[float]]:
        """
        Add noise to a behavioral fingerprint before sharing.
        Checks and spends privacy budget.
        """
        if not self.budget.can_spend(node_id, self.config.epsilon):
            logger.error(f"Privacy budget exhausted for node {node_id}")
            return None

        noisy = self.add_noise_vector(feature_vector)
        self.budget.spend(node_id, self.config.epsilon)
        return noisy

    def aggregate_with_privacy(self, vectors: List[List[float]],
                                node_ids: List[str]) -> Optional[List[float]]:
        """
        Aggregate multiple noisy vectors with privacy.

        Uses secure aggregation principle: each vector is already
        noisy, so averaging preserves privacy while reducing noise.
        """
        if not vectors:
            return None

        # Check budget for all nodes
        for nid in node_ids:
            if not self.budget.can_spend(nid, self.config.epsilon):
                logger.warning(f"Node {nid} has insufficient budget, excluding from aggregation")

        # Filter to nodes with budget
        valid = [(v, nid) for v, nid in zip(vectors, node_ids)
                 if self.budget.can_spend(nid, self.config.epsilon)]

        if not valid:
            return None

        valid_vectors = [v for v, _ in valid]
        valid_nodes = [n for _, n in valid]

        # Average (noise cancels out with more participants)
        dim = len(valid_vectors[0])
        aggregated = [0.0] * dim
        for vec in valid_vectors:
            for i in range(dim):
                aggregated[i] += vec[i]
        aggregated = [v / len(valid_vectors) for v in aggregated]

        # Spend budget
        for nid in valid_nodes:
            self.budget.spend(nid, self.config.epsilon)

        return aggregated

    def compute_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        Compute cosine similarity between two vectors.
        Returns value in [-1, 1] where 1 = identical direction.
        """
        if len(vec1) != len(vec2):
            return 0.0

        dot = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot / (norm1 * norm2)

    def detect_anomaly_from_baseline(self, vector: List[float],
                                      baseline: List[float],
                                      threshold: float = 0.3) -> Tuple[bool, float]:
        """
        Detect if a vector is anomalous compared to a baseline.
        Returns (is_anomalous, distance).
        """
        similarity = self.compute_similarity(vector, baseline)
        distance = 1.0 - similarity  # 0 = identical, 2 = opposite
        return distance > threshold, distance
