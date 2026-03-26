# RTA-GUARD Training Videos — Scripts & Topic Index

> **Note:** No actual video files are included. This directory contains scripts and topic outlines for planned training videos.

---

## Video Series: Getting Started (Beginner)

| # | Title | Duration | Script File | Description |
|---|-------|----------|-------------|-------------|
| V01 | What is RTA-GUARD? | 5 min | `scripts/v01-what-is-rta-guard.md` | Product overview, the "seatbelt for AI" concept, when to use it |
| V02 | Installation & First Run | 8 min | `scripts/v02-install-first-run.md` | Docker deployment, dashboard login, health check |
| V03 | Your First Rule Violation | 6 min | `scripts/v03-first-violation.md` | Running the demo agent, watching a session get killed |
| V04 | The 13 Rules Explained | 12 min | `scripts/v04-13-rules-explained.md` | Walk through R1–R13 with examples for each |

## Video Series: Integration (Intermediate)

| # | Title | Duration | Script File | Description |
|---|-------|----------|-------------|-------------|
| V05 | Guarding an OpenAI Agent | 10 min | `scripts/v05-guard-openai.md` | Python integration with OpenAI, input/output screening |
| V06 | Custom Rules Deep Dive | 10 min | `scripts/v06-custom-rules.md` | YAML syntax, regex patterns, severity levels, hot-reload |
| V07 | Dashboard Tour | 8 min | `scripts/v07-dashboard-tour.md` | Events, Metrics, Configuration tabs walkthrough |
| V08 | Webhooks & Notifications | 7 min | `scripts/v08-webhooks.md` | Setting up Slack, PagerDuty, and custom webhooks |

## Video Series: Production Operations (Advanced)

| # | Title | Duration | Script File | Description |
|---|-------|----------|-------------|-------------|
| V09 | Kubernetes Deployment with Helm | 12 min | `scripts/v09-k8s-helm.md` | Helm install, values override, ingress setup |
| V10 | High Availability Setup | 10 min | `scripts/v10-ha-setup.md` | Leader election, PostgreSQL HA, Redis Sentinel |
| V11 | Multi-Region Deployment | 10 min | `scripts/v11-multi-region.md` | Geo-routing, replication, failover walkthrough |
| V12 | Monitoring & Alerting | 10 min | `scripts/v12-monitoring.md` | Prometheus metrics, Grafana dashboards, alert rules |
| V13 | Backup & Disaster Recovery | 8 min | `scripts/v13-backup-dr.md` | Backup strategies, DR drills, RPO/RTO targets |
| V14 | Cost Optimization | 8 min | `scripts/v14-cost-optimization.md` | Sizing, autoscaling, right-sizing, multi-tenant costs |

## Video Series: Deep Dives (Expert)

| # | Title | Duration | Script File | Description |
|---|-------|----------|-------------|-------------|
| V15 | Brahmanda Map Internals | 10 min | `scripts/v15-brahmanda-internals.md` | Ground truth verification, data sources, caching |
| V16 | Conscience Monitor Explained | 10 min | `scripts/v16-conscience-monitor.md` | Behavioral profiling, drift detection, baseline establishment |
| V17 | Sudarshan WASM Engine | 10 min | `scripts/v17-sudarshan-wasm.md` | Rust/WASM execution model, browser vs server, Python bindings |
| V18 | Enterprise Features: RBAC & SSO | 8 min | `scripts/v18-rbac-sso.md` | Role-based access, SAML/OIDC integration, multi-tenancy |

---

## Script Format

Each script file follows this template:

```markdown
# V## — [Title]

**Duration:** ~X min
**Audience:** [Beginner|Intermediate|Advanced]

## Outline
1. [Section 1 — description]
2. [Section 2 — description]
...

## Script
[Full narration script with slide/animation cues]

## Demo Steps
[Exact commands and screenshots needed]

## Key Takeaways
- Point 1
- Point 2
- Point 3
```

---

## Production Notes

- Videos should be recorded using screen capture (OBS or similar)
- Terminal demos should use a dark theme with large font (16pt+)
- Dashboard demos should use the pre-loaded demo dataset
- Each video should end with links to related documentation
- Target resolution: 1920×1080 (1080p)
- Target bitrate: 4 Mbps for screen recordings, 8 Mbps for mixed content

---

*RTA-GUARD v0.6.1 — The seatbelt for AI.*
