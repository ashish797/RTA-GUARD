# CI/CD Documentation — RTA-GUARD

## Pipeline Overview

RTA-GUARD uses 5 GitHub Actions workflows for continuous integration, delivery, security, and documentation.

```
push/PR ──→ CI (lint + test + build) ──→ Deploy (Docker + K8s)
tag v*  ──→ Release (binaries + GitHub Release)
weekly  ──→ Security (CodeQL + Trivy + audits)
docs/*  ──→ Docs (pdoc3 + rustdoc → GitHub Pages)
```

## Workflows

### 1. CI (`ci.yml`)

**Triggers:** Push to `main`, pull requests

| Job | What it does |
|-----|-------------|
| **lint** | `ruff` (Python), `clippy` + `rustfmt` (Rust), `bandit` (Python security) |
| **test** | `pytest` with JUnit XML + coverage (Python 3.11) |
| **test-rust** | `cargo test` (native) |
| **build-wasm** | WASM browser (`wasm32-unknown-unknown`) + WASI (`wasm32-wasip1`) |
| **build-summary** | Aggregated status table in GitHub Step Summary |

**Artifacts:** pytest results, coverage XML, WASM binaries (browser + WASI), bandit report

### 2. Release (`release.yml`)

**Triggers:** Version tags (`v*`)

| Job | What it does |
|-----|-------------|
| **build-browser-wasm** | Production WASM for browser injection |
| **build-wasi** | Production WASI binary for serverless/CLI |
| **build-bindings** | Python wheel via maturin (optional) |
| **changelog** | Auto-generate from commit messages since last tag |
| **release** | Create GitHub Release with all assets |

**Usage:**
```bash
git tag v0.1.0
git push origin v0.1.0
```

Pre-release tags (`-rc`, `-beta`) are automatically marked as pre-releases.

### 3. Deploy (`deploy.yml`)

**Triggers:** After CI passes on `main` (via `workflow_run`)

| Job | What it does |
|-----|-------------|
| **build-and-push** | Docker build → push to `ghcr.io` |
| **deploy-staging** | `kubectl set image` or `helm upgrade` to K8s |

**Image tags:** `latest`, git SHA, branch name, semver

### 4. Security (`security.yml`)

**Triggers:** Push/PR to `main`, weekly schedule (Monday 06:00 UTC)

| Job | What it does |
|-----|-------------|
| **codeql** | CodeQL SAST for Python |
| **codeql-rust** | CodeQL SAST for Rust (via cpp analyzer) |
| **trufflehog** | Secret scanning (full history) |
| **cargo-audit** | Rust dependency vulnerability audit |
| **pip-audit** | Python dependency vulnerability audit |
| **trivy-container** | Container image CVE scan |
| **dependency-review** | PR dependency change review |

### 5. Docs (`docs.yml`)

**Triggers:** Changes to `docs/`, `brahmanda/`, `discus-rs/src/`

| Job | What it does |
|-----|-------------|
| **build** | pdoc3 (Python API) + rustdoc (Rust API) + mkdocs (guides) |
| **deploy** | Publish to GitHub Pages |

## Required Secrets

| Secret | Where | Description |
|--------|-------|-------------|
| `GITHUB_TOKEN` | Auto | GHCR push (automatic, no setup needed) |
| `KUBECONFIG` | Deploy | Base64-encoded kubeconfig for K8s deploy |
| `GHCR_TOKEN` | Deploy | Optional: custom GHCR token (defaults to `GITHUB_TOKEN`) |

### Setting up KUBECONFIG

```bash
# Encode your kubeconfig
cat ~/.kube/config | base64 -w0

# Add as GitHub secret: Settings → Secrets → KUBECONFIG
```

### Enabling GitHub Pages

1. Go to repo Settings → Pages
2. Source: GitHub Actions
3. The docs workflow will auto-deploy

## Dependabot Configuration

Automated dependency updates via `.github/dependabot.yml`:

| Ecosystem | Directory | Schedule |
|-----------|-----------|----------|
| pip | `/` | Weekly (Monday) |
| cargo | `/discus-rs` | Weekly (Monday) |
| cargo | `/discus-rs/bindings/python` | Weekly (Monday) |
| docker | `/` | Weekly (Monday) |
| github-actions | `/` | Weekly (Monday) |

## Branch Protection (Recommended)

For `main` branch:

1. **Settings → Branches → Add rule** for `main`
2. ✅ Require pull request reviews (1 reviewer)
3. ✅ Require status checks: `Lint`, `Test (Python 3.11)`, `Test (Rust)`, `Build WASM`
4. ✅ Require branches to be up to date
5. ✅ Require CodeQL to pass

## Local Development

### Run CI checks locally

```bash
# Lint
ruff check .
cargo clippy --manifest-path discus-rs/Cargo.toml -- -D warnings

# Test
pytest tests/ -v
cargo test --manifest-path discus-rs/Cargo.toml

# Build WASM
cd discus-rs && cargo build --target wasm32-unknown-unknown --release
```

### Create a release

```bash
# Bump version in Cargo.toml, commit, then:
git tag v0.1.0
git push origin v0.1.0
# Release workflow runs automatically
```

## Monitoring Pipeline Health

- **GitHub Actions tab:** Workflow run history and logs
- **Step Summaries:** CI summary tables in each run
- **Dependabot:** Security alerts in repo Security tab
- **CodeQL:** Code scanning alerts in Security tab
