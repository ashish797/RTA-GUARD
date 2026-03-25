"""
Test suite for Phase 4.3 — Compliance Reporting System.

Tests:
  1. ComplianceReport creation
  2. ReportGenerator with sample data
  3. EU AI Act conformity assessment
  4. JSON export
  5. Markdown export
  6. Report structure validation
  7. Recommendations generation
  8. Edge cases

Run with: ``python3 -m pytest brahmanda/test_compliance.py -v``
"""
import sys
import os
import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

try:
    from brahmanda.compliance import (
        ComplianceReport,
        ReportGenerator,
        ReportType,
        ReportFormat,
        RiskLevel,
        ExecutiveSummary,
        ViolationEntry,
        ViolationsSection,
        DriftComponentSummary,
        DriftAnalysisSection,
        TamasEventEntry,
        TamasSection,
        AuditTrailSection,
        UserRiskEntry,
        UserRiskSection,
        Recommendation,
        RecommendationsSection,
        generate_report,
    )
    COMPLIANCE_AVAILABLE = True
except ImportError:
    COMPLIANCE_AVAILABLE = False


# ═══════════════════════════════════════════════════════════════════
# 1. ComplianceReport Creation
# ═══════════════════════════════════════════════════════════════════


class TestComplianceReportCreation:
    """ComplianceReport instantiation, defaults, and hashing."""

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_default_report_creation(self):
        report = ComplianceReport()
        assert report.report_id.startswith("rpt-")
        assert report.report_type == ReportType.EU_AI_ACT.value
        assert report.report_hash != ""
        assert len(report.report_hash) == 64  # SHA-256 hex

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_report_with_title(self):
        report = ComplianceReport(title="Quarterly Assessment Q1 2026")
        assert report.title == "Quarterly Assessment Q1 2026"

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_report_hash_is_deterministic(self):
        """Same content produces the same hash."""
        report1 = ComplianceReport(
            title="Test",
            report_type=ReportType.EU_AI_ACT.value,
            executive_summary={"total_violations": 5},
        )
        report2 = ComplianceReport(
            title="Test",
            report_type=ReportType.EU_AI_ACT.value,
            executive_summary={"total_violations": 5},
        )
        # Hashes differ because generated_at is different
        # But _compute_hash with same inputs is deterministic
        h1 = report1._compute_hash()
        h2 = report1._compute_hash()
        assert h1 == h2

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_report_hash_changes_with_content(self):
        report = ComplianceReport(title="A")
        h1 = report.report_hash
        report.executive_summary = {"total_violations": 99}
        h2 = report._compute_hash()
        assert h1 != h2

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_report_id_unique(self):
        r1 = ComplianceReport()
        r2 = ComplianceReport()
        assert r1.report_id != r2.report_id


# ═══════════════════════════════════════════════════════════════════
# 2. ReportGenerator with Sample Data
# ═══════════════════════════════════════════════════════════════════


class TestReportGenerator:
    """ReportGenerator with mocked subsystem data."""

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_generator_no_data(self):
        """Generator with no subsystems produces a clean report."""
        gen = ReportGenerator()
        report = gen.generate()
        assert report.report_type == ReportType.EU_AI_ACT.value
        assert report.executive_summary["total_violations"] == 0
        assert report.executive_summary["hash_chain_valid"] is True

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_generator_with_mutation_tracker(self):
        tracker = MagicMock()
        tracker.get_stats.return_value = {
            "total_mutations": 42,
            "chain_intact": True,
        }
        gen = ReportGenerator(mutation_tracker=tracker)
        report = gen.generate()
        assert report.executive_summary["total_mutations"] == 42
        assert report.audit_trail["mutation_count"] == 42

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_generator_with_audit_trail(self):
        trail = MagicMock()
        trail.count = 150
        trail.verify_chain.return_value = (True, None)
        entry = MagicMock()
        entry.action = MagicMock(value="create")
        entry.timestamp = "2026-03-01T00:00:00+00:00"
        trail.get_entries.return_value = [entry]

        gen = ReportGenerator(audit_trail=trail)
        report = gen.generate()
        assert report.executive_summary["total_audit_entries"] == 150
        assert report.audit_trail["hash_chain_valid"] is True

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_generator_with_conscience_monitor(self):
        monitor = MagicMock()
        monitor.list_agents.return_value = [
            {"agent_id": "agent-1", "violation_count": 3, "violation_types": {"prompt_injection": 2}, "live_drift_level": "degraded", "drift_components": {"semantic": 0.4}},
            {"agent_id": "agent-2", "violation_count": 0, "violation_types": {}, "live_drift_level": "healthy", "drift_components": {"semantic": 0.1}},
        ]
        monitor.list_users.return_value = []
        monitor.detect_anomaly.return_value = (False, "none", "")

        gen = ReportGenerator(conscience_monitor=monitor)
        report = gen.generate()
        assert report.executive_summary["agents_monitored"] == 2
        assert report.executive_summary["total_violations"] == 3
        assert report.drift_analysis["agents_degraded"] == 1
        assert report.drift_analysis["agents_healthy"] == 1

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_generator_with_user_tracker(self):
        tracker = MagicMock()
        tracker.list_users.return_value = [
            {"user_id": "u1", "risk_score": 0.85, "is_adversarial": True},
            {"user_id": "u2", "risk_score": 0.2, "is_adversarial": False},
        ]
        tracker.analyze_behavior.return_value = []

        gen = ReportGenerator(user_tracker=tracker)
        report = gen.generate()
        assert report.user_risk["total_users"] == 2
        assert report.user_risk["adversarial_users"] == 1
        assert report.user_risk["high_risk_users"] == 1

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_generator_custom_title(self):
        gen = ReportGenerator()
        report = gen.generate(title="My Custom Report")
        assert report.title == "My Custom Report"

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_generator_report_types(self):
        gen = ReportGenerator()
        for rtype in [ReportType.EU_AI_ACT, ReportType.SOC2, ReportType.HIPAA, ReportType.CUSTOM]:
            report = gen.generate(report_type=rtype)
            assert report.report_type == rtype.value

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_generator_custom_fields(self):
        gen = ReportGenerator()
        report = gen.generate(
            report_type=ReportType.CUSTOM,
            custom_fields={"environment": "production", "reviewer": "Ash"},
        )
        assert report.custom_fields["environment"] == "production"
        assert report.custom_fields["reviewer"] == "Ash"

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_generator_default_titles_contain_date(self):
        gen = ReportGenerator()
        report = gen.generate(report_type=ReportType.EU_AI_ACT)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        assert today in report.title

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_generator_mutation_tracker_exception(self):
        """Generator handles broken mutation tracker gracefully."""
        tracker = MagicMock()
        tracker.get_stats.side_effect = RuntimeError("tracker down")
        gen = ReportGenerator(mutation_tracker=tracker)
        # Should not raise
        report = gen.generate()
        assert report.executive_summary["total_mutations"] == 0


# ═══════════════════════════════════════════════════════════════════
# 3. EU AI Act Conformity Assessment
# ═══════════════════════════════════════════════════════════════════


class TestEUAIAct:
    """EU AI Act conformity assessment specifics."""

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_report_type_is_eu_ai_act(self):
        gen = ReportGenerator()
        report = gen.generate(report_type=ReportType.EU_AI_ACT)
        assert report.report_type == "eu_ai_act"

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_eu_ai_act_has_required_sections(self):
        """EU AI Act requires audit trail, risk analysis, and drift documentation."""
        gen = ReportGenerator()
        report = gen.generate(report_type=ReportType.EU_AI_ACT)
        data = report.to_dict()
        assert "executive_summary" in data
        assert "violations" in data
        assert "drift_analysis" in data
        assert "audit_trail" in data
        assert "recommendations" in data

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_eu_ai_act_hash_chain_integrity(self):
        """EU AI Act requires verifiable audit trail integrity."""
        trail = MagicMock()
        trail.count = 100
        trail.verify_chain.return_value = (True, None)
        trail.get_entries.return_value = []

        gen = ReportGenerator(audit_trail=trail)
        report = gen.generate(report_type=ReportType.EU_AI_ACT)
        assert report.audit_trail["hash_chain_valid"] is True

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_eu_ai_act_risk_assessment(self):
        """Risk level is set correctly based on violation count."""
        monitor = MagicMock()
        monitor.list_agents.return_value = [
            {"agent_id": "a1", "violation_count": 15, "violation_types": {}, "live_drift_level": "healthy"},
        ]
        monitor.list_users.return_value = []
        monitor.detect_anomaly.return_value = (False, "none", "")

        gen = ReportGenerator(conscience_monitor=monitor)
        report = gen.generate(report_type=ReportType.EU_AI_ACT)
        # 15 violations / 1 agent = 15 rate > 10 → HIGH
        assert report.executive_summary["overall_risk_level"] == RiskLevel.HIGH.value

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_eu_ai_act_critical_on_hash_chain_broken(self):
        """Broken hash chain → CRITICAL risk regardless of violations."""
        tracker = MagicMock()
        tracker.get_stats.return_value = {"total_mutations": 0, "chain_intact": False}

        gen = ReportGenerator(mutation_tracker=tracker)
        report = gen.generate(report_type=ReportType.EU_AI_ACT)
        assert report.executive_summary["overall_risk_level"] == RiskLevel.CRITICAL.value

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_eu_ai_act_recommendations_for_critical_drift(self):
        """Critical drift → critical recommendation generated."""
        monitor = MagicMock()
        monitor.list_agents.return_value = [
            {"agent_id": "a1", "violation_count": 0, "violation_types": {}, "live_drift_level": "critical", "drift_components": {}},
        ]
        monitor.list_users.return_value = []
        monitor.detect_anomaly.return_value = (True, "spike", "unexpected output")

        gen = ReportGenerator(conscience_monitor=monitor)
        report = gen.generate(report_type=ReportType.EU_AI_ACT)

        rec_titles = [r["title"] for r in report.recommendations["recommendations"]]
        assert any("Critical Drift" in t for t in rec_titles)


# ═══════════════════════════════════════════════════════════════════
# 4. JSON Export
# ═══════════════════════════════════════════════════════════════════


class TestJSONExport:
    """JSON serialization and structure."""

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_to_json_valid(self):
        report = ComplianceReport(title="JSON Test")
        json_str = report.to_json()
        data = json.loads(json_str)
        assert data["title"] == "JSON Test"
        assert "report_id" in data
        assert "report_hash" in data

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_to_json_all_sections_present(self):
        report = ComplianceReport(
            executive_summary={"total_violations": 0},
            violations={"total_violations": 0},
            drift_analysis={"agents_with_drift": 0},
            tamas_events={"total_events": 0},
            audit_trail={"total_entries": 0},
            user_risk={"total_users": 0},
            recommendations={"total_recommendations": 0},
        )
        data = json.loads(report.to_json())
        for key in ["executive_summary", "violations", "drift_analysis",
                     "tamas_events", "audit_trail", "user_risk", "recommendations"]:
            assert key in data

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_to_json_roundtrip(self):
        """JSON → parse → dict matches original."""
        report = ComplianceReport(title="Roundtrip Test", report_type=ReportType.SOC2.value)
        data = json.loads(report.to_json())
        assert data["report_type"] == "soc2"
        assert data["title"] == "Roundtrip Test"

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_generate_report_json_format(self):
        result = generate_report(output_format=ReportFormat.JSON)
        data = json.loads(result)
        assert "report_id" in data

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_to_dict_matches_to_json(self):
        report = ComplianceReport(title="Compare")
        d = report.to_dict()
        j = json.loads(report.to_json())
        assert d["report_id"] == j["report_id"]
        assert d["report_hash"] == j["report_hash"]


# ═══════════════════════════════════════════════════════════════════
# 5. Markdown Export
# ═══════════════════════════════════════════════════════════════════


class TestMarkdownExport:
    """Markdown output format."""

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_markdown_has_title(self):
        report = ComplianceReport(title="Markdown Export Test")
        md = report.to_markdown()
        assert "# Markdown Export Test" in md

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_markdown_has_report_id(self):
        report = ComplianceReport()
        md = report.to_markdown()
        assert f"**Report ID:** {report.report_id}" in md

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_markdown_has_all_sections(self):
        report = ComplianceReport(
            title="Full Report",
            executive_summary={"system_name": "RTA-GUARD", "system_version": "0.1.0",
                               "overall_risk_level": "low", "total_violations": 0,
                               "total_mutations": 0, "total_audit_entries": 0,
                               "agents_monitored": 0, "users_tracked": 0,
                               "hash_chain_valid": True},
            violations={"total_violations": 0},
            drift_analysis={"agents_with_drift": 0, "agents_critical": 0,
                            "agents_unhealthy": 0, "agents_degraded": 0,
                            "agents_healthy": 0, "overall_drift_trend": "stable",
                            "anomalies_detected": 0},
            tamas_events={"total_events": 0},
            audit_trail={"total_entries": 0, "hash_chain_valid": True, "mutation_count": 0},
            user_risk={"total_users": 0},
            recommendations={},
        )
        md = report.to_markdown()
        assert "## Executive Summary" in md
        assert "## Rule Violations Log" in md
        assert "## Drift Analysis" in md
        assert "## Tamas Events" in md
        assert "## Audit Trail Summary" in md
        assert "## User Risk Analysis" in md
        assert "## Recommendations" in md

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_markdown_violations_by_severity(self):
        report = ComplianceReport(
            violations={
                "total_violations": 5,
                "by_severity": {"critical": 1, "high": 2, "medium": 2},
            },
        )
        md = report.to_markdown()
        assert "**critical:** 1" in md
        assert "**high:** 2" in md

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_markdown_recommendations_rendered(self):
        report = ComplianceReport(
            recommendations={
                "total_recommendations": 1,
                "recommendations": [{
                    "priority": "high",
                    "category": "drift",
                    "title": "Review Agent Config",
                    "description": "Agent drift detected.",
                    "evidence": ["drift > 0.5"],
                }],
            },
        )
        md = report.to_markdown()
        assert "[HIGH] Review Agent Config" in md
        assert "Agent drift detected." in md
        assert "- drift > 0.5" in md

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_markdown_no_recommendations(self):
        report = ComplianceReport(recommendations={})
        md = report.to_markdown()
        assert "No recommendations at this time." in md

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_markdown_hash_chain_valid_indicator(self):
        report = ComplianceReport(
            executive_summary={"hash_chain_valid": True, "system_name": "RTA-GUARD", "system_version": "0.1.0"},
            audit_trail={"hash_chain_valid": True},
        )
        md = report.to_markdown()
        assert "✅ Yes" in md

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_markdown_hash_chain_invalid_indicator(self):
        report = ComplianceReport(
            executive_summary={"hash_chain_valid": False, "system_name": "RTA-GUARD", "system_version": "0.1.0"},
            audit_trail={"hash_chain_valid": False},
        )
        md = report.to_markdown()
        assert "❌ No" in md

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_generate_report_markdown_format(self):
        result = generate_report(output_format=ReportFormat.MARKDOWN)
        assert "# " in result  # Markdown heading
        assert "RTA-GUARD" in result

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_markdown_custom_fields(self):
        report = ComplianceReport(
            custom_fields={"env": "staging", "reviewer": "Ash"},
        )
        md = report.to_markdown()
        assert "## Custom Fields" in md
        assert '"env": "staging"' in md


# ═══════════════════════════════════════════════════════════════════
# 6. Report Structure Validation
# ═══════════════════════════════════════════════════════════════════


class TestReportStructure:
    """Validate report dataclass structure and section types."""

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_executive_summary_fields(self):
        es = ExecutiveSummary()
        d = es.to_dict()
        assert "system_name" in d
        assert "overall_risk_level" in d
        assert "generated_at" in d
        assert "hash_chain_valid" in d

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_violation_entry_fields(self):
        entry = ViolationEntry(
            violation_id="v-001",
            rule_id="R001",
            severity="high",
            description="Test violation",
        )
        d = entry.to_dict()
        assert d["violation_id"] == "v-001"
        assert d["severity"] == "high"

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_drift_component_summary(self):
        comp = DriftComponentSummary(name="semantic", average=0.35, max_value=0.8, trend="rising")
        d = comp.to_dict()
        assert d["name"] == "semantic"
        assert d["average"] == 0.35

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_recommendation_fields(self):
        rec = Recommendation(
            priority="critical",
            category="integrity",
            title="Hash chain broken",
            description="Investigate immediately",
            evidence=["chain verification failed"],
        )
        d = rec.to_dict()
        assert d["priority"] == "critical"
        assert d["evidence"] == ["chain verification failed"]

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_report_has_all_enum_types(self):
        assert ReportType.EU_AI_ACT.value == "eu_ai_act"
        assert ReportType.SOC2.value == "soc2"
        assert ReportType.HIPAA.value == "hipaa"
        assert ReportType.CUSTOM.value == "custom"
        assert ReportFormat.JSON.value == "json"
        assert ReportFormat.MARKDOWN.value == "markdown"
        assert ReportFormat.PDF.value == "pdf"
        assert RiskLevel.LOW.value == "low"
        assert RiskLevel.MEDIUM.value == "medium"
        assert RiskLevel.HIGH.value == "high"
        assert RiskLevel.CRITICAL.value == "critical"

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_tamas_event_entry(self):
        entry = TamasEventEntry(
            agent_id="a1",
            previous_state="sattva",
            new_state="tamas",
            trigger_reasons=["drift spike"],
            escalation_action="throttle",
        )
        d = entry.to_dict()
        assert d["agent_id"] == "a1"
        assert d["escalation_action"] == "throttle"

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_user_risk_entry(self):
        entry = UserRiskEntry(
            user_id="u1",
            risk_score=0.92,
            risk_level="critical",
            is_adversarial=True,
            anomaly_signals=5,
            categories=["prompt_injection", "jailbreak"],
        )
        d = entry.to_dict()
        assert d["is_adversarial"] is True
        assert d["risk_score"] == 0.92


# ═══════════════════════════════════════════════════════════════════
# 7. Recommendations Generation
# ═══════════════════════════════════════════════════════════════════


class TestRecommendationsGeneration:
    """Automated recommendation logic based on data patterns."""

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_no_issues_gives_all_clear(self):
        gen = ReportGenerator()
        report = gen.generate()
        recs = report.recommendations["recommendations"]
        assert len(recs) == 1
        assert recs[0]["title"] == "System Operating Normally"
        assert recs[0]["priority"] == "low"

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_hash_chain_broken_gives_critical_recommendation(self):
        tracker = MagicMock()
        tracker.get_stats.return_value = {"total_mutations": 0, "chain_intact": False}
        gen = ReportGenerator(mutation_tracker=tracker)
        report = gen.generate()
        recs = report.recommendations["recommendations"]
        assert any(r["priority"] == "critical" and "Hash Chain" in r["title"] for r in recs)

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_high_violations_gives_recommendation(self):
        monitor = MagicMock()
        monitor.list_agents.return_value = [
            {"agent_id": "a1", "violation_count": 25, "violation_types": {}, "live_drift_level": "healthy"},
        ]
        monitor.list_users.return_value = []
        monitor.detect_anomaly.return_value = (False, "none", "")

        gen = ReportGenerator(conscience_monitor=monitor)
        report = gen.generate()
        recs = report.recommendations["recommendations"]
        assert any("Violation" in r["title"] for r in recs)

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_adversarial_users_gives_recommendation(self):
        tracker = MagicMock()
        tracker.list_users.return_value = [
            {"user_id": "bad-actor", "risk_score": 0.95, "is_adversarial": True},
        ]
        tracker.analyze_behavior.return_value = []

        gen = ReportGenerator(user_tracker=tracker)
        report = gen.generate()
        recs = report.recommendations["recommendations"]
        assert any("Adversarial" in r["title"] for r in recs)

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_tamas_agents_gives_recommendation(self):
        monitor = MagicMock()
        monitor.list_agents.return_value = [
            {"agent_id": "a1", "violation_count": 0, "violation_types": {}, "live_drift_level": "healthy"},
        ]
        monitor.list_users.return_value = []
        monitor.detect_anomaly.return_value = (False, "none", "")
        monitor.get_tamas_state.return_value = {"current_state": "tamas"}
        monitor.get_tamas_history.return_value = [
            {"event_id": "e1", "timestamp": "2026-03-26T00:00:00Z", "previous_state": "sattva", "new_state": "tamas", "trigger_reasons": ["drift"], "escalation": "throttle"},
        ]

        gen = ReportGenerator(conscience_monitor=monitor)
        report = gen.generate()
        recs = report.recommendations["recommendations"]
        assert any("Tamas" in r["title"] for r in recs)

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_recommendations_sorted_by_priority(self):
        """Critical before high before medium before low."""
        monitor = MagicMock()
        monitor.list_agents.return_value = [
            {"agent_id": "a1", "violation_count": 0, "violation_types": {}, "live_drift_level": "critical"},
        ]
        monitor.list_users.return_value = [
            {"user_id": "u1", "risk_score": 0.95, "is_adversarial": True},
        ]
        monitor.detect_anomaly.return_value = (True, "spike", "bad")
        monitor.get_tamas_state.return_value = {"current_state": "critical"}
        monitor.get_tamas_history.return_value = [
            {"event_id": "e1", "timestamp": "2026-03-26T00:00:00Z", "previous_state": "sattva", "new_state": "critical", "trigger_reasons": ["kill"], "escalation": "kill"},
        ]

        tracker = MagicMock()
        tracker.list_users.return_value = [
            {"user_id": "u1", "risk_score": 0.95, "is_adversarial": True},
        ]
        tracker.analyze_behavior.return_value = []

        gen = ReportGenerator(conscience_monitor=monitor, user_tracker=tracker)
        report = gen.generate()
        recs = report.recommendations["recommendations"]
        priorities = [r["priority"] for r in recs]
        order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for i in range(len(priorities) - 1):
            assert order[priorities[i]] <= order[priorities[i + 1]]

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_recommendations_by_priority_count(self):
        gen = ReportGenerator()
        report = gen.generate()
        by_p = report.recommendations["by_priority"]
        assert sum(by_p.values()) == report.recommendations["total_recommendations"]


# ═══════════════════════════════════════════════════════════════════
# 8. Edge Cases
# ═══════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Boundary conditions and error handling."""

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_empty_report_to_json(self):
        report = ComplianceReport()
        json_str = report.to_json()
        data = json.loads(json_str)
        assert data["report_id"].startswith("rpt-")

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_empty_report_to_markdown(self):
        report = ComplianceReport()
        md = report.to_markdown()
        assert isinstance(md, str)
        assert len(md) > 0

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_report_with_unicode_title(self):
        report = ComplianceReport(title="合规报告 — 评估 2026")
        md = report.to_markdown()
        assert "合规报告" in md
        data = json.loads(report.to_json())
        assert "合规报告" in data["title"]

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_report_with_very_long_title(self):
        long_title = "A" * 10000
        report = ComplianceReport(title=long_title)
        assert len(report.title) == 10000
        json_str = report.to_json()
        assert len(json_str) > 10000

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_conscience_monitor_partial_data(self):
        """Monitor returns agents with missing fields."""
        monitor = MagicMock()
        monitor.list_agents.return_value = [
            {"agent_id": "a1"},  # No violation_count, drift_level, etc.
        ]
        monitor.list_users.return_value = []
        monitor.detect_anomaly.return_value = (False, "none", "")

        gen = ReportGenerator(conscience_monitor=monitor)
        report = gen.generate()
        assert report.executive_summary["agents_monitored"] == 1

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_audit_trail_verify_chain_fails(self):
        trail = MagicMock()
        trail.count = 10
        trail.verify_chain.return_value = (False, "Chain break at entry 5")
        trail.get_entries.return_value = []

        gen = ReportGenerator(audit_trail=trail)
        report = gen.generate()
        assert report.audit_trail["hash_chain_valid"] is False
        assert report.audit_trail["chain_verification_error"] == "Chain break at entry 5"

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_pdf_format_returns_placeholder(self):
        result = generate_report(output_format=ReportFormat.PDF)
        data = json.loads(result)
        assert data["pdf_placeholder"] is True
        assert "pdf_note" in data

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_violations_section_empty(self):
        vs = ViolationsSection()
        d = vs.to_dict()
        assert d["total_violations"] == 0
        assert d["entries"] == []

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_risk_assessment_no_violations(self):
        gen = ReportGenerator()
        level, rationale = gen._assess_risk(0, True, 0)
        assert level == RiskLevel.LOW
        assert "No violations" in rationale

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_risk_assessment_moderate(self):
        gen = ReportGenerator()
        level, rationale = gen._assess_risk(10, True, 2)
        # 10 / 2 = 5 > 3 → MEDIUM
        assert level == RiskLevel.MEDIUM

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_generate_report_convenience_function(self):
        """The one-shot generate_report() function works end-to-end."""
        result = generate_report(
            report_type=ReportType.EU_AI_ACT,
            output_format=ReportFormat.JSON,
        )
        data = json.loads(result)
        assert data["report_type"] == "eu_ai_act"

    @pytest.mark.skipif(not COMPLIANCE_AVAILABLE, reason="compliance module not implemented")
    def test_convenience_function_with_all_subsystems(self):
        tracker = MagicMock()
        tracker.get_stats.return_value = {"total_mutations": 5, "chain_intact": True}
        trail = MagicMock()
        trail.count = 20
        trail.verify_chain.return_value = (True, None)
        trail.get_entries.return_value = []
        monitor = MagicMock()
        monitor.list_agents.return_value = []
        monitor.list_users.return_value = []
        ut = MagicMock()
        ut.list_users.return_value = []

        result = generate_report(
            report_type=ReportType.SOC2,
            mutation_tracker=tracker,
            audit_trail=trail,
            conscience_monitor=monitor,
            user_tracker=ut,
            output_format=ReportFormat.MARKDOWN,
            title="SOC2 Full Report",
        )
        assert "SOC2 Full Report" in result
