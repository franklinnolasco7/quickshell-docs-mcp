# Contributing to quickshell-docs-mcp

Thanks for your interest in contributing. This document covers the basics.

## Table of Contents

- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Project Structure](#project-structure)
- [Code Style](#code-style)
- [Testing](#testing)
- [Commit Messages](#commit-messages)
- [Pull Requests](#pull-requests)
- [Reporting Issues](#reporting-issues)
- [License](#license)

## Getting Started

1. Fork and clone the repo
2. Install dependencies: `pip install -e '.[dev]'`
3. Create a branch: `git checkout -b feat/my-feature`

## Development Workflow

```bash
pip install -e '.[dev]'
pytest                                      # offline suite (fixtures, no network)
ruff check . && ruff format --check .       # lint + formatting
mypy quickshell_docs_mcp                    # typecheck
QUICKSHELL_DOCS_LIVE_TEST=1 pytest -m live  # opt-in live tests
.venv/bin/python scripts/smoke_test.py      # end-to-end stdio vs live sites
nix develop                                 # dev shell with everything CI uses
```

Debug interactively with the official MCP Inspector:

```bash
npx @modelcontextprotocol/inspector quickshell-docs-mcp
```

> Agents working on this repo should read [`AGENTS.md`](./AGENTS.md). To make an agent *using* this server reach for it reliably, add a rule to that project's instructions telling it to verify QML types here before writing any from memory.

**All checks must pass before submitting a PR.**

## Project Structure

```
quickshell_docs_mcp/
  sources/       one module per upstream source
  server.py      MCP tool definitions
  config.py      URLs, constants
  utils.py       shared helpers
tests/           offline test suite with fixtures
```

## Code Style

- Follow existing patterns in the codebase
- Use type hints for all public functions
- Write docstrings for new modules and functions
- Keep imports sorted (ruff handles this)

## Testing

- Add tests for new functionality
- Use the existing `mock_fetch` pattern for HTTP-dependent tests
- Mark live network tests with `@pytest.mark.live`

## Commit Messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

| Prefix | Use for |
|---|---|
| `feat:` | New feature or tool |
| `fix:` | Bug fix |
| `docs:` | Documentation only |
| `refactor:` | Code change that neither fixes a bug nor adds a feature |
| `chore:` | Maintenance tasks |

Examples:

```
feat(search): add fuzzy matching for type names
fix(docs): handle 404 on missing guide pages
chore(ci): update ruff to v0.8
```

## Pull Requests

- Keep PRs focused on one logical change
- Fill out the PR template completely
- Reference any related issues
- Ensure CI passes before requesting review

## Reporting Issues

- Use the issue templates when available
- Include steps to reproduce for bugs
- Specify your Python version and OS

## License

By contributing, you agree that your contributions will be licensed under the [MIT](LICENSE) License.