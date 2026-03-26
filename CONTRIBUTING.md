# Contributing to RTA-GUARD

Thank you for your interest in contributing to RTA-GUARD! We welcome contributions from the community.

## Quick Start

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Make your changes
4. Run tests: `python -m pytest tests/ -v && cd discus-rs && cargo test`
5. Submit a pull request

## Getting Started

See [docs/DEV_SETUP.md](docs/DEV_SETUP.md) for detailed development setup instructions.

## What to Contribute

### Good First Issues
- Add new rule implementations (R14–R20)
- Improve WASM binary size (target: <500KB)
- Add language bindings (Java, C#, Ruby)
- Enhance dashboard UI
- Write additional test coverage
- Improve documentation

### How We Work
- **Feature branches** for all work
- **Test-driven** — new code must have tests
- **Commit messages** follow [Conventional Commits](https://www.conventionalcommits.org/)
- **Code review** required for all PRs
- **CI must pass** before merge

## Code Standards

### Python
- Python 3.11+
- Type hints required
- Follow existing code style (consistent throughout)
- `pytest` for testing

### Rust
- Rust 1.94+
- `clippy` must pass with no warnings
- `rustfmt` must pass
- `cargo test` must pass

### General
- Don't break existing tests
- Use descriptive variable names
- Add docstrings to public APIs
- Keep functions focused and small

## Testing

```bash
# Python tests
python -m pytest tests/ -v

# Rust tests
cd discus-rs && cargo test

# All tests
python -m pytest tests/ -q && cd discus-rs && cargo test
```

## Pull Request Process

1. Ensure your branch is up to date with `main`
2. Run all tests locally
3. Create a PR with a clear description of changes
4. Link any related issues
5. Wait for CI to pass
6. Address any review feedback
7. Squash and merge when approved

## Reporting Issues

- Use the issue tracker
- Include reproduction steps
- Include expected vs actual behavior
- Include environment details (OS, Python version, Rust version)

## Code of Conduct

Be respectful, inclusive, and constructive. We are building a safer AI ecosystem together.

## Questions?

- Open an issue for bugs or feature requests
- Join discussions in the GitHub Discussions tab
- Check [docs/FAQ.md](docs/FAQ.md) for common questions

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.

---

*The last line of defense.* 🛡️
