# RTA-GUARD — Training Materials

> **Version 0.6.1** | Last Updated: 2026-03-26

---

## Overview

This directory contains all training materials for RTA-GUARD — from quick start tutorials to full operator workshops. Materials are designed for self-paced learning or instructor-led delivery.

---

## Available Materials

### 🚀 Quick Start Course
**File:** [TRAINING/quickstart-course.md](TRAINING/quickstart-course.md)
**Duration:** ~1 hour (hands-on)
**Level:** Beginner
**What you'll learn:**
- Deploy RTA-GUARD locally with Docker
- Guard an AI agent with the Discus kill-switch
- Understand and customize the 13 rules
- Navigate the monitoring dashboard
- Integrate with an OpenAI agent

**Best for:** Developers new to RTA-GUARD, evaluating the product, proof-of-concept work.

---

### 🎓 Operator Workshop
**File:** [TRAINING/operator-workshop.md](TRAINING/operator-workshop.md)
**Duration:** 2 days (16 hours)
**Level:** Intermediate
**What you'll learn:**
- Deep architecture understanding
- Production deployment (Docker, Kubernetes, Helm)
- Rules engine mastery (writing, testing, hot-reloading)
- Monitoring, alerting, and log management
- High availability and multi-region operations
- Backup, disaster recovery, and incident response
- Security hardening (RBAC, TLS, secrets)
- Cost optimization and capacity planning

**Best for:** Platform/SRE teams deploying RTA-GUARD in production.

---

### 📹 Video Scripts
**File:** [TRAINING/videos/README.md](TRAINING/videos/README.md)
**Content:** Topic index and script outlines for 18 planned training videos
**Levels:** Beginner (V01–V04), Intermediate (V05–V08), Advanced (V09–V14), Expert (V15–V18)

---

## Example Configurations

| Config | File | Description |
|--------|------|-------------|
| Small | [config/examples/small.yml](../config/examples/small.yml) | Single-node, SQLite, no HA. Dev/test use. |
| Medium | [config/examples/medium.yml](../config/examples/medium.yml) | 3 replicas, PostgreSQL HA, Redis Sentinel, 2 regions. |
| Large | [config/examples/large.yml](../config/examples/large.yml) | 5+ replicas, full HA, 4 regions, Redis Cluster, autoscaling, all enterprise features. |

---

## Prerequisites

### Software
- Docker & Docker Compose
- Python 3.10+
- kubectl & Helm (for Kubernetes materials)
- A web browser (Chrome or Firefox)

### Knowledge
- Basic terminal/command-line usage
- YAML syntax (for configuration exercises)
- REST APIs (for integration exercises)
- Kubernetes concepts (for advanced materials only)

### Accounts (Optional)
- OpenAI API key (for integration exercises)
- AWS/GCP account (for multi-region exercises)
- Slack workspace (for webhook exercises)

---

## Related Documentation

| Document | Description |
|----------|-------------|
| [USER_GUIDE.md](USER_GUIDE.md) | End-user guide, installation, configuration |
| [ADMIN_GUIDE.md](ADMIN_GUIDE.md) | Operations, monitoring, backup/restore |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, data flow, components |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Docker, Docker Compose, Kubernetes, Helm |
| [API_REFERENCE.md](API_REFERENCE.md) | Python, Rust, and REST API documentation |
| [HA.md](HA.md) | High availability and multi-region guide |
| [MONITORING.md](MONITORING.md) | Prometheus, Grafana, alerting |
| [LOGGING.md](LOGGING.md) | Log structure, ELK/Loki integration |
| [DISASTER_RECOVERY.md](DISASTER_RECOVERY.md) | Backup, DR drills, RPO/RTO |
| [COST.md](COST.md) | Cost modeling, optimization, sizing |
| [RTA-RULESET.md](RTA-RULESET.md) | Rules engine, R1–R13 definitions |

---

## How to Use These Materials

### Self-Paced Learning
1. Start with the **Quick Start Course** — complete all 6 modules
2. Review the relevant docs (Architecture, Deployment, User Guide)
3. Try the **Example Configurations** — start with `small.yml`, work up to `large.yml`
4. Optionally, work through the **Operator Workshop** Day 1 on your own
5. Watch the **Video Series** as supplementary material

### Instructor-Led Training
1. **Day 1 (Quick Start + Workshop Day 1):** Architecture, deployment, rules engine, monitoring
2. **Day 2 (Workshop Day 2):** HA, security, cost optimization, incident simulation
3. Use the video scripts as slide content / talking points
4. Provide participants with the example configs as lab starting points

### Onboarding New Operators
1. Quick Start Course (1 hour)
2. Read ADMIN_GUIDE.md and DEPLOYMENT.md
3. Shadow a production on-call shift
4. Complete the Workshop Day 2 final exercise (incident simulation)
5. Review DISASTER_RECOVERY.md and COST.md

---

*RTA-GUARD v0.6.1 — The seatbelt for AI.*
