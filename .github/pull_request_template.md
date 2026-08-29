## What

Brief description of the change.

## Why

Link to issue or explain the problem. Use `Closes #123` if this resolves an open issue.

## How

Key implementation details or approach taken.

## Type of Change

- [ ] New feature or tool (add `Semver: minor` trailer to commit body)
- [ ] Bug fix (defaults to patch release)
- [ ] Breaking change (add `BREAKING CHANGE:` trailer to commit body)
- [ ] Documentation only
- [ ] Refactor (no behavior change)
- [ ] Maintenance, CI, deps, packaging

## Breaking Changes

- [ ] This PR introduces a breaking change (tool signature, config format, or output shape)

If checked, describe the impact and migration path below.

## Checklist

- [ ] Tests pass (`pytest`)
- [ ] Lint passes (`ruff check . && ruff format --check .`)
- [ ] Types pass (`mypy quickshell_mcp`)
- [ ] New tools have happy + failure path tests
- [ ] Tool docstrings written for how users ask, not what code does
- [ ] No hardcoded version strings outside `tests/fixtures/`
- [ ] Docs updated (`README.md`, tool tables) if behavior or interface changed

## Related Issues

Closes #