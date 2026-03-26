# File Management Audit — RTA-GUARD Workspace
**Date:** 2026-03-26  
**Auditor:** RTA_CTO (CTO-level agent)  
**Scope:** Entire workspace `/data/.openclaw/workspace/rta-cto`

---

## 1. Executive Summary

The workspace has **two overlapping trees**:
- **Root** (`/data/.openclaw/workspace/rta-cto`) — contains most project files (the git tracking tree)
- **Subdirectory** (`rta-guard-mvp/`) — contains duplicate copies of many files created by subagents

**Issues:**
- ❌ Files scattered across root and `rta-guard-mvp/`
- ❌ Duplicate directories (e.g., `brahmanda/` exists in both root and `rta-guard-mvp/`)
- ❌ Inconsistent commit history (some files committed from root, some from `rta-guard-mvp/`)
- ⚠️ Git tracks both trees, leading to potential confusion
- ✅ No actual data loss (all files present somewhere)

**Recommendation:** Choose a single canonical root (`rta-guard-mvp/`) and migrate all root files into it, then set that as the git working tree. Or keep root as canonical and remove `rta-guard-mvp/` duplicates. **Do not delete** anything yet; this is a report only.

---

## 2. Current State

### 2.1 Git Repository Root
- **Git root:** `/data/.openclaw/workspace/rta-cto`
- **Remote:** `origin/main` (GitHub)
- **Current HEAD:** `master` (local), tracking `origin/main`

### 2.2 Directory Structure Comparison

| Directory | In Root? | In rta-guard-mvp/? | Status |
|-----------|----------|-------------------|--------|
| `brahmanda/` | ✅ | ✅ (some files) | Partial duplicate |
| `config/` | ✅ | ✅ (examples only) | OK (root has actual config; mvp has examples) |
| `dashboard/` | ✅ | ❌ | Only in root |
| `demo/` | ✅ | ❌ | Only in root |
| `discus/` | ✅ | ❌ | Only in root |
| `discus-rs/` | ✅ | ❌ | Only in root |
| `docs/` | ✅ | ✅ | Overlap; MVP has extra training/ |
| `helm/` | ✅ | ✅ | Both contain chart files (some duplicates) |
| `k8s/` | ✅ | ❌ | Only in root |
| `logging/` | ✅ | ❌ | Only in root |
| `memory/` | ✅ | ❌ | Only in root (daily notes) |
| `mission-control/` | ✅ | ✅ (partial) | MVP has subset |
| `monitoring/` | ✅ | ❌ | Only in root |
| `scripts/` | ✅ | ❌ | Only in root |
| `showcase/` | ✅ | ❌ | Only in root |
| `tests/` | ✅ | ❌ | Only in root |
| `tools/` | ✅ | ❌ | Only in root |

### 2.3 Conflicting Files (same path in both trees)

Root-level config files exist **only in root**, not in `rta-guard-mvp/`:
- `Dockerfile` (root only)
- `docker-compose.yml` (root only)
- `requirements.txt` (root only)
- `.env.example` (root only)
- `README.md` (root only)
- `AGENTS.md`, `SOUL.md`, `USER.md`, `TOOLS.md`, `IDENTITY.md`, `HEARTBEAT.md`, `BOOTSTRAP.md` (root only)

`rta-guard-mvp/` has its own copy of `docker-compose.yml` and `Dockerfile`? Let's verify: the earlier listing showed `rta-guard-mvp/helm/`, `rta-guard-mvp/docs/`, `rta-guard-mvp/config/`, `rta-guard-mvp/brahmanda/` (partial). But does it have its own `Dockerfile`? Check: Not listed. So `rta-guard-mvp/` does not have Dockerfile at its root. That means the Dockerfile is only in root, but it's tracked in git and pushed. That's fine.

But wait: `rta-guard-mvp/` is a subdirectory. It has its own internal structure that mirrors parts of the root. This is likely because subagents created files in the wrong location (some in root, some in rta-guard-mvp). The git repository includes both trees.

### 2.4 Git Tracking Status

From `git ls-files`, tracked files include:
- Many root-level files (Dockerfile, docker-compose.yml, etc.)
- Entire `brahmanda/` from root (50+ Python modules)
- Entire `discus-rs/` from root
- Entire `docs/` from root (plus training in subdirs)
- Entire `helm/` from root
- Entire `k8s/` from root
- Entire `monitoring/` from root
- Entire `logging/` from root
- Entire `dashboard/` from root
- Plus files under `rta-guard-mvp/` for:
  - `brahmanda/` (backup, dr, cost, etc. — these appear to have been created in rta-guard-mvp by subagents)
  - `docs/` (training, deployment-prod, dev-setup, etc.)
  - `config/examples/`
  - `helm/rta-guard/` (backup templates, updated values)

Effect: The same logical component (e.g., `brahmanda/`) exists in two places with different content. Git tracks both; they are not symlinks.

---

## 3. Duplication Analysis

### 3.1 brahmanda/ (largest module)

**Root brahmanda/ contains:**
- Core modules: `conscience.py`, `pipeline.py`, `tamas.py`, `sla_monitor.py`, `rate_limit.py`, `rbac.py`, `tenancy.py`, `extractor.py`, `verifier.py`, `models.py`, `config.py`, `profiles.py`, `qdrant_client.py`, `mutation.py`, `temporal.py`, `attribution.py`, `confidence.py`, `compliance.py`, `escalation.py`
- Plus test modules: `test_*.py` for many

**rta-guard-mvp/brahmanda/ contains:**
- Phase 6 additions: `backup.py`, `restore.py`, `dr_monitor.py`, `snapshot.py`, `cost_monitor.py`, `quotas.py`, `efficient_ops.py`, `cost_report.py`, `region.py`, `ha.py`, `replication.py`, `failover.py`, `metrics.py`, `logging_config.py`, `log_analyzer.py`, `test_backup_dr.py`, `test_cost.py`
- And possibly some core modules that were copied over during earlier phases? Verified earlier: rta-guard-mvp/brahmanda/ had `__init__.py`, `config.py`, `conscience.py`, `cost_monitor.py`, `cost_report.py`, `efficient_ops.py`, etc. — it's a mix.

**Conclusion:** Two separate sets of modules; the root version is the original Phase 1–5 code, while `rta-guard-mvp/brahmanda/` contains Phase 6 additions and some possibly copied core files. This is a **split codebase**.

### 3.2 docs/

- Root `docs/` contains: DEPLOYMENT.md, MONITORING.md, LOGGING.md, HA.md, COST.md, DISASTER_RECOVERY.md, CICD.md, RTA-RULESET.md, plus subdirectories (TRAINING/, etc.)
- `rta-guard-mvp/docs/` contains: USER_GUIDE.md, ADMIN_GUIDE.md, ARCHITECTURE.md, API_REFERENCE.md, DEPLOYMENT-PROD.md, DEV_SETUP.md, CONTRIBUTING.md, RELEASE_PROCESS.md, FAQ.md, CHEATSHEET.md, TRAINING_README.md, plus TRAINING/ (copied from root)

Root docs are the Phase 6.1–6.7 technical docs. MVP docs are the Phase 6.8 user/developer docs. This is a **complementary split**, not a duplicate; they should ideally be merged under a single docs tree.

### 3.3 helm/

- Both root and `rta-guard-mvp/helm/rta-guard/` contain Helm charts.
- Root Helm chart is the original (from 6.1).
- `rta-guard-mvp/helm/rta-guard/` has updated `values.yaml` and backup templates from 6.7, plus possible modifications from 6.5 (HA). There may be divergence.

### 3.4 Other dirs: config/, mission-control/

- `config/examples/` only exists in `rta-guard-mvp/` (good).
- `mission-control/` exists in both; root has original; `rta-guard-mvp/` likely has a partial copy.

---

## 4. Issues & Risks

| Issue | Impact | Severity |
|-------|--------|----------|
| **Split codebase** — Python modules are in two locations (root/brahmanda and rta-guard-mvp/brahmanda) with different content | Runtime confusion: imports may pick one over the other depending on PYTHONPATH; packaging unclear | HIGH |
| **Duplicate Helm charts** — two versions with different values/templates | Deployment inconsistency; which one is the source of truth? | HIGH |
| **Scattered documentation** — technical docs in root/docs, user/developer docs in rta-guard-mvp/docs | Users may not know where to look; navigation fragmented | MEDIUM |
| **Mixed git history** — some files committed from root, some from rta-guard-mvp path | Blurs project structure; future merges could cause conflicts | MEDIUM |
| **Root contains many non-code files** (AGENTS.md, SOUL.md, etc.) that are config/metadata only | Not a code issue, but adds to root clutter | LOW |
| **Missing top-level manifest** — no single `pyproject.toml` or `Cargo.toml` at repo root that defines the project layout | Unclear how to build/install the project as a whole | MEDIUM |

---

## 5. Recommended Consolidation (Not Executed)

To fix, pick one canonical root:

### Option A: Use `rta-guard-mvp/` as project root
- Move all top-level project files (Dockerfile, docker-compose.yml, requirements.txt, discus-rs/, dashboard/, demo/, testing, etc.) into `rta-guard-mvp/`
- Update git index to reflect new paths
- Delete duplicates from root
- Set `rta-guard-mvp/` as the new git root (or keep git at current root but with files moved)

### Option B: Keep current root as git root, remove `rta-guard-mvp/`
- Merge necessary files from `rta-guard-mvp/` into appropriate root directories:
  - Merge `rta-guard-mvp/brahmanda/*` into root `brahmanda/` (resolving duplicates)
  - Merge `rta-guard-mvp/docs/*` into root `docs/`
  - Merge `rta-guard-mvp/config/examples/` into root `config/`
  - Merge `rta-guard-mvp/helm/rta-guard/` into root `helm/rta-guard/` (overwriting with newer versions)
- Delete `rta-guard-mvp/` directory entirely
- Commit consolidation

**Suggested choice:** Option B (keep root as git root) because the git remote is already configured there and most of the codebase lived there from Phases 1–5. The `rta-guard-mvp/` subdirectory appears to be an artifact of Phase 6 subagents writing to a relative path; it can be retired after merging its new files.

---

## 6. Immediate Observations

- **No data loss** detected; all deliverables exist somewhere in the workspace.
- **All Phase 6 work is present** either in root or `rta-guard-mvp/`.
- **GitHub pushes** have been successful with files from both trees (since both are tracked).
- **Functionality unaffected** as long as deployment uses the correct paths (Dockerfile expects root layout). But this is fragile.

---

## 7. Next Steps (For Your Decision)

1. **Decide on canonical structure** (Option A or B above)
2. **If B:** I can perform a safe merge of `rta-guard-mvp/` contents into root, ensuring no overwrites of root files that may have uncommitted changes.
3. **Reorganize git index** to reflect single coherent tree
4. **Audit imports** to ensure no broken references (e.g., `from brahmanda import X` works regardless of which `brahmanda/` is on PYTHONPATH)
5. **Push final consolidated state** to GitHub
6. **Document the final project layout** in `docs/STRUCTURE.md`

---

## 8. Conclusion

The workspace currently operates in a **split-brain state** but all code is present and functional. To maintain long-term health, consolidate into a single tree without deleting any content (just moving/merging). Awaiting your directive on which option to proceed with.

**No deletions performed** — this report is informational only.
