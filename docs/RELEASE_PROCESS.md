# RTA-GUARD — Release Process

> **Version 0.6.1** | Release Cadence, Versioning, Changelog

---

## Table of Contents

- [Versioning Scheme](#versioning-scheme)
- [Release Cadence](#release-cadence)
- [Release Workflow](#release-workflow)
- [Changelog](#changelog)
- [Pre-Release Process](#pre-release-process)
- [Hotfix Process](#hotfix-process)
- [Artifacts](#artifacts)
- [Post-Release](#post-release)

---

## Versioning Scheme

RTA-GUARD follows [Semantic Versioning 2.0](https://semver.org/):

```
MAJOR.MINOR.PATCH[-PRERELEASE]

0.6.1
│ │ │
│ │ └── Patch: bug fixes, minor improvements
│ └──── Minor: new features, non-breaking changes
└────── Major: breaking changes, major rewrites
```

### Pre-release Tags

| Tag | Meaning | Example |
|-----|---------|---------|
| `-alpha` | Early development, unstable | `0.7.0-alpha` |
| `-beta` | Feature-complete, testing | `0.7.0-beta` |
| `-rc` | Release candidate, final testing | `0.7.0-rc1` |
| _(none)_ | Stable release | `0.7.0` |

### Version Bumps

| Change Type | Bump |
|-------------|------|
| New rule or feature | Minor |
| Bug fix | Patch |
| Breaking API change | Major |
| Deprecation notice | Minor |
| Documentation only | Patch |
| Security fix | Patch (or Minor if API changes) |

---

## Release Cadence

| Type | Frequency | Branch |
|------|-----------|--------|
| Minor release | Monthly | `main` → tag |
| Patch release | As needed | `main` → tag |
| Major release | Quarterly | `release/vX.0` → tag |
| Hotfix | Immediate | `hotfix/description` → tag |
| Pre-release | Weekly during active dev | `main` → `-rc` tag |

### Release Calendar

```
Week 1:  Feature freeze, create -rc1
Week 2:  Testing, bug fixes, -rc2 if needed
Week 3:  Final testing, documentation review
Week 4:  Release stable version
```

---

## Release Workflow

### 1. Prepare

```bash
# Ensure main is up to date
git checkout main
git pull origin main

# Verify CI is green
# → Check GitHub Actions tab

# Run full test suite locally
python3 -m pytest tests/ brahmanda/test_*.py -v
cd discus-rs && cargo test && cd ..
```

### 2. Update Version

Update version in these files:

| File | Field |
|------|-------|
| `discus-rs/Cargo.toml` | `version = "0.7.0"` |
| `discus-rs/bindings/python/Cargo.toml` | `version = "0.7.0"` |
| `Dockerfile` | `LABEL version="0.7.0"` |
| `docs/*.md` | Version header |
| `helm/rta-guard/Chart.yaml` | `version: 0.7.0` + `appVersion: "0.7.0"` |

### 3. Commit & Tag

```bash
# Commit version bump
git add -A
git commit -m "chore: bump version to 0.7.0"

# Tag (triggers release workflow)
git tag v0.7.0
git push origin main --tags
```

### 4. Automated Release

The `release.yml` workflow runs automatically on `v*` tags:

1. **Build WASM** — Browser + WASI binaries
2. **Build Python wheel** — via maturin (optional)
3. **Generate changelog** — from commits since last tag
4. **Create GitHub Release** — with all assets attached

### 5. Verify

- Check the GitHub Release page for assets
- Verify Docker image: `docker pull rtaguard/dashboard:0.7.0`
- Verify WASM files are attached
- Verify changelog is accurate

---

## Changelog

### Format

Changelogs are auto-generated from commit messages. Follow Conventional Commits for clean changelogs:

```
## What's Changed

### Features
* feat(discus): add R14 rule for code injection by @contributor (#123)

### Bug Fixes
* fix(brahmanda): correct drift EMA calculation by @contributor (#124)

### Documentation
* docs(api): add webhook endpoints by @contributor (#125)

### Dependencies
* deps(cargo): update wasm-bindgen to 0.2.90 (#126)

**Full Changelog**: https://github.com/rta-guard/rta-guard/compare/v0.6.1...v0.7.0
```

### Manual Changelog

For major releases, write a manual changelog in the GitHub Release description:

```markdown
# RTA-GUARD v0.7.0

## Highlights
- New R14 rule for code injection detection
- 3x faster drift scoring with SIMD
- Multi-region replication support

## Breaking Changes
- `DiscusGuard.check()` now returns `GuardResult` instead of `bool`
  - Migration: use `result.passed` for boolean checks

## Upgrade Guide
1. Update Python: `pip install rtaguard==0.7.0`
2. Update Rust: `cargo update discus-rs`
3. Run migrations: `python -m brahmanda.migrate`
4. See [MIGRATION.md](docs/MIGRATION.md) for details
```

---

## Pre-Release Process

### Release Candidate

```bash
# Create RC
git tag v0.7.0-rc1
git push origin v0.7.0-rc1

# Test, fix issues, create rc2 if needed
git tag v0.7.0-rc2
git push origin v0.7.0-rc2

# When ready, create stable
git tag v0.7.0
git push origin v0.7.0
```

Pre-release tags are automatically marked as pre-releases on GitHub.

### Beta

For larger features that need broader testing:

```bash
git tag v0.7.0-beta1
git push origin v0.7.0-beta1
```

---

## Hotfix Process

For critical production bugs:

```bash
# Create hotfix branch from the release tag
git checkout -b hotfix/fix-description v0.6.1

# Fix the issue
# ... code changes ...
# ... tests ...

# Commit
git commit -m "fix(component): description"

# Tag patch release
git tag v0.6.2
git push origin hotfix/fix-description --tags

# Merge back to main
git checkout main
git merge hotfix/fix-description
git push origin main

# Clean up
git branch -d hotfix/fix-description
```

---

## Artifacts

Each release produces:

| Artifact | Format | Location |
|----------|--------|----------|
| Docker image | `rtaguard/dashboard:X.Y.Z` | GitHub Container Registry |
| WASM (browser) | `discus_rs_browser.wasm` | GitHub Release |
| WASM (WASI) | `discus_rs_wasi.wasm` | GitHub Release |
| Python wheel | `discus_rs-X.Y.Z-py3-none-any.whl` | GitHub Release (optional) |
| Helm chart | `rta-guard-X.Y.Z.tgz` | GitHub Release |
| Changelog | Markdown | GitHub Release body |

### Docker Tags

| Tag | Meaning |
|-----|---------|
| `0.7.0` | Exact version |
| `0.7` | Latest patch of 0.7.x |
| `0` | Latest minor of 0.x |
| `latest` | Latest stable release |

---

## Post-Release

### Checklist

- [ ] GitHub Release created with all assets
- [ ] Docker image pushed to GHCR
- [ ] Helm chart updated
- [ ] Documentation version headers updated
- [ ] Announcement (if major/minor release)
- [ ] Deprecation notices communicated (if any)
- [ ] `main` branch is ahead of the release tag

### Deprecation Policy

When deprecating an API:

1. **Minor N**: Add deprecation warning (logs + Python `warnings.warn`)
2. **Minor N+1**: Keep warning, update docs with migration guide
3. **Major N+2**: Remove deprecated API

Example:

```python
import warnings

def old_function():
    warnings.warn(
        "old_function() is deprecated, use new_function() instead. "
        "Will be removed in v1.0.0.",
        DeprecationWarning,
        stacklevel=2,
    )
    return new_function()
```

---

## Version History

| Version | Date | Highlights |
|---------|------|------------|
| 0.6.1 | 2026-03-26 | Ecosystem integration (Docker, K8s, Helm) |
| 0.6.0 | 2026-03-20 | Enterprise layer (tenancy, RBAC, SSO, webhooks) |
| 0.5.0 | 2026-03-10 | Conscience monitor (drift, Tamas, temporal) |
| 0.4.0 | 2026-03-01 | Brahmanda Map (ground truth verification) |
| 0.3.0 | 2026-02-20 | Rust/WASM engine (discus-rs) |
| 0.2.0 | 2026-02-10 | Dashboard + FastAPI server |
| 0.1.0 | 2026-02-01 | Initial release (Discus guard engine) |

---

## CI/CD Integration

See [CICD.md](CICD.md) for details on:

- Release workflow triggers (`release.yml`)
- Automated changelog generation
- GitHub Release creation
- Docker image publishing
