## What

Brief description of the change.

## Why

Link to issue or explain the problem. Use `Closes #123` if this resolves an open issue.

## How

Key implementation details or approach taken.

## Type of Change

- [ ] `feat` (new feature or tool)
- [ ] `fix` (bug fix)
- [ ] `docs` (documentation only)
- [ ] `refactor` (code change with no behavior change)
- [ ] `chore` (maintenance, deps, CI)

## Breaking Changes

- [ ] This PR introduces a breaking change (tool signature, config format, or output shape)

If checked, describe the impact and migration path below.

## Checklist

- [ ] Tests pass (`pytest`)
- [ ] Lint passes (`ruff check . && ruff format --check .`)
- [ ] Types pass (`mypy quickshell_docs_mcp`)
- [ ] New tools have happy + failure path tests
- [ ] Tool docstrings written for how users ask, not what code does
- [ ] No hardcoded version strings outside `tests/fixtures/`
- [ ] Docs updated (`README.md`, tool tables) if behavior or interface changed

## Related Issues

Closes #