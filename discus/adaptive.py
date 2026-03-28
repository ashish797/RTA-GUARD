"""
RTA-GUARD Discus — Adaptive Thresholds (Phase 18.1)

Dynamically adjusts violation thresholds based on observed behavior patterns.
Uses Welford's online algorithm for numerically stable statistics and
reservoir sampling for percentile computation.

The adaptive system learns what "normal" looks like per deployment and
per violation category, then sets thresholds that catch real outliers
while reducing false positives.
"""
import json
import logging
import math
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("discus.adaptive")


# ─── Welford's Online Algorithm ───────────────────────────────────


@dataclass
class _WelfordState:
    """
    Accumulator for Welford's numerically stable online mean/variance.

    Tracks count, running mean, and M2 (sum of squared deviations).
    Variance = M2 / (count - 1), standard deviation = sqrt(variance).
    """
    count: int = 0
    mean: float = 0.0
    m2: float = 0.0  # sum of squared differences from current mean

    def update(self, value: float) -> None:
        """Incorporate a new observation."""
        self.count += 1
        delta = value - self.mean
        self.mean += delta / self.count
        delta2 = value - self.mean
        self.m2 += delta * delta2

    def variance(self) -> float:
        """Sample variance (Bessel-corrected)."""
        if self.count < 2:
            return 0.0
        return self.m2 / (self.count - 1)

    def std_dev(self) -> float:
        """Sample standard deviation."""
        return math.sqrt(self.variance())

    def to_dict(self) -> Dict[str, Any]:
        return {"count": self.count, "mean": self.mean, "m2": self.m2}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "_WelfordState":
        return cls(count=data["count"], mean=data["mean"], m2=data["m2"])


# ─── Reservoir Sample ─────────────────────────────────────────────


class _ReservoirSample:
    """
    Bounded reservoir sample for percentile estimation.

    Maintains a uniform random sample of at most `capacity` items
    from an arbitrary-length stream. Uses Algorithm R (Vitter 1985).
    """

    def __init__(self, capacity: int = 1000):
        self.capacity = capacity
        self._items: List[float] = []
        self._count: int = 0

    def add(self, value: float) -> None:
        """Add an observation to the reservoir."""
        self._count += 1
        if len(self._items) < self.capacity:
            self._items.append(value)
        else:
            # Algorithm R: replace with probability capacity/count
            idx = random.randint(0, self._count - 1)
            if idx < self.capacity:
                self._items[idx] = value

    def percentile(self, p: float) -> Optional[float]:
        """
        Compute the p-th percentile from the reservoir sample.

        Args:
            p: Percentile in [0, 1] (e.g., 0.95 for P95).

        Returns:
            The estimated percentile value, or None if no samples.
        """
        if not self._items:
            return None
        sorted_items = sorted(self._items)
        k = p * (len(sorted_items) - 1)
        floor = int(math.floor(k))
        ceil = int(math.ceil(k))
        if floor == ceil:
            return sorted_items[floor]
        # Linear interpolation
        frac = k - floor
        return sorted_items[floor] * (1 - frac) + sorted_items[ceil] * frac

    @property
    def size(self) -> int:
        """Number of items in the reservoir."""
        return len(self._items)

    @property
    def total_seen(self) -> int:
        """Total observations seen (may exceed reservoir size)."""
        return self._count

    def to_list(self) -> List[float]:
        """Serialize reservoir items."""
        return self._items.copy()

    @classmethod
    def from_list(cls, items: List[float], count: int, capacity: int = 1000) -> "_ReservoirSample":
        """Deserialize reservoir from saved state."""
        obj = cls(capacity=capacity)
        obj._items = items
        obj._count = count
        return obj


# ─── BaselineProfile ──────────────────────────────────────────────


@dataclass
class BaselineProfile:
    """
    Statistical baseline for a single (deployment, category) pair.

    Captures the observed distribution of a metric (e.g., violation rate)
    so adaptive thresholds can distinguish normal behavior from outliers.
    """
    deployment_id: str = ""
    category: str = ""
    observation_count: int = 0
    mean_rate: float = 0.0
    std_dev: float = 0.0
    p50: float = 0.0
    p95: float = 0.0
    p99: float = 0.0
    last_updated: float = 0.0
    is_calibrated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "category": self.category,
            "observation_count": self.observation_count,
            "mean_rate": self.mean_rate,
            "std_dev": self.std_dev,
            "p50": self.p50,
            "p95": self.p95,
            "p99": self.p99,
            "last_updated": self.last_updated,
            "is_calibrated": self.is_calibrated,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaselineProfile":
        return cls(**data)


# ─── BaselineLearner ──────────────────────────────────────────────


class BaselineLearner:
    """
    Learns statistical baselines from observed behavior data.

    Uses Welford's online algorithm for O(1)-memory mean/variance tracking
    and bounded reservoir sampling for percentile estimation.

    A key is (deployment_id, category) — each combination gets its own
    independent baseline profile.

    Args:
        min_observations: Minimum observations before a baseline is considered
                         calibrated and trustworthy. Default 100.
        calibration_window: Time window in seconds within which observations
                           must occur for calibration. Default 3600 (1 hour).
        reservoir_capacity: Maximum items in the reservoir sample. Default 1000.
    """

    def __init__(
        self,
        min_observations: int = 100,
        calibration_window: float = 3600.0,
        reservoir_capacity: int = 1000,
    ):
        self.min_observations = min_observations
        self.calibration_window = calibration_window
        self.reservoir_capacity = reservoir_capacity
        # key -> (welford_state, reservoir_sample, first_observation_time)
        self._welford: Dict[str, _WelfordState] = {}
        self._reservoirs: Dict[str, _ReservoirSample] = {}
        self._first_seen: Dict[str, float] = {}

    def _key(self, deployment_id: str, category: str) -> str:
        return f"{deployment_id}::{category}"

    def observe(self, deployment_id: str, category: str, value: float) -> None:
        """
        Record an observation of a metric value.

        Args:
            deployment_id: Deployment identifier.
            category: Violation category (e.g., "pii", "injection").
            value: Observed metric value (e.g., violation rate, confidence loss).
        """
        key = self._key(deployment_id, category)
        now = time.time()

        if key not in self._welford:
            self._welford[key] = _WelfordState()
            self._reservoirs[key] = _ReservoirSample(self.reservoir_capacity)
            self._first_seen[key] = now

        self._welford[key].update(value)
        self._reservoirs[key].add(value)

    def get_baseline(self, deployment_id: str, category: str) -> Optional[BaselineProfile]:
        """
        Get the current baseline profile for a deployment+category.

        Returns None if no observations have been recorded.
        """
        key = self._key(deployment_id, category)
        w = self._welford.get(key)
        r = self._reservoirs.get(key)

        if w is None or r is None:
            return None

        calibrated = self._is_calibrated_internal(key, w)

        return BaselineProfile(
            deployment_id=deployment_id,
            category=category,
            observation_count=w.count,
            mean_rate=round(w.mean, 6),
            std_dev=round(w.std_dev(), 6),
            p50=round(r.percentile(0.50) or 0.0, 6),
            p95=round(r.percentile(0.95) or 0.0, 6),
            p99=round(r.percentile(0.99) or 0.0, 6),
            last_updated=time.time(),
            is_calibrated=calibrated,
        )

    def _is_calibrated_internal(self, key: str, w: _WelfordState) -> bool:
        """Check if a key has enough observations and is within the calibration window."""
        if w.count < self.min_observations:
            return False
        first = self._first_seen.get(key, 0)
        elapsed = time.time() - first
        return elapsed <= self.calibration_window

    def is_calibrated(self, deployment_id: str, category: str) -> bool:
        """Check if a baseline has enough observations to be trustworthy."""
        key = self._key(deployment_id, category)
        w = self._welford.get(key)
        if w is None:
            return False
        return self._is_calibrated_internal(key, w)

    def export(self) -> Dict[str, Any]:
        """Serialize all learner state for persistence."""
        welford_data = {}
        for k, v in self._welford.items():
            welford_data[k] = v.to_dict()

        reservoir_data = {}
        for k, v in self._reservoirs.items():
            reservoir_data[k] = {"items": v.to_list(), "count": v.total_seen}

        return {
            "min_observations": self.min_observations,
            "calibration_window": self.calibration_window,
            "reservoir_capacity": self.reservoir_capacity,
            "welford": welford_data,
            "reservoirs": reservoir_data,
            "first_seen": self._first_seen.copy(),
        }

    def import_(self, data: Dict[str, Any]) -> None:
        """Restore learner state from serialized data."""
        self.min_observations = data.get("min_observations", self.min_observations)
        self.calibration_window = data.get("calibration_window", self.calibration_window)
        self.reservoir_capacity = data.get("reservoir_capacity", self.reservoir_capacity)

        self._welford = {}
        for k, v in data.get("welford", {}).items():
            self._welford[k] = _WelfordState.from_dict(v)

        self._reservoirs = {}
        for k, v in data.get("reservoirs", {}).items():
            self._reservoirs[k] = _ReservoirSample.from_list(
                v["items"], v["count"], self.reservoir_capacity
            )

        self._first_seen = data.get("first_seen", {})


# ─── AdaptiveThreshold ────────────────────────────────────────────


@dataclass
class AdaptiveThreshold:
    """
    A threshold that adapts based on observed baseline behavior.

    Attributes:
        category: Violation category this threshold governs.
        base_threshold: The original static threshold value.
        current_threshold: The dynamically adapted threshold.
        adaptation_factor: Multiplier applied to get current from base.
        min_threshold: Floor — threshold cannot go below this.
        max_threshold: Ceiling — threshold cannot go above this.
        confidence: 0-1 indicating how much we trust the adaptation.
    """
    category: str = ""
    base_threshold: float = 0.5
    current_threshold: float = 0.5
    adaptation_factor: float = 1.0
    min_threshold: float = 0.0
    max_threshold: float = 1.0
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "base_threshold": self.base_threshold,
            "current_threshold": self.current_threshold,
            "adaptation_factor": self.adaptation_factor,
            "min_threshold": self.min_threshold,
            "max_threshold": self.max_threshold,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AdaptiveThreshold":
        return cls(**data)


# ─── AdaptiveThresholdManager ─────────────────────────────────────


class AdaptiveThresholdManager:
    """
    Manages adaptive thresholds across deployments and categories.

    Learns what "normal" looks like via the BaselineLearner, then sets
    thresholds at the P95 of the baseline (catches outliers, tolerates normal).

    Tightens after real violations, relaxes after confirmed false positives.

    Args:
        learner: A BaselineLearner instance providing statistical baselines.
        config: Optional config dict. Supported keys:
            - default_min: default min threshold floor (0.0)
            - default_max: default max threshold ceiling (1.0)
            - tighten_factor: default tighten multiplier (0.9)
            - relax_factor: default relax multiplier (1.1)
    """

    def __init__(self, learner: BaselineLearner, config: Optional[Dict[str, Any]] = None):
        self.learner = learner
        self.config = config or {}
        # (deployment_id, category) -> AdaptiveThreshold
        self._thresholds: Dict[str, AdaptiveThreshold] = {}
        # category -> (base_threshold, min_val, max_val) for registrations
        self._registrations: Dict[str, Tuple[float, float, float]] = {}
        self._default_min = self.config.get("default_min", 0.0)
        self._default_max = self.config.get("default_max", 1.0)
        self._tighten_factor = self.config.get("tighten_factor", 0.9)
        self._relax_factor = self.config.get("relax_factor", 1.1)

    def _threshold_key(self, deployment_id: str, category: str) -> str:
        return f"{deployment_id}::{category}"

    def register_threshold(
        self,
        category: str,
        base_threshold: float,
        min_val: float = 0.0,
        max_val: float = 1.0,
    ) -> None:
        """
        Register a threshold category with its base value and bounds.

        Args:
            category: Violation category (e.g., "pii", "injection").
            base_threshold: The static threshold to start from.
            min_val: Minimum allowed adapted threshold.
            max_val: Maximum allowed adapted threshold.
        """
        self._registrations[category] = (base_threshold, min_val, max_val)
        logger.debug(f"Registered adaptive threshold: {category} base={base_threshold} "
                     f"range=[{min_val}, {max_val}]")

    def _ensure_threshold(self, deployment_id: str, category: str) -> AdaptiveThreshold:
        """Get or create an AdaptiveThreshold for a deployment+category."""
        key = self._threshold_key(deployment_id, category)
        if key in self._thresholds:
            return self._thresholds[key]

        if category not in self._registrations:
            raise ValueError(f"Category '{category}' not registered. Call register_threshold first.")

        base, min_val, max_val = self._registrations[category]
        threshold = AdaptiveThreshold(
            category=category,
            base_threshold=base,
            current_threshold=base,
            min_threshold=min_val,
            max_threshold=max_val,
            confidence=0.0,
        )
        self._thresholds[key] = threshold
        return threshold

    def get_threshold(self, deployment_id: str, category: str) -> float:
        """
        Get the current adapted threshold for a deployment+category.

        Returns the adapted threshold if calibrated, otherwise the base threshold.
        """
        try:
            th = self._ensure_threshold(deployment_id, category)
        except ValueError:
            # Unregistered category — return a safe default
            return 0.5

        if not self.learner.is_calibrated(deployment_id, category):
            return th.base_threshold

        adapted = self.adapt(deployment_id, category)
        return adapted.current_threshold

    def adapt(self, deployment_id: str, category: str) -> AdaptiveThreshold:
        """
        Compute the adapted threshold based on baseline statistics.

        If calibrated: sets threshold to P95 of baseline (catches outliers,
        tolerates normal behavior). Otherwise returns base threshold.

        The adaptation factor is clamped to [min_threshold, max_threshold].
        Confidence = min(1.0, observation_count / min_observations).
        """
        th = self._ensure_threshold(deployment_id, category)
        baseline = self.learner.get_baseline(deployment_id, category)

        if baseline is None or not baseline.is_calibrated:
            th.confidence = 0.0
            th.current_threshold = th.base_threshold
            th.adaptation_factor = 1.0
            return th

        # Use P95 as the adapted threshold — catches outliers, tolerates normal
        p95 = baseline.p95
        if p95 <= 0:
            # Fallback to mean + 1 std_dev if P95 is zero
            p95 = baseline.mean_rate + baseline.std_dev

        # Compute factor relative to base
        if th.base_threshold > 0:
            factor = p95 / th.base_threshold
        else:
            factor = 1.0

        # Clamp factor so current stays within [min, max]
        current = th.base_threshold * factor
        current = max(th.min_threshold, min(th.max_threshold, current))

        # Recompute factor from clamped current
        if th.base_threshold > 0:
            factor = current / th.base_threshold

        # Confidence based on observation count
        confidence = min(1.0, baseline.observation_count / self.learner.min_observations)

        th.current_threshold = round(current, 6)
        th.adaptation_factor = round(factor, 6)
        th.confidence = round(confidence, 6)
        return th

    def tighten(self, deployment_id: str, category: str, factor: float = 0.9) -> AdaptiveThreshold:
        """
        Tighten the threshold after a real violation is detected.

        Multiplies the current threshold by the given factor (< 1.0),
        making it more sensitive.

        Args:
            deployment_id: Deployment identifier.
            category: Violation category.
            factor: Multiplier (< 1.0 tightens). Default 0.9.
        """
        th = self._ensure_threshold(deployment_id, category)
        new_current = th.current_threshold * factor
        new_current = max(th.min_threshold, new_current)
        th.current_threshold = round(new_current, 6)
        if th.base_threshold > 0:
            th.adaptation_factor = round(th.current_threshold / th.base_threshold, 6)
        logger.debug(f"Threshold tightened: {category} for {deployment_id} "
                     f"-> {th.current_threshold} (factor={factor})")
        return th

    def relax(self, deployment_id: str, category: str, factor: float = 1.1) -> AdaptiveThreshold:
        """
        Relax the threshold after a false positive is confirmed.

        Multiplies the current threshold by the given factor (> 1.0),
        making it less sensitive.

        Args:
            deployment_id: Deployment identifier.
            category: Violation category.
            factor: Multiplier (> 1.0 relaxes). Default 1.1.
        """
        th = self._ensure_threshold(deployment_id, category)
        new_current = th.current_threshold * factor
        new_current = min(th.max_threshold, new_current)
        th.current_threshold = round(new_current, 6)
        if th.base_threshold > 0:
            th.adaptation_factor = round(th.current_threshold / th.base_threshold, 6)
        logger.debug(f"Threshold relaxed: {category} for {deployment_id} "
                     f"-> {th.current_threshold} (factor={factor})")
        return th

    def record_violation(self, deployment_id: str, category: str) -> None:
        """
        Record a violation observation.

        Feeds a high value (1.0) into the learner to mark this as a
        violation event. This skews the baseline upward, eventually
        leading to tighter thresholds.
        """
        self.learner.observe(deployment_id, category, 1.0)

    def record_normal(self, deployment_id: str, category: str, value: float = 0.0) -> None:
        """
        Record a non-violation observation.

        Feeds a low value into the learner to reinforce the normal baseline,
        eventually leading to more relaxed thresholds.

        Args:
            deployment_id: Deployment identifier.
            category: Violation category.
            value: Observed metric value (0.0 = perfectly clean).
        """
        self.learner.observe(deployment_id, category, value)

    def get_all_thresholds(self, deployment_id: str) -> Dict[str, AdaptiveThreshold]:
        """
        Get all adaptive thresholds for a deployment.

        Returns a dict of category -> AdaptiveThreshold for every
        registered category that has been accessed for this deployment.
        """
        result = {}
        prefix = f"{deployment_id}::"
        for key, th in self._thresholds.items():
            if key.startswith(prefix):
                result[th.category] = th
        return result

    def export(self) -> Dict[str, Any]:
        """Serialize manager state for persistence."""
        thresholds_data = {}
        for k, v in self._thresholds.items():
            thresholds_data[k] = v.to_dict()

        registrations_data = {}
        for k, (base, min_v, max_v) in self._registrations.items():
            registrations_data[k] = {"base": base, "min": min_v, "max": max_v}

        return {
            "learner": self.learner.export(),
            "thresholds": thresholds_data,
            "registrations": registrations_data,
            "config": self.config,
        }

    def import_(self, data: Dict[str, Any]) -> None:
        """Restore manager state from serialized data."""
        if "learner" in data:
            self.learner.import_(data["learner"])

        self._thresholds = {}
        for k, v in data.get("thresholds", {}).items():
            self._thresholds[k] = AdaptiveThreshold.from_dict(v)

        self._registrations = {}
        for k, v in data.get("registrations", {}).items():
            self._registrations[k] = (v["base"], v["min"], v["max"])

        if "config" in data:
            self.config = data["config"]


# ─── DiscusGuard Integration ──────────────────────────────────────


def integrate_adaptive_guard(guard, adaptive_manager: AdaptiveThresholdManager) -> None:
    """
    Attach an AdaptiveThresholdManager to a DiscusGuard instance.

    Adds the manager as guard.adaptive_manager and exposes
    get_adaptive_report().

    Args:
        guard: A DiscusGuard instance.
        adaptive_manager: The AdaptiveThresholdManager to integrate.
    """
    guard.adaptive_manager = adaptive_manager

    def get_adaptive_report(deployment_id: str) -> Dict[str, Any]:
        """Get a report of all adaptive thresholds for a deployment."""
        thresholds = adaptive_manager.get_all_thresholds(deployment_id)
        report: Dict[str, Any] = {
            "deployment_id": deployment_id,
            "thresholds": {},
            "calibrated_categories": [],
            "uncalibrated_categories": [],
        }
        for cat, th in thresholds.items():
            baseline = adaptive_manager.learner.get_baseline(deployment_id, cat)
            report["thresholds"][cat] = th.to_dict()
            if baseline and baseline.is_calibrated:
                report["calibrated_categories"].append(cat)
                report["thresholds"][cat]["baseline"] = baseline.to_dict()
            else:
                report["uncalibrated_categories"].append(cat)
        report["total_categories"] = len(thresholds)
        return report

    guard.get_adaptive_report = get_adaptive_report

    # Patch check() to use adaptive thresholds
    _original_check = guard.check

    def adaptive_check(text: str, session_id: str = "default",
                       user_id: str = "", agent_role: str = None,
                       check_output: bool = False,
                       deployment_id: str = "default"):
        """
        Enhanced check() that uses adaptive thresholds before static rules.

        Falls through to original check() after computing adapted thresholds.
        The adapted threshold is stored on the guard for inspection.
        """
        # Compute adapted thresholds for all registered categories
        for category in adaptive_manager._registrations:
            th = adaptive_manager.adapt(deployment_id, category)
            setattr(guard, f"_adaptive_threshold_{category}", th.current_threshold)

        guard._current_adaptive_deployment = deployment_id
        return _original_check(text, session_id=session_id, user_id=user_id,
                               agent_role=agent_role, check_output=check_output)

    guard.check = adaptive_check
    logger.info("AdaptiveThresholdManager integrated with DiscusGuard")
