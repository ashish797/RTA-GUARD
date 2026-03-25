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

# Mutation tracking (Phase 2.6)
try:
    from .mutation import (
        MutationTracker, Mutation, compute_diff,
    )
    _MUTATION_AVAILABLE = True
except ImportError:
    _MUTATION_AVAILABLE = False

# Behavioral Profiling (Phase 3.1) + Live Drift (Phase 3.2) + Tamas (Phase 3.3)
try:
    from .profiles import (
        AgentProfile, SessionProfile, UserProfile, AnomalyType,
        DriftLevel, DriftComponents, classify_drift,
    )
    from .conscience import (
        ConscienceMonitor, BehavioralBaseline, get_monitor,
        LiveDriftScorer, DriftSnapshot,
    )
    from .tamas import (
        TamasDetector, TamasState, TamasEvent,
        EscalationAction, TamasStore,
    )
    from .temporal import (
        TemporalConsistencyChecker, ConsistencyLevel,
        classify_consistency, Statement, ContradictionPair,
    )
    _CONSCIENCE_AVAILABLE = True
except ImportError:
    _CONSCIENCE_AVAILABLE = False

# User behavior anomaly detection (Phase 3.5)
try:
    from .user_monitor import (
        UserBehaviorTracker, UserBehaviorProfile, AnomalySignal,
        AnomalyCategory, RiskLevel, get_tracker,
    )
    _USER_MONITOR_AVAILABLE = True
except ImportError:
    _USER_MONITOR_AVAILABLE = False

# Escalation protocols (Phase 3.6)
try:
    from .escalation import (
        EscalationChain, EscalationLevel, EscalationDecision,
        EscalationConfig, get_escalation_chain,
    )
    _ESCALATION_AVAILABLE = True
except ImportError:
    _ESCALATION_AVAILABLE = False

# Multi-tenant isolation (Phase 4.1)
try:
    from .tenancy import (
        TenantContext, TenantManager, get_tenant_manager,
        validate_tenant_id, get_legacy_context, reset_tenant_manager,
    )
    _TENANCY_AVAILABLE = True
except ImportError:
    _TENANCY_AVAILABLE = False

# RBAC (Phase 4.2)
try:
    from .rbac import (
        Role, Permission, RBACManager, RoleAssignment,
        get_role_permissions, get_all_permissions,
        get_rbac_manager, reset_rbac_manager,
    )
    _RBAC_AVAILABLE = True
except ImportError:
    _RBAC_AVAILABLE = False

# Compliance Reporting (Phase 4.3)
try:
    from .compliance import (
        ComplianceReport,
        ReportGenerator,
        ReportType,
        ReportFormat,
        RiskLevel,
        ExecutiveSummary,
        ViolationsSection,
        DriftAnalysisSection,
        TamasSection,
        AuditTrailSection,
        UserRiskSection,
        RecommendationsSection,
        generate_report,
    )
    _COMPLIANCE_AVAILABLE = True
except ImportError:
    _COMPLIANCE_AVAILABLE = False

# Webhook Notifications (Phase 4.4)
try:
    from .webhooks import (
        WebhookManager, WebhookConfig, WebhookEvent, WebhookEventType,
        WebhookStore, compute_signature, verify_signature,
        get_webhook_manager, reset_webhook_manager,
    )
    _WEBHOOKS_AVAILABLE = True
except ImportError:
    _WEBHOOKS_AVAILABLE = False

# Qdrant vector backend (optional — requires qdrant-client + openai)
try:
    from .qdrant_client import QdrantBrahmanda, create_qdrant_seed_map, get_qdrant_verifier
    _QDRANT_AVAILABLE = True
except ImportError:
    _QDRANT_AVAILABLE = False

# SSO Integration (Phase 4.5)
try:
    from .sso import (
        SSOProvider,
        SSOProviderType,
        SSOConfig,
        UserProfile,
        OIDCProvider,
        SAMLProvider,
        SSOManager,
        get_sso_manager,
        reset_sso_manager,
        create_oidc_config,
        create_saml_config,
    )
    _SSO_AVAILABLE = True
except ImportError:
    _SSO_AVAILABLE = False

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

if _MUTATION_AVAILABLE:
    __all__.extend([
        "MutationTracker",
        "Mutation",
        "compute_diff",
    ])

if _CONSCIENCE_AVAILABLE:
    __all__.extend([
        "AgentProfile",
        "SessionProfile",
        "UserProfile",
        "AnomalyType",
        "ConscienceMonitor",
        "BehavioralBaseline",
        "get_monitor",
        # Phase 3.2
        "DriftLevel",
        "DriftComponents",
        "classify_drift",
        "LiveDriftScorer",
        "DriftSnapshot",
        # Phase 3.3
        "TamasDetector",
        "TamasState",
        "TamasEvent",
        "EscalationAction",
        "TamasStore",
        # Phase 3.4
        "TemporalConsistencyChecker",
        "ConsistencyLevel",
        "classify_consistency",
        "Statement",
        "ContradictionPair",
    ])

if _USER_MONITOR_AVAILABLE:
    __all__.extend([
        # Phase 3.5
        "UserBehaviorTracker",
        "UserBehaviorProfile",
        "AnomalySignal",
        "AnomalyCategory",
        "RiskLevel",
        "get_tracker",
    ])

if _ESCALATION_AVAILABLE:
    __all__.extend([
        # Phase 3.6
        "EscalationChain",
        "EscalationLevel",
        "EscalationDecision",
        "EscalationConfig",
        "get_escalation_chain",
    ])

if _TENANCY_AVAILABLE:
    __all__.extend([
        # Phase 4.1
        "TenantContext",
        "TenantManager",
        "get_tenant_manager",
        "validate_tenant_id",
        "get_legacy_context",
        "reset_tenant_manager",
    ])

if _RBAC_AVAILABLE:
    __all__.extend([
        # Phase 4.2
        "Role",
        "Permission",
        "RBACManager",
        "RoleAssignment",
        "get_role_permissions",
        "get_all_permissions",
        "get_rbac_manager",
        "reset_rbac_manager",
    ])

if _COMPLIANCE_AVAILABLE:
    __all__.extend([
        # Phase 4.3
        "ComplianceReport",
        "ReportGenerator",
        "ReportType",
        "ReportFormat",
        "RiskLevel",
        "ExecutiveSummary",
        "ViolationsSection",
        "DriftAnalysisSection",
        "TamasSection",
        "AuditTrailSection",
        "UserRiskSection",
        "RecommendationsSection",
        "generate_report",
    ])

if _SSO_AVAILABLE:
    __all__.extend([
        # Phase 4.5
        "SSOProvider",
        "SSOProviderType",
        "SSOConfig",
        "UserProfile",
        "OIDCProvider",
        "SAMLProvider",
        "SSOManager",
        "get_sso_manager",
        "reset_sso_manager",
        "create_oidc_config",
        "create_saml_config",
    ])

if _WEBHOOKS_AVAILABLE:
    __all__.extend([
        # Phase 4.4
        "WebhookManager",
        "WebhookConfig",
        "WebhookEvent",
        "WebhookEventType",
        "WebhookStore",
        "compute_signature",
        "verify_signature",
        "get_webhook_manager",
        "reset_webhook_manager",
    ])

# Rate Limiting & Quotas (Phase 4.7)
try:
    from .rate_limit import (
        RateLimiter, RateLimitConfig, QuotaConfig, QuotaType,
        RateLimitResult, QuotaResult, RateLimitStore,
        RateLimitMiddleware,
        get_rate_limiter, reset_rate_limiter,
    )
    _RATE_LIMIT_AVAILABLE = True
except ImportError:
    _RATE_LIMIT_AVAILABLE = False

if _RATE_LIMIT_AVAILABLE:
    __all__.extend([
        # Phase 4.7
        "RateLimiter",
        "RateLimitConfig",
        "QuotaConfig",
        "QuotaType",
        "RateLimitResult",
        "QuotaResult",
        "RateLimitStore",
        "RateLimitMiddleware",
        "get_rate_limiter",
        "reset_rate_limiter",
    ])
