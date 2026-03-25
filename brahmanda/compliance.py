"""
RTA-GUARD — Compliance Reporting (Phase 4.3)

Generates structured compliance reports for regulatory submissions.
Supports EU AI Act (Title III), SOC2, HIPAA, and custom reports.

Data sources:
  - MutationTracker: hash chain, mutation history
  - AuditTrail: append-only audit log
  - ConscienceMonitor: drift, Tamas, temporal, escalation
  - UserBehaviorTracker: adversarial user detection

Report output: JSON, Markdown, PDF (stub).

EU AI Act: conformity assessments require audit trails, risk analysis,
and documentation of system behavior — this module generates them.
"""
import json
import hashlib
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional, List, Dict, Any

logger = logging.getLogger(__name__)


# ─── Report Types ──────────────────────────────────────────────────


class ReportType(str, Enum):
    """Supported compliance report types."""
    EU_AI_ACT = "eu_ai_act"
    SOC2 = "soc2"
    HIPAA = "hipaa"
    CUSTOM = "custom"


class ReportFormat(str, Enum):
    """Output formats for reports."""
    JSON = "json"
    MARKDOWN = "markdown"
    PDF = "pdf"  # Stub — returns JSON with pdf_placeholder flag


class RiskLevel(str, Enum):
    """Overall risk level for the compliance report."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# ─── Report Sections ──────────────────────────────────────────────


@dataclass
class ExecutiveSummary:
    """High-level system overview and risk assessment."""
    system_name: str = "RTA-GUARD"
    system_version: str = "0.1.0"
    report_period_start: str = ""
    report_period_end: str = ""
    total_violations: int = 0
    total_mutations: int = 0
    total_audit_entries: int = 0
    agents_monitored: int = 0
    users_tracked: int = 0
    overall_risk_level: str = RiskLevel.LOW.value
    risk_rationale: str = ""
    hash_chain_valid: bool = True
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ViolationEntry:
    """A single rule violation with context."""
    violation_id: str = ""
    timestamp: str = ""
    rule_id: str = ""
    rule_name: str = ""
    severity: str = "medium"
    agent_id: str = ""
    session_id: str = ""
    description: str = ""
    action_taken: str = ""
    resolved: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ViolationsSection:
    """Aggregated violation log."""
    total_violations: int = 0
    by_severity: Dict[str, int] = field(default_factory=dict)
    by_rule: Dict[str, int] = field(default_factory=dict)
    by_agent: Dict[str, int] = field(default_factory=dict)
    entries: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DriftComponentSummary:
    """Summary of a single drift component."""
    name: str = ""
    average: float = 0.0
    max_value: float = 0.0
    trend: str = "stable"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class DriftAnalysisSection:
    """Drift trends and anomaly analysis."""
    agents_with_drift: int = 0
    agents_critical: int = 0
    agents_unhealthy: int = 0
    agents_degraded: int = 0
    agents_healthy: int = 0
    overall_drift_trend: str = "stable"
    components: List[Dict[str, Any]] = field(default_factory=list)
    anomalies_detected: int = 0
    anomaly_details: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TamasEventEntry:
    """A single Tamas state transition."""
    event_id: str = ""
    agent_id: str = ""
    timestamp: str = ""
    previous_state: str = ""
    new_state: str = ""
    trigger_reasons: List[str] = field(default_factory=list)
    escalation_action: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TamasSection:
    """Tamas (degraded state) events and analysis."""
    total_events: int = 0
    agents_in_tamas: int = 0
    agents_in_critical: int = 0
    escalation_actions: Dict[str, int] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AuditTrailSection:
    """Audit trail integrity and statistics."""
    total_entries: int = 0
    hash_chain_valid: bool = True
    chain_verification_error: Optional[str] = None
    entries_by_action: Dict[str, int] = field(default_factory=dict)
    first_entry_time: Optional[str] = None
    last_entry_time: Optional[str] = None
    mutation_count: int = 0
    mutation_types: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class UserRiskEntry:
    """Risk assessment for a single user."""
    user_id: str = ""
    risk_score: float = 0.0
    risk_level: str = "low"
    is_adversarial: bool = False
    anomaly_signals: int = 0
    categories: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class UserRiskSection:
    """User risk analysis across all tracked users."""
    total_users: int = 0
    adversarial_users: int = 0
    high_risk_users: int = 0
    users: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Recommendation:
    """An automated recommendation based on data patterns."""
    priority: str = "medium"  # low, medium, high, critical
    category: str = ""
    title: str = ""
    description: str = ""
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RecommendationsSection:
    """Automated recommendations based on data analysis."""
    total_recommendations: int = 0
    by_priority: Dict[str, int] = field(default_factory=dict)
    recommendations: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ─── Compliance Report ────────────────────────────────────────────


@dataclass
class ComplianceReport:
    """
    Structured compliance report with all sections.

    Deterministic: same input data always produces the same report
    (timestamps are taken from data, not generation time, except
    generated_at which is set once at creation).
    """
    report_id: str = ""
    report_type: str = ReportType.EU_AI_ACT.value
    title: str = ""
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    report_hash: str = ""

    # Sections
    executive_summary: Dict[str, Any] = field(default_factory=dict)
    violations: Dict[str, Any] = field(default_factory=dict)
    drift_analysis: Dict[str, Any] = field(default_factory=dict)
    tamas_events: Dict[str, Any] = field(default_factory=dict)
    audit_trail: Dict[str, Any] = field(default_factory=dict)
    user_risk: Dict[str, Any] = field(default_factory=dict)
    recommendations: Dict[str, Any] = field(default_factory=dict)

    # Custom fields (for CUSTOM report type)
    custom_fields: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.report_id:
            self.report_id = f"rpt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{hashlib.sha256(self.generated_at.encode()).hexdigest()[:8]}"
        if not self.report_hash:
            self.report_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        """Compute deterministic hash of the report content (excluding report_hash itself)."""
        content = json.dumps({
            "report_id": self.report_id,
            "report_type": self.report_type,
            "title": self.title,
            "generated_at": self.generated_at,
            "executive_summary": self.executive_summary,
            "violations": self.violations,
            "drift_analysis": self.drift_analysis,
            "tamas_events": self.tamas_events,
            "audit_trail": self.audit_trail,
            "user_risk": self.user_risk,
            "recommendations": self.recommendations,
            "custom_fields": self.custom_fields,
        }, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()

    def to_dict(self) -> dict:
        return {
            "report_id": self.report_id,
            "report_type": self.report_type,
            "title": self.title,
            "generated_at": self.generated_at,
            "report_hash": self.report_hash,
            "executive_summary": self.executive_summary,
            "violations": self.violations,
            "drift_analysis": self.drift_analysis,
            "tamas_events": self.tamas_events,
            "audit_trail": self.audit_trail,
            "user_risk": self.user_risk,
            "recommendations": self.recommendations,
            "custom_fields": self.custom_fields,
        }

    def to_json(self, indent: int = 2) -> str:
        """Export as JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def to_markdown(self) -> str:
        """Export as Markdown document."""
        lines = []
        lines.append(f"# {self.title}")
        lines.append(f"")
        lines.append(f"**Report ID:** {self.report_id}")
        lines.append(f"**Report Type:** {self.report_type}")
        lines.append(f"**Generated:** {self.generated_at}")
        lines.append(f"**Report Hash:** `{self.report_hash}`")
        lines.append("")

        # Executive Summary
        es = self.executive_summary
        lines.append("## Executive Summary")
        lines.append("")
        lines.append(f"- **System:** {es.get('system_name', 'N/A')} v{es.get('system_version', 'N/A')}")
        lines.append(f"- **Period:** {es.get('report_period_start', 'N/A')} to {es.get('report_period_end', 'N/A')}")
        lines.append(f"- **Overall Risk Level:** {es.get('overall_risk_level', 'N/A').upper()}")
        lines.append(f"- **Total Violations:** {es.get('total_violations', 0)}")
        lines.append(f"- **Total Mutations:** {es.get('total_mutations', 0)}")
        lines.append(f"- **Total Audit Entries:** {es.get('total_audit_entries', 0)}")
        lines.append(f"- **Agents Monitored:** {es.get('agents_monitored', 0)}")
        lines.append(f"- **Users Tracked:** {es.get('users_tracked', 0)}")
        lines.append(f"- **Hash Chain Valid:** {'✅ Yes' if es.get('hash_chain_valid') else '❌ No'}")
        if es.get('risk_rationale'):
            lines.append(f"- **Risk Rationale:** {es['risk_rationale']}")
        lines.append("")

        # Violations
        viol = self.violations
        lines.append("## Rule Violations Log")
        lines.append("")
        lines.append(f"**Total Violations:** {viol.get('total_violations', 0)}")
        lines.append("")
        if viol.get('by_severity'):
            lines.append("### By Severity")
            for sev, count in sorted(viol['by_severity'].items()):
                lines.append(f"- **{sev}:** {count}")
            lines.append("")
        if viol.get('by_rule'):
            lines.append("### By Rule")
            for rule, count in sorted(viol['by_rule'].items(), key=lambda x: -x[1]):
                lines.append(f"- **{rule}:** {count}")
            lines.append("")
        if viol.get('entries'):
            lines.append("### Recent Violations")
            for entry in viol['entries'][:20]:
                lines.append(f"- [{entry.get('timestamp', 'N/A')}] **{entry.get('rule_id', 'N/A')}** "
                           f"(severity: {entry.get('severity', 'N/A')}): {entry.get('description', 'N/A')}")
            lines.append("")

        # Drift Analysis
        drift = self.drift_analysis
        lines.append("## Drift Analysis")
        lines.append("")
        lines.append(f"- **Agents with Drift Data:** {drift.get('agents_with_drift', 0)}")
        lines.append(f"- **Critical:** {drift.get('agents_critical', 0)}")
        lines.append(f"- **Unhealthy:** {drift.get('agents_unhealthy', 0)}")
        lines.append(f"- **Degraded:** {drift.get('agents_degraded', 0)}")
        lines.append(f"- **Healthy:** {drift.get('agents_healthy', 0)}")
        lines.append(f"- **Overall Trend:** {drift.get('overall_drift_trend', 'N/A')}")
        lines.append(f"- **Anomalies Detected:** {drift.get('anomalies_detected', 0)}")
        lines.append("")
        if drift.get('components'):
            lines.append("### Drift Components")
            for comp in drift['components']:
                lines.append(f"- **{comp.get('name', 'N/A')}:** avg={comp.get('average', 0):.4f}, "
                           f"max={comp.get('max_value', 0):.4f}, trend={comp.get('trend', 'N/A')}")
            lines.append("")

        # Tamas Events
        tamas = self.tamas_events
        lines.append("## Tamas Events")
        lines.append("")
        lines.append(f"- **Total Events:** {tamas.get('total_events', 0)}")
        lines.append(f"- **Agents in Tamas:** {tamas.get('agents_in_tamas', 0)}")
        lines.append(f"- **Agents in Critical:** {tamas.get('agents_in_critical', 0)}")
        if tamas.get('escalation_actions'):
            lines.append("### Escalation Actions")
            for action, count in sorted(tamas['escalation_actions'].items()):
                lines.append(f"- **{action}:** {count}")
        lines.append("")

        # Audit Trail
        audit = self.audit_trail
        lines.append("## Audit Trail Summary")
        lines.append("")
        lines.append(f"- **Total Entries:** {audit.get('total_entries', 0)}")
        lines.append(f"- **Hash Chain Valid:** {'✅ Yes' if audit.get('hash_chain_valid') else '❌ No'}")
        lines.append(f"- **Mutation Count:** {audit.get('mutation_count', 0)}")
        if audit.get('entries_by_action'):
            lines.append("### Entries by Action")
            for action, count in sorted(audit['entries_by_action'].items()):
                lines.append(f"- **{action}:** {count}")
        lines.append("")

        # User Risk
        ur = self.user_risk
        lines.append("## User Risk Analysis")
        lines.append("")
        lines.append(f"- **Total Users:** {ur.get('total_users', 0)}")
        lines.append(f"- **Adversarial Users:** {ur.get('adversarial_users', 0)}")
        lines.append(f"- **High Risk Users:** {ur.get('high_risk_users', 0)}")
        if ur.get('users'):
            lines.append("### User Details")
            for u in ur['users'][:20]:
                adv = "⚠️ ADVERSARIAL" if u.get('is_adversarial') else "✅"
                lines.append(f"- **{u.get('user_id', 'N/A')}** {adv} — risk: {u.get('risk_score', 0):.2f} ({u.get('risk_level', 'N/A')})")
            lines.append("")

        # Recommendations
        recs = self.recommendations
        lines.append("## Recommendations")
        lines.append("")
        if recs.get('recommendations'):
            for rec in recs['recommendations']:
                lines.append(f"### [{rec.get('priority', 'N/A').upper()}] {rec.get('title', 'N/A')}")
                lines.append(f"")
                lines.append(f"**Category:** {rec.get('category', 'N/A')}")
                lines.append(f"")
                lines.append(f"{rec.get('description', 'N/A')}")
                if rec.get('evidence'):
                    lines.append(f"")
                    lines.append(f"**Evidence:**")
                    for ev in rec['evidence']:
                        lines.append(f"- {ev}")
                lines.append("")
        else:
            lines.append("No recommendations at this time.")
            lines.append("")

        # Custom fields
        if self.custom_fields:
            lines.append("## Custom Fields")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(self.custom_fields, indent=2, default=str))
            lines.append("```")
            lines.append("")

        return "\n".join(lines)


# ─── Report Generator ─────────────────────────────────────────────


class ReportGenerator:
    """
    Generates compliance reports from RTA-GUARD subsystem data.

    Aggregates data from MutationTracker, AuditTrail, ConscienceMonitor,
    and UserBehaviorTracker into structured compliance reports.

    Supports EU AI Act, SOC2, HIPAA, and custom report types.

    Usage:
        gen = ReportGenerator(
            mutation_tracker=tracker,
            audit_trail=trail,
            conscience_monitor=monitor,
            user_tracker=tracker,
        )
        report = gen.generate(ReportType.EU_AI_ACT)
        json_str = report.to_json()
        md_str = report.to_markdown()
    """

    def __init__(
        self,
        mutation_tracker: Any = None,
        audit_trail: Any = None,
        conscience_monitor: Any = None,
        user_tracker: Any = None,
        attribution_manager: Any = None,
    ):
        """
        Args:
            mutation_tracker: MutationTracker instance (optional).
            audit_trail: AuditTrail instance (optional). If not provided,
                         extracted from attribution_manager.audit.
            conscience_monitor: ConscienceMonitor instance (optional).
            user_tracker: UserBehaviorTracker instance (optional).
            attribution_manager: AttributionManager instance (optional).
        """
        self.mutation_tracker = mutation_tracker
        self.audit_trail = audit_trail
        self.conscience_monitor = conscience_monitor
        self.user_tracker = user_tracker
        self.attribution_manager = attribution_manager

        # Extract audit trail from attribution if not provided directly
        if not self.audit_trail and self.attribution_manager:
            self.audit_trail = self.attribution_manager.audit

    def generate(
        self,
        report_type: ReportType = ReportType.EU_AI_ACT,
        title: Optional[str] = None,
        period_start: Optional[str] = None,
        period_end: Optional[str] = None,
        custom_fields: Optional[Dict[str, Any]] = None,
    ) -> ComplianceReport:
        """
        Generate a compliance report.

        Args:
            report_type: Type of report to generate.
            title: Custom title (auto-generated if not provided).
            period_start: Report period start (ISO timestamp).
            period_end: Report period end (ISO timestamp).
            custom_fields: Additional fields for CUSTOM reports.

        Returns:
            ComplianceReport with all sections populated.
        """
        if title is None:
            title = self._default_title(report_type)

        # Gather all sections
        executive_summary = self._build_executive_summary(report_type, period_start, period_end)
        violations = self._build_violations_section(period_start, period_end)
        drift_analysis = self._build_drift_analysis()
        tamas_events = self._build_tamas_section()
        audit_trail_section = self._build_audit_trail_section()
        user_risk = self._build_user_risk_section()
        recommendations = self._build_recommendations(
            executive_summary, violations, drift_analysis, tamas_events, user_risk
        )

        report = ComplianceReport(
            report_type=report_type.value,
            title=title,
            executive_summary=executive_summary.to_dict(),
            violations=violations.to_dict(),
            drift_analysis=drift_analysis.to_dict(),
            tamas_events=tamas_events.to_dict(),
            audit_trail=audit_trail_section.to_dict(),
            user_risk=user_risk.to_dict(),
            recommendations=recommendations.to_dict(),
            custom_fields=custom_fields or {},
        )

        return report

    def _default_title(self, report_type: ReportType) -> str:
        """Generate default report title."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        titles = {
            ReportType.EU_AI_ACT: f"EU AI Act Conformity Assessment — RTA-GUARD ({now})",
            ReportType.SOC2: f"SOC2 Audit Report — RTA-GUARD ({now})",
            ReportType.HIPAA: f"HIPAA Compliance Report — RTA-GUARD ({now})",
            ReportType.CUSTOM: f"Custom Compliance Report — RTA-GUARD ({now})",
        }
        return titles.get(report_type, f"Compliance Report — RTA-GUARD ({now})")

    # ── Section Builders ──────────────────────────────────────────

    def _build_executive_summary(
        self,
        report_type: ReportType,
        period_start: Optional[str],
        period_end: Optional[str],
    ) -> ExecutiveSummary:
        """Build executive summary from available data."""
        total_violations = 0
        total_mutations = 0
        total_audit_entries = 0
        agents_monitored = 0
        users_tracked = 0
        hash_chain_valid = True

        # Mutation tracker stats
        if self.mutation_tracker:
            try:
                stats = self.mutation_tracker.get_stats()
                total_mutations = stats.get("total_mutations", 0)
                hash_chain_valid = stats.get("chain_intact", True)
            except Exception as e:
                logger.warning(f"Failed to get mutation stats: {e}")

        # Audit trail stats
        if self.audit_trail:
            try:
                total_audit_entries = self.audit_trail.count
                chain_valid, _ = self.audit_trail.verify_chain()
                hash_chain_valid = hash_chain_valid and chain_valid
            except Exception as e:
                logger.warning(f"Failed to get audit trail stats: {e}")

        # Conscience monitor stats
        if self.conscience_monitor:
            try:
                agents = self.conscience_monitor.list_agents()
                agents_monitored = len(agents)
                for agent in agents:
                    total_violations += agent.get("violation_count", 0)
                users = self.conscience_monitor.list_users()
                users_tracked = len(users)
            except Exception as e:
                logger.warning(f"Failed to get conscience stats: {e}")

        # Determine risk level
        risk_level, risk_rationale = self._assess_risk(
            total_violations, hash_chain_valid, agents_monitored
        )

        return ExecutiveSummary(
            report_period_start=period_start or "",
            report_period_end=period_end or "",
            total_violations=total_violations,
            total_mutations=total_mutations,
            total_audit_entries=total_audit_entries,
            agents_monitored=agents_monitored,
            users_tracked=users_tracked,
            overall_risk_level=risk_level.value,
            risk_rationale=risk_rationale,
            hash_chain_valid=hash_chain_valid,
        )

    def _assess_risk(
        self,
        total_violations: int,
        hash_chain_valid: bool,
        agents_monitored: int,
    ) -> tuple:
        """Assess overall risk level from data patterns."""
        if not hash_chain_valid:
            return RiskLevel.CRITICAL, "Hash chain integrity compromised — possible tampering detected"

        if total_violations == 0:
            return RiskLevel.LOW, "No violations detected, hash chain intact"

        if agents_monitored > 0:
            violation_rate = total_violations / max(agents_monitored, 1)
            if violation_rate > 10:
                return RiskLevel.HIGH, f"High violation rate: {violation_rate:.1f} violations per agent"
            elif violation_rate > 3:
                return RiskLevel.MEDIUM, f"Moderate violation rate: {violation_rate:.1f} violations per agent"

        if total_violations > 50:
            return RiskLevel.MEDIUM, f"{total_violations} total violations detected"

        return RiskLevel.LOW, f"{total_violations} violations within acceptable range"

    def _build_violations_section(
        self,
        period_start: Optional[str],
        period_end: Optional[str],
    ) -> ViolationsSection:
        """Build violations log from conscience monitor data."""
        if not self.conscience_monitor:
            return ViolationsSection()

        by_severity: Dict[str, int] = {}
        by_rule: Dict[str, int] = {}
        by_agent: Dict[str, int] = {}
        entries: List[Dict[str, Any]] = []

        try:
            agents = self.conscience_monitor.list_agents()
            for agent in agents:
                agent_id = agent.get("agent_id", "")
                v_count = agent.get("violation_count", 0)
                if v_count > 0:
                    by_agent[agent_id] = v_count

                # Get violation types from agent profile
                v_types = agent.get("violation_types", {})
                for vtype, count in v_types.items():
                    by_rule[vtype] = by_rule.get(vtype, 0) + count
                    by_severity["medium"] = by_severity.get("medium", 0) + count

                # Build entries from violation history if available
                v_history = agent.get("violation_history", [])
                for vh in v_history:
                    entry = ViolationEntry(
                        violation_id=vh.get("id", ""),
                        timestamp=vh.get("timestamp", ""),
                        rule_id=vh.get("rule_id", vh.get("type", "")),
                        rule_name=vh.get("rule_name", vh.get("type", "")),
                        severity=vh.get("severity", "medium"),
                        agent_id=agent_id,
                        description=vh.get("description", vh.get("detail", "")),
                        action_taken=vh.get("action", ""),
                    )
                    entries.append(entry.to_dict())

            # Sort entries by timestamp descending
            entries.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

        except Exception as e:
            logger.warning(f"Failed to build violations section: {e}")

        total = sum(by_agent.values())
        return ViolationsSection(
            total_violations=total,
            by_severity=by_severity,
            by_rule=by_rule,
            by_agent=by_agent,
            entries=entries,
        )

    def _build_drift_analysis(self) -> DriftAnalysisSection:
        """Build drift analysis from conscience monitor."""
        if not self.conscience_monitor:
            return DriftAnalysisSection()

        try:
            agents = self.conscience_monitor.list_agents()

            critical = 0
            unhealthy = 0
            degraded = 0
            healthy = 0
            anomalies = 0
            anomaly_details: List[Dict[str, Any]] = []
            component_accum: Dict[str, List[float]] = {}

            for agent in agents:
                agent_id = agent.get("agent_id", "")
                drift_level = agent.get("live_drift_level", agent.get("drift_level", "healthy"))

                if drift_level == "critical":
                    critical += 1
                elif drift_level == "unhealthy":
                    unhealthy += 1
                elif drift_level == "degraded":
                    degraded += 1
                else:
                    healthy += 1

                # Check for anomalies
                is_anomalous, anomaly_type, detail = False, "none", ""
                try:
                    is_anomalous, anomaly_type, detail = self.conscience_monitor.detect_anomaly(agent_id)
                except Exception:
                    pass

                if is_anomalous:
                    anomalies += 1
                    anomaly_details.append({
                        "agent_id": agent_id,
                        "anomaly_type": anomaly_type.value if hasattr(anomaly_type, 'value') else str(anomaly_type),
                        "detail": detail,
                    })

                # Accumulate drift components
                drift_comps = agent.get("drift_components", {})
                for comp_name, comp_val in drift_comps.items():
                    if comp_name not in component_accum:
                        component_accum[comp_name] = []
                    component_accum[comp_name].append(float(comp_val))

            # Build component summaries
            components = []
            for comp_name, values in component_accum.items():
                avg_val = sum(values) / len(values) if values else 0.0
                max_val = max(values) if values else 0.0
                components.append(DriftComponentSummary(
                    name=comp_name,
                    average=round(avg_val, 4),
                    max_value=round(max_val, 4),
                ).to_dict())

            # Overall trend
            total_with_data = critical + unhealthy + degraded + healthy
            if critical > 0:
                overall_trend = "critical"
            elif unhealthy > total_with_data * 0.3:
                overall_trend = "deteriorating"
            elif degraded > total_with_data * 0.5:
                overall_trend = "degrading"
            else:
                overall_trend = "stable"

            with_drift = unhealthy + degraded + critical

            return DriftAnalysisSection(
                agents_with_drift=with_drift,
                agents_critical=critical,
                agents_unhealthy=unhealthy,
                agents_degraded=degraded,
                agents_healthy=healthy,
                overall_drift_trend=overall_trend,
                components=components,
                anomalies_detected=anomalies,
                anomaly_details=anomaly_details,
            )

        except Exception as e:
            logger.warning(f"Failed to build drift analysis: {e}")
            return DriftAnalysisSection()

    def _build_tamas_section(self) -> TamasSection:
        """Build Tamas events section from conscience monitor."""
        if not self.conscience_monitor:
            return TamasSection()

        try:
            agents = self.conscience_monitor.list_agents()

            total_events = 0
            agents_in_tamas = 0
            agents_in_critical = 0
            escalation_actions: Dict[str, int] = {}
            all_events: List[Dict[str, Any]] = []

            for agent in agents:
                agent_id = agent.get("agent_id", "")

                # Get Tamas state
                tamas_summary = self.conscience_monitor.get_tamas_state(agent_id)
                current_state = tamas_summary.get("current_state", "sattva")

                if current_state == "tamas":
                    agents_in_tamas += 1
                elif current_state == "critical":
                    agents_in_critical += 1

                # Get Tamas history
                history = self.conscience_monitor.get_tamas_history(agent_id)
                total_events += len(history)

                for event in history:
                    entry = TamasEventEntry(
                        event_id=event.get("event_id", ""),
                        agent_id=agent_id,
                        timestamp=event.get("timestamp", ""),
                        previous_state=event.get("previous_state", ""),
                        new_state=event.get("new_state", ""),
                        trigger_reasons=event.get("trigger_reasons", []),
                        escalation_action=event.get("escalation", ""),
                    )
                    all_events.append(entry.to_dict())

                    esc = event.get("escalation", "none")
                    if esc and esc != "none":
                        escalation_actions[esc] = escalation_actions.get(esc, 0) + 1

            # Sort events by timestamp
            all_events.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

            return TamasSection(
                total_events=total_events,
                agents_in_tamas=agents_in_tamas,
                agents_in_critical=agents_in_critical,
                escalation_actions=escalation_actions,
                events=all_events,
            )

        except Exception as e:
            logger.warning(f"Failed to build Tamas section: {e}")
            return TamasSection()

    def _build_audit_trail_section(self) -> AuditTrailSection:
        """Build audit trail summary."""
        total_entries = 0
        chain_valid = True
        chain_error = None
        entries_by_action: Dict[str, int] = {}
        first_entry = None
        last_entry = None
        mutation_count = 0
        mutation_types: Dict[str, int] = {}

        # Audit trail
        if self.audit_trail:
            try:
                total_entries = self.audit_trail.count
                chain_valid, chain_error = self.audit_trail.verify_chain()

                # Get all entries for stats
                all_entries = self.audit_trail.get_entries(limit=10000)
                for entry in all_entries:
                    action = entry.action.value if hasattr(entry.action, 'value') else str(entry.action)
                    entries_by_action[action] = entries_by_action.get(action, 0) + 1

                if all_entries:
                    # Entries sorted desc, so last = first chronological
                    last_entry = all_entries[0].timestamp
                    first_entry = all_entries[-1].timestamp
            except Exception as e:
                logger.warning(f"Failed to get audit trail data: {e}")

        # Mutation tracker
        if self.mutation_tracker:
            try:
                stats = self.mutation_tracker.get_stats()
                mutation_count = stats.get("total_mutations", 0)
                mutation_types = stats.get("mutation_types", {})
            except Exception as e:
                logger.warning(f"Failed to get mutation stats: {e}")

        return AuditTrailSection(
            total_entries=total_entries,
            hash_chain_valid=chain_valid,
            chain_verification_error=chain_error,
            entries_by_action=entries_by_action,
            first_entry_time=first_entry,
            last_entry_time=last_entry,
            mutation_count=mutation_count,
            mutation_types=mutation_types,
        )

    def _build_user_risk_section(self) -> UserRiskSection:
        """Build user risk analysis section."""
        if not self.user_tracker:
            return UserRiskSection()

        try:
            users_data = self.user_tracker.list_users()
            user_entries: List[Dict[str, Any]] = []
            adversarial_count = 0
            high_risk_count = 0

            for u in users_data:
                user_id = u.get("user_id", "")
                risk_score = u.get("risk_score", 0.0)
                is_adv = u.get("is_adversarial", False)

                if is_adv:
                    adversarial_count += 1
                if risk_score >= 0.6:
                    high_risk_count += 1

                risk_level = "low"
                if risk_score >= 0.85:
                    risk_level = "critical"
                elif risk_score >= 0.6:
                    risk_level = "high"
                elif risk_score >= 0.3:
                    risk_level = "moderate"

                # Get signals
                signals = []
                categories = []
                try:
                    signal_list = self.user_tracker.analyze_behavior(user_id)
                    signals = signal_list if isinstance(signal_list, list) else []
                    categories = list(set(
                        s.category.value if hasattr(s.category, 'value') else str(s.category)
                        for s in signals
                    )) if signals else []
                except Exception:
                    pass

                entry = UserRiskEntry(
                    user_id=user_id,
                    risk_score=round(risk_score, 4),
                    risk_level=risk_level,
                    is_adversarial=is_adv,
                    anomaly_signals=len(signals),
                    categories=categories,
                )
                user_entries.append(entry.to_dict())

            # Sort by risk score descending
            user_entries.sort(key=lambda u: u.get("risk_score", 0), reverse=True)

            return UserRiskSection(
                total_users=len(users_data),
                adversarial_users=adversarial_count,
                high_risk_users=high_risk_count,
                users=user_entries,
            )

        except Exception as e:
            logger.warning(f"Failed to build user risk section: {e}")
            return UserRiskSection()

    def _build_recommendations(
        self,
        summary: ExecutiveSummary,
        violations: ViolationsSection,
        drift: DriftAnalysisSection,
        tamas: TamasSection,
        user_risk: UserRiskSection,
    ) -> RecommendationsSection:
        """Generate automated recommendations based on data patterns."""
        recs: List[Recommendation] = []

        # Hash chain integrity
        if not summary.hash_chain_valid:
            recs.append(Recommendation(
                priority="critical",
                category="integrity",
                title="Hash Chain Integrity Compromised",
                description="The audit trail or mutation hash chain has failed verification. "
                           "This may indicate data tampering. Immediately investigate and restore "
                           "from a known-good backup.",
                evidence=["Hash chain verification returned invalid"],
            ))

        # High violation rate
        if violations.total_violations > 20:
            recs.append(Recommendation(
                priority="high",
                category="violations",
                title="Elevated Violation Count",
                description=f"System recorded {violations.total_violations} violations. "
                           "Review violation rules and consider tightening thresholds or "
                           "adding additional guardrails.",
                evidence=[f"Total violations: {violations.total_violations}"],
            ))

        # Drift alerts
        if drift.agents_critical > 0:
            recs.append(Recommendation(
                priority="critical",
                category="drift",
                title="Agents in Critical Drift State",
                description=f"{drift.agents_critical} agent(s) are in critical drift state. "
                           "Consider suspending these agents and reviewing their recent behavior.",
                evidence=[f"Critical agents: {drift.agents_critical}"],
            ))
        elif drift.agents_unhealthy > 0:
            recs.append(Recommendation(
                priority="high",
                category="drift",
                title="Agents in Unhealthy Drift State",
                description=f"{drift.agents_unhealthy} agent(s) show unhealthy drift levels. "
                           "Monitor closely and consider throttling their output.",
                evidence=[f"Unhealthy agents: {drift.agents_unhealthy}"],
            ))

        # Tamas alerts
        if tamas.agents_in_critical > 0:
            recs.append(Recommendation(
                priority="critical",
                category="tamas",
                title="Agents in Critical Tamas State",
                description=f"{tamas.agents_in_critical} agent(s) are in critical Tamas state. "
                           "Auto-kill protocols should have been triggered. Verify kill switches engaged.",
                evidence=[f"Critical Tamas agents: {tamas.agents_in_critical}"],
            ))
        elif tamas.agents_in_tamas > 0:
            recs.append(Recommendation(
                priority="high",
                category="tamas",
                title="Agents in Tamas State",
                description=f"{tamas.agents_in_tamas} agent(s) are in degraded Tamas state. "
                           "Human operator review recommended.",
                evidence=[f"Tamas agents: {tamas.agents_in_tamas}"],
            ))

        # Adversarial users
        if user_risk.adversarial_users > 0:
            recs.append(Recommendation(
                priority="high",
                category="user_risk",
                title="Adversarial Users Detected",
                description=f"{user_risk.adversarial_users} user(s) flagged as adversarial. "
                           "Review their activity logs and consider rate limiting or blocking.",
                evidence=[f"Adversarial users: {user_risk.adversarial_users}"],
            ))

        # Anomalies
        if drift.anomalies_detected > 0:
            recs.append(Recommendation(
                priority="medium",
                category="anomaly",
                title="Behavioral Anomalies Detected",
                description=f"{drift.anomalies_detected} agent(s) show anomalous behavior patterns. "
                           "Review anomaly details and compare against baseline.",
                evidence=[f"Anomalies: {drift.anomalies_detected}"],
            ))

        # Overall drift trend
        if drift.overall_drift_trend in ("deteriorating", "critical"):
            recs.append(Recommendation(
                priority="high",
                category="drift",
                title="System-Wide Drift Trend Deteriorating",
                description="Overall system drift is trending upward. Consider reviewing "
                           "agent configurations and retraining models.",
                evidence=[f"Overall trend: {drift.overall_drift_trend}"],
            ))

        # Default: all clear
        if not recs:
            recs.append(Recommendation(
                priority="low",
                category="status",
                title="System Operating Normally",
                description="All monitored systems are within acceptable parameters. "
                           "No immediate action required.",
                evidence=["No critical issues detected"],
            ))

        # Sort by priority
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        recs.sort(key=lambda r: priority_order.get(r.priority, 99))

        by_priority: Dict[str, int] = {}
        for r in recs:
            by_priority[r.priority] = by_priority.get(r.priority, 0) + 1

        return RecommendationsSection(
            total_recommendations=len(recs),
            by_priority=by_priority,
            recommendations=[r.to_dict() for r in recs],
        )


# ─── Convenience ──────────────────────────────────────────────────


def generate_report(
    report_type: ReportType = ReportType.EU_AI_ACT,
    mutation_tracker: Any = None,
    audit_trail: Any = None,
    conscience_monitor: Any = None,
    user_tracker: Any = None,
    attribution_manager: Any = None,
    output_format: ReportFormat = ReportFormat.JSON,
    title: Optional[str] = None,
    custom_fields: Optional[Dict[str, Any]] = None,
) -> str:
    """
    One-shot report generation convenience function.

    Args:
        report_type: Type of report.
        mutation_tracker: MutationTracker instance.
        audit_trail: AuditTrail instance.
        conscience_monitor: ConscienceMonitor instance.
        user_tracker: UserBehaviorTracker instance.
        attribution_manager: AttributionManager instance.
        output_format: Output format (json/markdown/pdf).
        title: Custom title.
        custom_fields: Extra fields for CUSTOM reports.

    Returns:
        Report as string in the requested format.
    """
    gen = ReportGenerator(
        mutation_tracker=mutation_tracker,
        audit_trail=audit_trail,
        conscience_monitor=conscience_monitor,
        user_tracker=user_tracker,
        attribution_manager=attribution_manager,
    )

    report = gen.generate(
        report_type=report_type,
        title=title,
        custom_fields=custom_fields,
    )

    if output_format == ReportFormat.MARKDOWN:
        return report.to_markdown()
    elif output_format == ReportFormat.PDF:
        # PDF stub — return JSON with placeholder flag
        data = report.to_dict()
        data["pdf_placeholder"] = True
        data["pdf_note"] = "PDF generation requires weasyprint or reportlab. Install and re-run."
        return json.dumps(data, indent=2, default=str)
    else:
        return report.to_json()
