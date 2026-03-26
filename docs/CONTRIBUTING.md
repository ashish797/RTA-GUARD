# RTA-GUARD — Contributing Guide

> **Version 0.6.1** | Contribution Guidelines, PR Process, Code Standards

---

## Table of Contents

- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Pull Request Process](#pull-request-process)
- [Code Standards](#code-standards)
- [Testing Requirements](#testing-requirements)
- [Documentation](#documentation)
- [Security](#security)
- [Issue Guidelines](#issue-guidelines)
- [Review Process](#review-process)

---

## Getting Started

1. **Fork** the repository
2. **Clone** your fork:
   ```bash
   git clone https://github.com/YOUR_USER/rta-guard.git
   cd rta-guard
   ```
3. **Set up** your development environment — see [DEV_SETUP.md](DEV_SETUP.md)
4. **Create a branch** from `main`:
   ```bash
   git checkout -b feature/your-feature
   ```

---

## Development Workflow

### Branch Naming

| Prefix | Use Case | Example |
|--------|----------|---------|
| `feature/` | New features | `feature/rule-r14` |
| `fix/` | Bug fixes | `fix/drift-calculation` |
| `docs/` | Documentation | `docs/api-reference` |
| `refactor/` | Code refactoring | `refactor/guard-check-flow` |
| `chore/` | Maintenance | `chore/update-deps` |
| `test/` | Test additions | `test/conscience-coverage` |

### Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types:** `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `ci`, `perf`

**Examples:**
```
feat(discus): add R14 rule for code injection detection
fix(brahmanda): correct drift score EMA calculation
docs(api): add webhook endpoint documentation
test(conscience): add edge cases for Tamas state transitions
deps(cargo): update wasm-bindgen to 0.2.90
```

### Pre-commit Checks

Run these before pushing:

```bash
# Python
ruff check . && ruff format --check .
python3 -m pytest tests/ brahmanda/test_*.py -v

# Rust
cd discus-rs && cargo clippy -- -D warnings && cargo fmt --check && cargo test
```

---

## Pull Request Process

### 1. Create the PR

- Target: `main` branch
- Title: Follows commit message format
- Description: What, why, how

### 2. PR Template

```markdown
## What

Brief description of the change.

## Why

Motivation / issue link.

## How

Implementation approach.

## Testing

- [ ] Unit tests added/updated
- [ ] Integration tests pass
- [ ] Manual testing performed

## Checklist

- [ ] Code follows style guidelines
- [ ] Self-review completed
- [ ] Documentation updated (if applicable)
- [ ] No breaking changes (or migration guide provided)
```

### 3. Required Checks

PRs must pass all CI checks before merge:

| Check | Workflow | Required |
|-------|----------|----------|
| Lint (Python) | `ci.yml` | ✅ |
| Lint (Rust) | `ci.yml` | ✅ |
| Test (Python) | `ci.yml` | ✅ |
| Test (Rust) | `ci.yml` | ✅ |
| Build WASM | `ci.yml` | ✅ |
| CodeQL | `security.yml` | ✅ |

### 4. Review

- At least **1 approving review** required
- Address all review comments
- Re-request review after changes

### 5. Merge

- **Squash merge** for feature branches (clean history)
- **Merge commit** for release branches
- Delete branch after merge

---

## Code Standards

### Python

| Aspect | Standard |
|--------|----------|
| Formatter | `ruff format` |
| Linter | `ruff check` |
| Security | `bandit -ll` |
| Type hints | Required for public APIs |
| Docstrings | Required for public classes/functions |
| Max line length | 120 characters |

```python
def check_drift(agent_id: str, window_size: int = 50) -> DriftResult:
    """Calculate EMA-smoothed drift score for an agent.

    Args:
        agent_id: Unique agent identifier.
        window_size: Number of recent interactions to consider.

    Returns:
        DriftResult with score (0-1) and component breakdown.

    Raises:
        AgentNotFoundError: If agent_id is not registered.
    """
    ...
```

### Rust

| Aspect | Standard |
|--------|----------|
| Formatter | `cargo fmt` |
| Linter | `cargo clippy -- -D warnings` |
| Documentation | `///` doc comments for public items |
| Unsafe | Requires explicit `// SAFETY:` comment |

### General

- **No secrets** in code — use environment variables
- **No hardcoded URLs** — use configuration
- **Defensive coding** — validate inputs, handle errors explicitly
- **Backward compatibility** — don't break existing APIs without deprecation

---

## Testing Requirements

### Minimum Coverage

| Component | Minimum |
|-----------|---------|
| New rules | 100% (pass + violation cases) |
| Public API functions | 90% |
| Enterprise features | 85% |
| Overall | Maintained (no regression) |

### Test Structure

```python
# brahmanda/test_new_feature.py

def test_happy_path():
    """Feature works under normal conditions."""
    ...

def test_edge_case_empty():
    """Handles empty input gracefully."""
    ...

def test_edge_case_max():
    """Handles maximum load."""
    ...

def test_error_handling():
    """Raises appropriate exceptions on failure."""
    ...
```

### Running Tests

```bash
# Python
python3 -m pytest tests/ brahmanda/test_*.py -v

# Rust
cd discus-rs && cargo test

# With coverage
python3 -m pytest --cov=discus --cov=brahmanda --cov-report=html
```

---

## Documentation

### When to Update Docs

| Change Type | Docs to Update |
|-------------|---------------|
| New feature | `USER_GUIDE.md`, `API_REFERENCE.md`, `CHEATSHEET.md` |
| New rule | `RTA-RULESET.md`, `ARCHITECTURE.md` |
| API change | `API_REFERENCE.md` |
| Config change | `USER_GUIDE.md`, `DEPLOYMENT.md` |
| New env var | `USER_GUIDE.md`, `DEPLOYMENT.md`, `CHEATSHEET.md` |
| Breaking change | Migration guide in PR description |

### Doc Style

- Use Markdown
- Include code examples for every API
- Cross-reference related docs
- Keep tables for structured data
- Add `> **Version X.Y.Z**` header to all docs

---

## Security

### Reporting Vulnerabilities

**Do not open public issues for security vulnerabilities.**

Email: security@rta-guard.dev (or use GitHub's private vulnerability reporting)

### Security Review

PRs touching these areas require additional review:

- Authentication/authorization (`brahmanda/rbac.py`, `brahmanda/sso.py`)
- Encryption (`brahmanda/backup.py`)
- Input validation (`discus/guard.py`, `discus/rules.py`)
- Network endpoints (`dashboard/app.py`)

### Dependency Updates

- Dependabot creates PRs weekly (see [CICD.md](CICD.md))
- Review security advisories before merging
- Run `pip audit` and `cargo audit` locally

---

## Issue Guidelines

### Bug Reports

```markdown
**Describe the bug**
Clear description.

**To Reproduce**
Steps to reproduce.

**Expected behavior**
What should happen.

**Actual behavior**
What actually happens.

**Environment**
- RTA-GUARD version:
- Python version:
- Deployment: Docker / K8s / Direct
- Database: SQLite / PostgreSQL
```

### Feature Requests

```markdown
**Problem**
What problem does this solve?

**Proposed Solution**
How should it work?

**Alternatives Considered**
Other approaches.

**Additional Context**
Screenshots, diagrams, etc.
```

### Labels

| Label | Meaning |
|-------|---------|
| `bug` | Something broken |
| `enhancement` | New feature |
| `documentation` | Docs improvement |
| `good first issue` | Beginner-friendly |
| `priority: critical` | Production impact |
| `priority: high` | Important |
| `priority: medium` | Normal |
| `priority: low` | Nice to have |

---

## Review Process

### What Reviewers Look For

1. **Correctness** — Does it do what it claims?
2. **Tests** — Are edge cases covered?
3. **Style** — Follows project conventions?
4. **Security** — No vulnerabilities introduced?
5. **Performance** — No regressions?
6. **Docs** — Updated where needed?
7. **Backward compat** — Existing APIs preserved?

### Review Timeline

- **First response:** Within 2 business days
- **Follow-up:** Within 1 business day
- **Critical fixes:** Same day

### Becoming a Maintainer

Regular contributors who demonstrate:
- Quality PRs (well-tested, documented)
- Thorough reviews
- Community engagement

May be invited to become maintainers with merge access.

---

## License

By contributing, you agree your code will be licensed under **Apache 2.0**.
