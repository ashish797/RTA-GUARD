"""
RTA-GUARD Discus — A/B Testing & Guard Analytics

Provides experiment running, shadow guarding, and analytics
for measuring guard effectiveness.
"""
import hashlib
import logging
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("discus.analytics")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GuardExperiment:
    """Configuration for an A/B test between two guard variants."""
    experiment_id: str
    name: str
    variant_a_name: str = "control"
    variant_b_name: str = "strict"
    variant_a_config: Dict = field(default_factory=dict)
    variant_b_config: Dict = field(default_factory=dict)
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None
    status: str = "running"  # running | completed | cancelled
    sample_size: int = 1000


@dataclass
class VariantStats:
    """Per-variant statistics for an experiment."""
    name: str
    total_checks: int = 0
    violations_caught: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    catch_rate: float = 0.0
    false_positive_rate: float = 0.0
    precision: float = 0.0
    throughput_per_second: float = 0.0

    def compute(self, latencies: List[float], total_time_seconds: float):
        """Recompute derived fields from raw data."""
        self.catch_rate = (
            self.violations_caught / self.total_checks
            if self.total_checks > 0 else 0.0
        )
        self.false_positive_rate = (
            self.false_positives / self.total_checks
            if self.total_checks > 0 else 0.0
        )
        denom = self.violations_caught + self.false_positives
        self.precision = (
            self.violations_caught / denom if denom > 0 else 0.0
        )
        if latencies:
            self.avg_latency_ms = statistics.mean(latencies)
            sorted_lat = sorted(latencies)
            idx = min(int(len(sorted_lat) * 0.95), len(sorted_lat) - 1)
            self.p95_latency_ms = sorted_lat[idx]
        if total_time_seconds > 0:
            self.throughput_per_second = self.total_checks / total_time_seconds


@dataclass
class ExperimentResult:
    """Aggregated result of an A/B experiment."""
    experiment_id: str
    variant_a: VariantStats
    variant_b: VariantStats
    winner: Optional[str] = None  # "a" | "b" | None
    confidence: float = 0.0
    recommendation: str = ""


@dataclass
class ShadowReport:
    """Report from shadow guard comparison."""
    primary_violations: int = 0
    shadow_violations: int = 0
    shadow_only_violations: int = 0
    primary_only_violations: int = 0
    overlap_count: int = 0
    overlap_rate: float = 0.0


@dataclass
class ComparisonStats:
    """Statistical comparison between primary and shadow guard."""
    primary_catch_rate: float = 0.0
    shadow_catch_rate: float = 0.0
    primary_avg_latency_ms: float = 0.0
    shadow_avg_latency_ms: float = 0.0
    recommendation: str = "keep_primary"


@dataclass
class AnalyticsStats:
    """Aggregate guard analytics."""
    total_checks: int = 0
    total_violations: int = 0
    catch_rate: float = 0.0
    avg_latency_ms: float = 0.0
    p50_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    p99_latency_ms: float = 0.0
    checks_per_second: float = 0.0
    uptime_seconds: float = 0.0


@dataclass
class RuleStats:
    """Per-rule trigger statistics."""
    rule_name: str = ""
    trigger_count: int = 0
    trigger_rate: float = 0.0
    avg_latency_ms: float = 0.0


@dataclass
class CategoryStats:
    """Violation category breakdown."""
    category: str = ""
    count: int = 0
    percentage: float = 0.0


@dataclass
class TimeBucket:
    """Time-bucketed analytics."""
    timestamp: float = 0.0
    checks: int = 0
    violations: int = 0
    avg_latency_ms: float = 0.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _percentile(data: List[float], pct: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = min(int(len(s) * pct), len(s) - 1)
    return s[idx]


# ---------------------------------------------------------------------------
# ExperimentRunner
# ---------------------------------------------------------------------------

class ExperimentRunner:
    """
    Deterministic A/B routing: hashes input text to pick variant A or B.
    """

    def __init__(self, guard_a: Any, guard_b: Any, experiment: GuardExperiment):
        self.guard_a = guard_a
        self.guard_b = guard_b
        self.experiment = experiment
        # Raw data per variant
        self._latencies: Dict[str, List[float]] = {"a": [], "b": []}
        self._violations_caught: Dict[str, int] = {"a": 0, "b": 0}
        self._false_positives: Dict[str, int] = {"a": 0, "b": 0}
        self._false_negatives: Dict[str, int] = {"a": 0, "b": 0}
        self._total_checks: Dict[str, int] = {"a": 0, "b": 0}
        self._start_time: float = time.time()

    # -- routing -----------------------------------------------------------

    def _pick_variant(self, text: str) -> str:
        h = int(hashlib.md5(text.encode("utf-8")).hexdigest(), 16)
        return "a" if h % 2 == 0 else "b"

    def route(self, text: str, is_input: bool = True) -> Tuple[Any, str]:
        """Route text to variant A or B, run guard check, return (response, variant)."""
        variant = self._pick_variant(text)
        guard = self.guard_a if variant == "a" else self.guard_b
        t0 = time.monotonic()
        try:
            response = guard.check(text)
        except Exception:
            response = None
        latency = (time.monotonic() - t0) * 1000.0
        caught = response is None  # SessionKilledError -> caught violation
        self.record_result(variant, caught, latency)
        return response, variant

    def record_result(self, variant: str, caught: bool, latency_ms: float,
                      is_true_positive: bool = None):
        """Record a single observation for a variant."""
        self._total_checks[variant] += 1
        self._latencies[variant].append(latency_ms)
        if caught:
            self._violations_caught[variant] += 1
            if is_true_positive is False:
                self._false_positives[variant] += 1
        elif is_true_positive is True:
            # True violation existed but was missed
            self._false_negatives[variant] += 1

    # -- results -----------------------------------------------------------

    def _build_variant_stats(self, variant: str) -> VariantStats:
        name = (
            self.experiment.variant_a_name if variant == "a"
            else self.experiment.variant_b_name
        )
        elapsed = time.time() - self._start_time
        vs = VariantStats(
            name=name,
            total_checks=self._total_checks[variant],
            violations_caught=self._violations_caught[variant],
            false_positives=self._false_positives[variant],
            false_negatives=self._false_negatives[variant],
        )
        vs.compute(self._latencies[variant], elapsed)
        return vs

    def get_results(self) -> ExperimentResult:
        va = self._build_variant_stats("a")
        vb = self._build_variant_stats("b")
        winner, confidence = self._determine_winner(va, vb)
        rec = self._make_recommendation(winner, va, vb)
        return ExperimentResult(
            experiment_id=self.experiment.experiment_id,
            variant_a=va,
            variant_b=vb,
            winner=winner,
            confidence=confidence,
            recommendation=rec,
        )

    def _determine_winner(self, a: VariantStats, b: VariantStats) -> Tuple[Optional[str], float]:
        """Simple heuristic winner determination based on catch rate + precision."""
        if a.total_checks == 0 or b.total_checks == 0:
            return None, 0.0
        # Score = catch_rate * (1 - false_positive_rate)
        score_a = a.catch_rate * (1.0 - a.false_positive_rate)
        score_b = b.catch_rate * (1.0 - b.false_positive_rate)
        diff = abs(score_a - score_b)
        if diff < 0.05:
            return None, diff
        if score_a > score_b:
            return "a", min(diff, 1.0)
        return "b", min(diff, 1.0)

    def _make_recommendation(self, winner: Optional[str],
                             a: VariantStats, b: VariantStats) -> str:
        if winner is None:
            return "inconclusive — consider increasing sample size"
        if winner == "a":
            return f"Use {a.name}: higher overall score"
        return f"Use {b.name}: higher overall score"

    def is_complete(self) -> bool:
        min_observations = min(self._total_checks["a"], self._total_checks["b"])
        return min_observations >= self.experiment.sample_size

    def finalize(self) -> ExperimentResult:
        self.experiment.status = "completed"
        self.experiment.ended_at = time.time()
        return self.get_results()


# ---------------------------------------------------------------------------
# ShadowGuard
# ---------------------------------------------------------------------------

class ShadowGuard:
    """
    Runs a primary guard (blocking) and a shadow guard (observe-only) in parallel.
    """

    def __init__(self, primary_guard: Any, shadow_guard: Any):
        self.primary_guard = primary_guard
        self.shadow_guard = shadow_guard
        self._total_checks: int = 0
        # Track which guard caught each check
        self._primary_caught: List[bool] = []
        self._shadow_caught: List[bool] = []
        self._primary_latencies: List[float] = []
        self._shadow_latencies: List[float] = []

    def check(self, text: str, **kwargs) -> Any:
        """Run primary guard (blocking) and shadow guard (observe-only)."""
        self._total_checks += 1

        # Primary — can raise
        t0 = time.monotonic()
        primary_exc = None
        result = None
        try:
            result = self.primary_guard.check(text, **kwargs)
        except Exception as e:
            primary_exc = e
        primary_latency = (time.monotonic() - t0) * 1000.0
        primary_caught = primary_exc is not None
        self._primary_caught.append(primary_caught)
        self._primary_latencies.append(primary_latency)

        # Shadow — never raises, observe only
        t1 = time.monotonic()
        shadow_caught = False
        try:
            self.shadow_guard.check(text, **kwargs)
        except Exception:
            shadow_caught = True
        shadow_latency = (time.monotonic() - t1) * 1000.0
        self._shadow_caught.append(shadow_caught)
        self._shadow_latencies.append(shadow_latency)

        # Re-raise primary exception if needed
        if primary_exc is not None:
            raise primary_exc

        return result

    def get_shadow_report(self) -> ShadowReport:
        primary_violations = sum(self._primary_caught)
        shadow_violations = sum(self._shadow_caught)
        overlap = sum(
            1 for p, s in zip(self._primary_caught, self._shadow_caught) if p and s
        )
        shadow_only = sum(
            1 for p, s in zip(self._primary_caught, self._shadow_caught) if not p and s
        )
        primary_only = sum(
            1 for p, s in zip(self._primary_caught, self._shadow_caught) if p and not s
        )
        total_caught = primary_violations + shadow_violations
        return ShadowReport(
            primary_violations=primary_violations,
            shadow_violations=shadow_violations,
            shadow_only_violations=shadow_only,
            primary_only_violations=primary_only,
            overlap_count=overlap,
            overlap_rate=(overlap * 2 / total_caught) if total_caught > 0 else 0.0,
        )

    def compare(self) -> ComparisonStats:
        report = self.get_shadow_report()
        p_rate = (
            report.primary_violations / self._total_checks
            if self._total_checks > 0 else 0.0
        )
        s_rate = (
            report.shadow_violations / self._total_checks
            if self._total_checks > 0 else 0.0
        )
        p_avg = statistics.mean(self._primary_latencies) if self._primary_latencies else 0.0
        s_avg = statistics.mean(self._shadow_latencies) if self._shadow_latencies else 0.0

        # Recommendation logic
        if s_rate > p_rate and s_avg <= p_avg * 1.5:
            rec = "switch_to_shadow"
        elif abs(p_rate - s_rate) < 0.02 and s_avg < p_avg:
            rec = "merge_configs"
        else:
            rec = "keep_primary"

        return ComparisonStats(
            primary_catch_rate=p_rate,
            shadow_catch_rate=s_rate,
            primary_avg_latency_ms=p_avg,
            shadow_avg_latency_ms=s_avg,
            recommendation=rec,
        )


# ---------------------------------------------------------------------------
# ROIReport
# ---------------------------------------------------------------------------

# Default breach costs (USD)
DEFAULT_BREACH_COSTS: Dict[str, float] = {
    "pii_detected": 15000.0,
    "prompt_injection": 50000.0,
    "jailbreak": 25000.0,
    "hallucination": 10000.0,
    "sensitive_content": 20000.0,
    "destructive_action": 100000.0,
    "harmful_content": 30000.0,
    "custom": 5000.0,
}


class ROIReport:
    """Return-on-investment report for guard deployment."""

    def __init__(self, breach_costs: Optional[Dict[str, float]] = None,
                 hourly_rate: float = 150.0):
        self.pii_leaks_prevented: int = 0
        self.injection_attacks_blocked: int = 0
        self.hallucinations_caught: int = 0
        self.total_violations_prevented: int = 0
        self.estimated_breach_cost_saved: float = 0.0
        self.guard_cost: float = 0.0
        self.roi_ratio: float = 0.0
        self._breach_costs = breach_costs or DEFAULT_BREACH_COSTS
        self._hourly_rate = hourly_rate

    def populate(self, check_records: List[Dict]):
        """
        Build ROI from analytics check records.
        Each record: {"violation_type": str|None, "caught": bool, "latency_ms": float}
        """
        total_latency_ms = 0.0
        for rec in check_records:
            total_latency_ms += rec.get("latency_ms", 0.0)
            vtype = rec.get("violation_type")
            if vtype and rec.get("caught"):
                self.total_violations_prevented += 1
                cost = self._breach_costs.get(vtype, 5000.0)
                self.estimated_breach_cost_saved += cost
                low = vtype.lower().replace(" ", "_")
                if "pii" in low:
                    self.pii_leaks_prevented += 1
                if any(k in low for k in ("injection", "jailbreak", "prompt")):
                    self.injection_attacks_blocked += 1
                if "hallucination" in low or "unverified" in low:
                    self.hallucinations_caught += 1
        # Guard cost: total latency (hours) * hourly rate
        hours = total_latency_ms / 3_600_000.0
        self.guard_cost = hours * self._hourly_rate
        if self.guard_cost > 0:
            self.roi_ratio = self.estimated_breach_cost_saved / self.guard_cost
        else:
            self.roi_ratio = float("inf") if self.estimated_breach_cost_saved > 0 else 0.0

    def generate_summary(self) -> str:
        lines = [
            "=== RTA-GUARD ROI Report ===",
            f"PII leaks prevented:        {self.pii_leaks_prevented}",
            f"Injection attacks blocked:  {self.injection_attacks_blocked}",
            f"Hallucinations caught:      {self.hallucinations_caught}",
            f"Total violations prevented: {self.total_violations_prevented}",
            f"Est. breach cost saved:     ${self.estimated_breach_cost_saved:,.2f}",
            f"Guard operating cost:       ${self.guard_cost:,.2f}",
            f"ROI ratio:                  {self.roi_ratio:.1f}x",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# GuardAnalytics
# ---------------------------------------------------------------------------

class _CheckRecord:
    """Internal record for a single guard check."""
    __slots__ = ("timestamp", "text", "caught", "violation_type", "latency_ms", "is_true_positive")

    def __init__(self, text: str, caught: bool, violation_type: Optional[str],
                 latency_ms: float, is_true_positive: Optional[bool]):
        self.timestamp = time.time()
        self.text = text
        self.caught = caught
        self.violation_type = violation_type
        self.latency_ms = latency_ms
        self.is_true_positive = is_true_positive


class GuardAnalytics:
    """
    Collects and analyses guard check data.
    """

    def __init__(self, guard: Any):
        self.guard = guard
        self._records: List[_CheckRecord] = []
        self._start_time: float = time.time()

    def record_check(self, text: str, caught: bool, violation_type: str = None,
                     latency_ms: float = 0, is_true_positive: bool = None):
        self._records.append(
            _CheckRecord(text, caught, violation_type, latency_ms, is_true_positive)
        )

    # -- stats -------------------------------------------------------------

    def get_stats(self, time_window_seconds: Optional[float] = None) -> AnalyticsStats:
        records = self._filter_by_time(time_window_seconds)
        latencies = [r.latency_ms for r in records]
        violations = sum(1 for r in records if r.caught)
        total = len(records)
        elapsed = time.time() - self._start_time
        window = time_window_seconds or elapsed
        stats = AnalyticsStats(
            total_checks=total,
            total_violations=violations,
            catch_rate=(violations / total) if total > 0 else 0.0,
            avg_latency_ms=statistics.mean(latencies) if latencies else 0.0,
            p50_latency_ms=_percentile(latencies, 0.50),
            p95_latency_ms=_percentile(latencies, 0.95),
            p99_latency_ms=_percentile(latencies, 0.99),
            checks_per_second=(total / window) if window > 0 else 0.0,
            uptime_seconds=elapsed,
        )
        return stats

    # -- rule breakdown ----------------------------------------------------

    def get_rule_breakdown(self) -> Dict[str, RuleStats]:
        total = len(self._records)
        buckets: Dict[str, List[_CheckRecord]] = {}
        for r in self._records:
            if r.violation_type:
                buckets.setdefault(r.violation_type, []).append(r)
        result: Dict[str, RuleStats] = {}
        for name, recs in buckets.items():
            lat = [r.latency_ms for r in recs]
            result[name] = RuleStats(
                rule_name=name,
                trigger_count=len(recs),
                trigger_rate=(len(recs) / total) if total > 0 else 0.0,
                avg_latency_ms=statistics.mean(lat) if lat else 0.0,
            )
        return result

    # -- category breakdown ------------------------------------------------

    def get_category_breakdown(self) -> Dict[str, CategoryStats]:
        total = len(self._records)
        counts: Dict[str, int] = {}
        for r in self._records:
            cat = r.violation_type or "no_violation"
            counts[cat] = counts.get(cat, 0) + 1
        return {
            cat: CategoryStats(
                category=cat,
                count=n,
                percentage=(n / total * 100.0) if total > 0 else 0.0,
            )
            for cat, n in counts.items()
        }

    # -- time series -------------------------------------------------------

    def get_time_series(self, bucket_seconds: float = 3600) -> List[TimeBucket]:
        if not self._records:
            return []
        start = self._records[0].timestamp
        buckets: Dict[int, List[_CheckRecord]] = {}
        for r in self._records:
            idx = int((r.timestamp - start) // bucket_seconds)
            buckets.setdefault(idx, []).append(r)
        result: List[TimeBucket] = []
        for idx in sorted(buckets):
            recs = buckets[idx]
            lat = [r.latency_ms for r in recs]
            result.append(TimeBucket(
                timestamp=start + idx * bucket_seconds,
                checks=len(recs),
                violations=sum(1 for r in recs if r.caught),
                avg_latency_ms=statistics.mean(lat) if lat else 0.0,
            ))
        return result

    # -- false positive estimate -------------------------------------------

    def get_false_positive_estimate(self) -> float:
        """Estimate FP rate from records that have ground truth."""
        labelled = [r for r in self._records if r.is_true_positive is not None]
        if not labelled:
            return 0.0
        fps = sum(1 for r in labelled if r.caught and r.is_true_positive is False)
        return fps / len(labelled)

    # -- ROI ---------------------------------------------------------------

    def get_roi_report(self, breach_costs: Optional[Dict[str, float]] = None,
                       hourly_rate: float = 150.0) -> ROIReport:
        report = ROIReport(breach_costs=breach_costs, hourly_rate=hourly_rate)
        records_for_roi = [
            {
                "violation_type": r.violation_type,
                "caught": r.caught,
                "latency_ms": r.latency_ms,
            }
            for r in self._records
        ]
        report.populate(records_for_roi)
        return report

    # -- internal ----------------------------------------------------------

    def _filter_by_time(self, window_seconds: Optional[float]) -> List[_CheckRecord]:
        if window_seconds is None:
            return self._records
        cutoff = time.time() - window_seconds
        return [r for r in self._records if r.timestamp >= cutoff]


# ---------------------------------------------------------------------------
# DiscusGuard integration helper
# ---------------------------------------------------------------------------

def attach_analytics(guard: Any, analytics: GuardAnalytics):
    """
    Monkey-patch a DiscusGuard instance to auto-record analytics on check().
    Call this after creating the guard to avoid modifying guard.py directly.
    """
    _original_check = guard.check

    def _patched_check(text: str, **kwargs):
        t0 = time.monotonic()
        caught = False
        vtype = None
        try:
            result = _original_check(text, **kwargs)
        except Exception as e:
            caught = True
            # Extract violation type from the exception's event if available
            event = getattr(e, "event", None)
            if event and hasattr(event, "violation_type") and event.violation_type:
                vtype = str(event.violation_type.value) if hasattr(event.violation_type, "value") else str(event.violation_type)
            raise
        finally:
            latency = (time.monotonic() - t0) * 1000.0
            analytics.record_check(text, caught, vtype, latency)
        return result

    guard.check = _patched_check
    guard.analytics = analytics
