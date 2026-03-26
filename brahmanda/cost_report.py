"""
RTA-GUARD — Cost Reporting (Phase 6.6)

Daily/weekly/monthly cost reports per tenant.
Cost breakdown by resource type. Export to CSV. ROI calculations.
Cost reporting is opt-in (disabled by default).
"""

import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Optional, List, Dict, Any


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class ReportPeriod(Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


@dataclass
class CostBreakdown:
    """Cost breakdown for a single resource type."""
    resource_type: str
    category: str
    total_cost_micro_cents: int
    event_count: int
    avg_cost_per_event: float
    pct_of_total: float

    def to_dict(self) -> dict:
        return {
            "resource_type": self.resource_type,
            "category": self.category,
            "total_cost_micro_cents": self.total_cost_micro_cents,
            "total_cost_dollars": self.total_cost_micro_cents / 100_000_000,
            "event_count": self.event_count,
            "avg_cost_per_event": self.avg_cost_per_event,
            "pct_of_total": round(self.pct_of_total, 2),
        }


@dataclass
class ROICalculation:
    """ROI calculation: cost of kills vs cost of violations prevented."""
    total_kill_cost_micro_cents: int
    estimated_violation_cost_micro_cents: int
    violations_prevented: int
    cost_per_violation_prevented: float
    roi_ratio: float        # (violations_prevented_value - kill_cost) / kill_cost
    savings_micro_cents: int

    def to_dict(self) -> dict:
        return {
            "total_kill_cost_dollars": self.total_kill_cost_micro_cents / 100_000_000,
            "estimated_violation_cost_dollars": self.estimated_violation_cost_micro_cents / 100_000_000,
            "violations_prevented": self.violations_prevented,
            "cost_per_violation_prevented_dollars": self.cost_per_violation_prevented / 100_000_000,
            "roi_ratio": round(self.roi_ratio, 2),
            "savings_dollars": self.savings_micro_cents / 100_000_000,
        }


@dataclass
class CostReport:
    """Complete cost report for a tenant and period."""
    report_id: str
    tenant_id: str
    period_type: str
    period_start: str
    period_end: str
    total_cost_micro_cents: int
    total_events: int
    breakdowns: List[CostBreakdown]
    roi: Optional[ROICalculation]
    generated_at: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).isoformat()
        if not self.report_id:
            self.report_id = hashlib.sha256(
                f"{self.tenant_id}:{self.period_start}:{self.period_end}".encode()
            ).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "tenant_id": self.tenant_id,
            "period_type": self.period_type,
            "period_start": self.period_start,
            "period_end": self.period_end,
            "total_cost_micro_cents": self.total_cost_micro_cents,
            "total_cost_dollars": self.total_cost_micro_cents / 100_000_000,
            "total_events": self.total_events,
            "breakdowns": [b.to_dict() for b in self.breakdowns],
            "roi": self.roi.to_dict() if self.roi else None,
            "generated_at": self.generated_at,
        }


# ---------------------------------------------------------------------------
# Cost Report Generator
# ---------------------------------------------------------------------------

# Default estimated cost of a single violation (in micro-cents)
# This represents what an unprevented violation might cost the organization
# (data breach, compliance fine, reputation damage, etc.)
DEFAULT_VIOLATION_COST_MICRO_CENTS = 50_000_000  # ~$0.50 per violation


class CostReportGenerator:
    """
    Generates cost reports from cost summary data (from CostTracker).

    Usage:
        generator = CostReportGenerator(cost_tracker)
        report = generator.generate_report("acme", start="2026-03-01", end="2026-04-01")
        csv_data = generator.export_csv(report)
    """

    def __init__(self, cost_tracker=None,
                 violation_cost_micro_cents: int = DEFAULT_VIOLATION_COST_MICRO_CENTS):
        self._tracker = cost_tracker
        self._violation_cost = violation_cost_micro_cents

    def generate_report(self, tenant_id: str, start: str, end: str,
                        period_type: str = "custom") -> CostReport:
        """Generate a cost report from cost tracker data."""
        summary = {}
        if self._tracker:
            summary = self._tracker.get_tenant_summary(tenant_id, start, end)

        by_resource = summary.get("by_resource", {})
        by_category = summary.get("by_category", {})
        total_cost = summary.get("total_cost_micro_cents", 0)
        total_events = summary.get("total_events", 0)

        # Build breakdowns
        breakdowns = []
        for resource, data in by_resource.items():
            cost = data.get("total", 0)
            count = data.get("count", 0)
            category = self._classify_resource(resource)
            breakdowns.append(CostBreakdown(
                resource_type=resource,
                category=category,
                total_cost_micro_cents=cost,
                event_count=count,
                avg_cost_per_event=cost / count if count > 0 else 0,
                pct_of_total=(cost / total_cost * 100) if total_cost > 0 else 0,
            ))

        # Sort by cost descending
        breakdowns.sort(key=lambda b: b.total_cost_micro_cents, reverse=True)

        # ROI calculation
        roi = self._calculate_roi(summary, total_cost)

        return CostReport(
            report_id="",
            tenant_id=tenant_id,
            period_type=period_type,
            period_start=start,
            period_end=end,
            total_cost_micro_cents=total_cost,
            total_events=total_events,
            breakdowns=breakdowns,
            roi=roi,
        )

    def generate_daily_report(self, tenant_id: str, date: str) -> CostReport:
        """Generate a report for a single day (YYYY-MM-DD)."""
        start = f"{date}T00:00:00"
        end = f"{date}T23:59:59"
        return self.generate_report(tenant_id, start, end, period_type="daily")

    def generate_weekly_report(self, tenant_id: str, week_start: str) -> CostReport:
        """Generate a report for a week starting from week_start (YYYY-MM-DD)."""
        start_dt = datetime.fromisoformat(week_start)
        end_dt = start_dt + timedelta(days=7)
        return self.generate_report(
            tenant_id, start_dt.isoformat(), end_dt.isoformat(),
            period_type="weekly"
        )

    def generate_monthly_report(self, tenant_id: str, year: int, month: int) -> CostReport:
        """Generate a report for a full month."""
        start = f"{year}-{month:02d}-01T00:00:00"
        if month == 12:
            end = f"{year + 1}-01-01T00:00:00"
        else:
            end = f"{year}-{month + 1:02d}-01T00:00:00"
        return self.generate_report(tenant_id, start, end, period_type="monthly")

    def _calculate_roi(self, summary: Dict[str, Any],
                       total_cost: int) -> Optional[ROICalculation]:
        """Calculate ROI: cost of kills vs estimated cost of violations prevented."""
        by_resource = summary.get("by_resource", {})
        kill_data = by_resource.get("kill_decision", {})
        kill_cost = kill_data.get("total", 0)
        kills_prevented = kill_data.get("count", 0)

        if kills_prevented == 0:
            return None

        estimated_violation_cost = kills_prevented * self._violation_cost
        savings = estimated_violation_cost - kill_cost
        roi_ratio = savings / kill_cost if kill_cost > 0 else float('inf')

        return ROICalculation(
            total_kill_cost_micro_cents=kill_cost,
            estimated_violation_cost_micro_cents=estimated_violation_cost,
            violations_prevented=kills_prevented,
            cost_per_violation_prevented=kill_cost / kills_prevented if kills_prevented > 0 else 0,
            roi_ratio=roi_ratio,
            savings_micro_cents=savings,
        )

    @staticmethod
    def _classify_resource(resource_type: str) -> str:
        mapping = {
            "kill_decision": "compute",
            "drift_check": "compute",
            "drift_score_compute": "compute",
            "api_call": "network",
            "webhook_delivery": "network",
            "storage_mb_hour": "storage",
            "audit_log_entry": "storage",
            "compliance_report": "reporting",
            "session_tracking": "monitoring",
        }
        return mapping.get(resource_type, "compute")

    # ---- Export formats ----

    def export_csv(self, report: CostReport) -> str:
        """Export report as CSV string."""
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow(["RTA-GUARD Cost Report"])
        writer.writerow(["Tenant", report.tenant_id])
        writer.writerow(["Period", f"{report.period_start} to {report.period_end}"])
        writer.writerow(["Type", report.period_type])
        writer.writerow(["Generated", report.generated_at])
        writer.writerow([])

        # Summary
        writer.writerow(["Summary"])
        writer.writerow(["Total Cost (USD)", f"${report.total_cost_micro_cents / 100_000_000:.4f}"])
        writer.writerow(["Total Events", report.total_events])
        writer.writerow([])

        # Breakdown
        writer.writerow(["Resource Type", "Category", "Cost (USD)", "Events",
                         "Avg Cost/Event", "% of Total"])
        for b in report.breakdowns:
            writer.writerow([
                b.resource_type,
                b.category,
                f"${b.total_cost_micro_cents / 100_000_000:.4f}",
                b.event_count,
                f"${b.avg_cost_per_event / 100_000_000:.6f}",
                f"{b.pct_of_total:.1f}%",
            ])

        # ROI
        if report.roi:
            writer.writerow([])
            writer.writerow(["ROI Analysis"])
            writer.writerow(["Kill Cost (USD)", f"${report.roi.total_kill_cost_micro_cents / 100_000_000:.4f}"])
            writer.writerow(["Estimated Violation Cost (USD)",
                             f"${report.roi.estimated_violation_cost_micro_cents / 100_000_000:.4f}"])
            writer.writerow(["Violations Prevented", report.roi.violations_prevented])
            writer.writerow(["ROI Ratio", f"{report.roi.roi_ratio:.2f}x"])
            writer.writerow(["Net Savings (USD)", f"${report.roi.savings_micro_cents / 100_000_000:.4f}"])

        return output.getvalue()

    def export_json(self, report: CostReport) -> str:
        """Export report as JSON string."""
        return json.dumps(report.to_dict(), indent=2, default=str)

    def export_markdown(self, report: CostReport) -> str:
        """Export report as Markdown string."""
        lines = [
            f"# Cost Report — {report.tenant_id}",
            f"",
            f"**Period:** {report.period_start} → {report.period_end} ({report.period_type})",
            f"**Generated:** {report.generated_at}",
            f"",
            f"## Summary",
            f"",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Cost | ${report.total_cost_micro_cents / 100_000_000:.4f} |",
            f"| Total Events | {report.total_events:,} |",
            f"",
            f"## Cost Breakdown",
            f"",
            f"| Resource | Category | Cost | Events | % of Total |",
            f"|----------|----------|------|--------|-----------|",
        ]

        for b in report.breakdowns:
            lines.append(
                f"| {b.resource_type} | {b.category} | "
                f"${b.total_cost_micro_cents / 100_000_000:.4f} | "
                f"{b.event_count:,} | {b.pct_of_total:.1f}% |"
            )

        if report.roi:
            lines.extend([
                "",
                "## ROI Analysis",
                "",
                f"| Metric | Value |",
                f"|--------|-------|",
                f"| Kill Cost | ${report.roi.total_kill_cost_micro_cents / 100_000_000:.4f} |",
                f"| Est. Violation Cost | ${report.roi.estimated_violation_cost_micro_cents / 100_000_000:.4f} |",
                f"| Violations Prevented | {report.roi.violations_prevented:,} |",
                f"| ROI Ratio | {report.roi.roi_ratio:.2f}x |",
                f"| Net Savings | ${report.roi.savings_micro_cents / 100_000_000:.4f} |",
            ])

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Billing Integration Helpers
# ---------------------------------------------------------------------------

class BillingAdapter:
    """
    Adapter for billing platform integration (Stripe/Paddle).

    Generates billing events from cost reports for external invoicing.
    """

    def __init__(self, platform: str = "stripe"):
        self._platform = platform

    def generate_invoice_items(self, report: CostReport) -> List[Dict[str, Any]]:
        """Generate billing line items from a cost report."""
        items = []
        for b in report.breakdowns:
            if b.total_cost_micro_cents > 0:
                items.append({
                    "platform": self._platform,
                    "tenant_id": report.tenant_id,
                    "description": f"RTA-GUARD: {b.resource_type} ({b.category})",
                    "quantity": b.event_count,
                    "unit_amount": b.avg_cost_per_event,  # in micro-cents
                    "currency": "usd",
                    "period_start": report.period_start,
                    "period_end": report.period_end,
                    "metadata": {
                        "resource_type": b.resource_type,
                        "category": b.category,
                        "report_id": report.report_id,
                    },
                })
        return items

    def generate_stripe_payload(self, report: CostReport) -> Dict[str, Any]:
        """Generate Stripe Invoice Item API payload."""
        items = self.generate_invoice_items(report)
        return {
            "customer": report.tenant_id,
            "auto_advance": True,
            "collection_method": "charge_automatically",
            "lines": [
                {
                    "description": item["description"],
                    "quantity": item["quantity"],
                    "unit_amount": int(item["unit_amount"] / 10000),  # micro-cents to cents
                    "currency": "usd",
                    "period": {
                        "start": item["period_start"],
                        "end": item["period_end"],
                    },
                }
                for item in items
            ],
        }

    def generate_paddle_payload(self, report: CostReport) -> Dict[str, Any]:
        """Generate Paddle transaction API payload."""
        items = self.generate_invoice_items(report)
        return {
            "customer_id": report.tenant_id,
            "currency_code": "USD",
            "items": [
                {
                    "name": item["description"],
                    "quantity": item["quantity"],
                    "unit_price": {
                        "amount": str(int(item["unit_amount"] / 10000)),  # cents
                        "currency_code": "USD",
                    },
                }
                for item in items
            ],
        }
