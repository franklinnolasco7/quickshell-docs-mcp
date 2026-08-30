# AGENTS.md

Guidance for AI agents (Claude Code, opencode, etc.) working on this repository.

## Quick start

- `pip install -e '.[dev]'` for the venv (or `nix develop` for the CI-equivalent shell)
- `pytest -q` for the offline suite; see Build/test commands below for the full list

## Scope

Governs agent behavior within `quickshell-mcp` only. This is a single-author personal tool, so keep changes proportional: no release automation, no features without a stated consumer, no dependencies without a reason.

## Project overview

An MCP server that serves live Quickshell documentation from quickshell.org so LLMs read real docs instead of hallucinating API surface (the API has shifted heavily between releases). Three companion sources round it out: Qt type docs from doc.qt.io (base types like Rectangle that Quickshell configs import but quickshell.org doesn't document), the official quickshell-examples repo via its Gitea API, and real-world QML shells (Caelestia, Noctalia, end-4's dots-hyprland) indexed from their GitHub repos. Everything is fetched at query time; nothing is hardcoded.

## Project structure

- `quickshell_mcp/`, the package itself:
  - `config.py`: URLs, repo identities, strip-selector lists, TTL/retry constants
  - `caches.py`: 30-minute in-memory cache per fetch, plus a disk layer that persists built indexes (guide/type/qt) across restarts (30-day default TTL); `QUICKSHELL_DOCS_MCP_DISK_CACHE` env var to disable/redirect
  - `utils.py`: logging, HTTP client, `_fetch_raw` (retry + stats), citation prefix; domain modules call `utils._fetch_raw` by module attribute so tests monkeypatch one seam
  - `versions.py`, `extraction.py`: runtime version discovery; HTML→Markdown with per-source strip rules
  - `sources/`: shared-services layer — data-source access, index building, parsing, and low-level analysis (`docs`, `qt_docs`, `examples`, `implementations`, `compat`, `migrate`, `validate`, `generate`, `assistant`, `explain_error`, `find_pattern`, `search_all`); no MCP decorators here and it never imports `capabilities/` (dependencies point down)
  - `capabilities/`: capability/domain layer between the tools and the sources — one module per capability (`knowledge`, `validation`, `generation`, `migration`, `debugging`, `assistant`), each declaring `CAPABILITY_NAME`/`CAPABILITY_TOOLS`/`CAPABILITY_DEPENDS_ON` and re-exporting the source entry points; `registry.py` aggregates the tool→capability map and a cycle-checked `dependency_order()`. Planned-but-unimplemented capabilities (project, runtime, inspection, testing, performance) are registry entries only — never empty placeholder modules
  - `server.py`: FastMCP instance, every `@mcp.tool()` wrapper + docstring (the trigger surface), `main()`, and re-exports of helper names so tests keep addressing `srv.<helper>`; tool logic is routed through `capabilities/`
- `tests/`: offline pytest suite driven by saved snapshots in `tests/fixtures/`. `conftest.py` provides `mock_fetch` (patches `utils._fetch_raw`), `docs_fixture_urls`, `http_404`, and an autouse cache/stats reset.
- `scripts/smoke_test.py`: end-to-end stdio client; drives the server like a real MCP session against the live sites.
- `flake.nix` / `Dockerfile` / `.github/workflows/ci.yml`: packaging + CI. `CLAUDE.md` is a symlink to this file.

## Design principles (do not violate)

1. **Never hardcode a Quickshell version.** `"latest"` resolves at runtime by regex-scanning pages for `/docs/vX.Y.Z/` links. A hardcoded version string outside tests/fixtures is a bug.
2. **Regex over CSS selectors for structural discovery.** `VERSION_RE`, `TYPE_LINK_RE`, `GUIDE_LINK_RE` scan raw HTML for URL patterns, not DOM structure; quickshell.org is an Astro site that can redesign. Keep this pattern for new discovery logic.
3. **Every fetched page returns its source URL** (`_with_source`). Don't strip it from new fetch-based tools.
4. **Generation ships only with verification.** `quickshell_generate_component` may synthesize QML, but only because every emitted type/property is checked against the versioned docs via the compat machinery + static validator before return (its `verified_surface`). Any new generate-style tool must keep that checklist; unverifiable APIs are surfaced, never silently emitted.
5. **Tool docstrings are the trigger surface.** Models reach for tools by matching phrasing against docstrings (see `quickshell_search`'s keyword map). Write docstrings for how users ask, not what the code does.
6. **Fail loudly with suggestions.** A 404 raises `ValueError` with did-you-mean candidates from `_build_index`, never silent empty results.

## Coding guidelines (write/review code first)

**Naming.** Prefer descriptive names over abbreviations (`enableBluetoothAutoConnect`, not `btAuto`). Optimize for readability: names are read far more often than typed.

**Comments.** Explain *why*, not *what*. Keep comments brief. Comment only edge cases, workarounds, non-obvious logic, or important constraints. Don't comment self-explanatory code. Match the comment style already used elsewhere in the codebase (formatting, tone, placement). Look at nearby files before writing a comment, rather than defaulting to a generic style. If the codebase has no established comment convention, keep comments short and placed directly above the code they explain.

**Code quality.**

- Handle realistic edge cases: invalid input, empty values, missing data, unexpected states, boundaries, failure paths.
- Skip defensive code for impossible scenarios unless there's a clear reason.
- Fail clearly and predictably; never silently swallow errors. Preserve context when propagating them.
- Validate external or untrusted input at system boundaries. Treat filesystem paths, commands, and network data as untrusted.
- Keep functions, classes, and modules focused.
- Avoid unnecessary duplication, but don't build abstractions just to remove a few repeated lines.
- Prefer straightforward control flow over deep nesting, clever one-liners, or unnecessary indirection.
- Use strong typing; avoid `any`, unchecked casts, magic values, and suppressions unless justified.
- Avoid unnecessary dependencies and obvious performance problems (repeated I/O, unnecessary computation, excessive allocations).
- Clean up resources: files, processes, connections, timers, subscriptions.
- Account for race conditions, cancellation, ordering, and shared state in concurrent or async code.
- Preserve existing behavior and compatibility unless the change intentionally requires otherwise.
- Add or update tests for behavior changes, especially edge cases and regressions.
- Remove dead code, obsolete branches, unused imports, and commented-out code.
- Prefer minimal, focused changes over unrelated refactoring; follow existing project conventions unless there's a strong reason to improve them.
- Before finishing, review for correctness, edge cases, error paths, unnecessary complexity, naming, duplication, and unintended side effects.

## Test harness

The suite is offline by construction: `mock_fetch` replaces `_fetch_raw`, serving saved real-page snapshots (`tests/fixtures/*.html`) or raising on unexpected URLs. No test touches the network unless marked `live`.

Rules for test cases in this repo:

1. **Test the private helpers, not the decorated tools**: the helper functions in `sources/*.py` plus `list_versions`. They hold the logic; `@mcp.tool()` wrappers are thin (recording + delegation). Exception: stats assertions go through the tool functions, since `_record_tool` lives there.
2. **Exact-match fake fetches over prefix matching** when a test cares *which* URL was fetched. Prefix matching once served the guide-index page for a typo'd slug and masked a bug. Use `url in mapping` or explicit equality.
3. **Every new tool needs three tests**: happy path (shape of returned dict/str), failure path (404 → friendly `ValueError` with suggestions), and an entry added to `expected` in `scripts/smoke_test.py`.
4. **Fixtures are committed real HTML.** If quickshell.org's markup changes and discovery/index tests break, re-snapshot deliberately and inspect the diff; it tells you exactly which regex died:
   ```bash
   rtk curl -sL https://quickshell.org/about/ -o tests/fixtures/about.html
   rtk curl -sL https://quickshell.org/docs/v0.3.1/guide/ -o tests/fixtures/guide_index.html
   ```
5. **Live tests are for fetch-proof only.** Mark with `@pytest.mark.live`; they self-skip unless `QUICKSHELL_LIVE_TEST=1`. Never use them to test logic; they're slow, order-dependent, and can flake on site hiccups.
6. **Don't clear caches manually.** The autouse conftest fixture resets `_cache`, `_TOOL_CALLS`, and `_FETCH_STATS` between tests.
7. **Code-quality gates are tests too** (`tests/test_code_quality.py`: ruff/format/mypy). They probe before running and skip cleanly where a tool is broken (e.g. glibc-ruff wheel on NixOS). A skip is NOT a pass; see Definition of done.

## Build, test, and development commands

```bash
pip install -e '.[dev]'                      # venv setup
pytest -q                                    # offline suite (+ quality-gate tests)
QUICKSHELL_LIVE_TEST=1 pytest -m live   # opt-in live verification
ruff check . && ruff format --check .        # lint + formatting
mypy quickshell_mcp                     # types
.venv/bin/python scripts/smoke_test.py       # end-to-end stdio vs live site
nix develop                                  # dev shell with everything CI uses
nix build && nix flake check                 # package + flake evaluation
```

`QUICKSHELL_DOCS_MCP_LOG=DEBUG` logs every HTTP request to stderr.

## Definition of done

Run checks when warranted, not reflexively. If none apply, say so instead of running them anyway.

1. `pytest -q`: after any change to the package or `tests/`. Skip for pure docs/comments edits.
2. Direct lint/type run (`nix develop -c sh -c 'ruff check . && ruff format --check . && mypy quickshell_mcp/'`): when making a non-trivial edit to the package, or whenever you intend to claim CI-green. The venv's pip-installed ruff may be unusable on NixOS (dynamic-linking); the quality-gate *tests* will skip rather than fail, so don't read a skip as passing.
3. `scripts/smoke_test.py`: after touching the tool surface (new tool, changed signature/docstring), `main()`/transport, or anything stdio-related. Requires network; keeps stdin open internally because closing the pipe mid-request makes the mcp transport abort in-flight work (looks like a hang, isn't).
4. Live pytest (`QUICKSHELL_LIVE_TEST=1 pytest -m live`): when changing `_fetch_raw`, extraction, version discovery, or URL construction. Proves the real site still agrees with your assumptions.
5. `git add -A && nix build && nix flake check`: after touching `flake.nix` or `pyproject.toml`. Staging is required because the flake evaluates the git tree, not the worktree.
6. `python -m build --no-isolation && twine check dist/*` (in `nix develop`): after metadata changes in `pyproject.toml`.
7. Always self-review the diff against the design principles above before reporting done.

**When a check fails and the fix isn't obvious:** stop and report the exact error plus which check produced it. Don't retry speculative variations.

## Important implementation notes

1. **`mcp` is pinned `>=1.2.0,<2.0.0` deliberately.** The 2.x line removed `FastMCP`. Do not bump without rewriting the server and verifying end-to-end (smoke script + live tests).
2. **Trailing slashes are required and verified for quickshell.org only**: it 308-redirects non-slash doc URLs; all quickshell.org fetches request the slash form directly (`_guide_page`/`_type_page`), and a test asserts the fetched URL shape. doc.qt.io and the Gitea API use their own URL shapes; don't apply the slash rule there.
3. **There is no canonical `/docs/` index; it 404s.** Version discovery scans `/about/` first (it links every published version), then `/docs/`, then `/`. Don't "fix" this back to fetching `/docs/`.
4. **Extraction is per-source.** quickshell.org strips `[class*=sidebar]` junk; doc.qt.io must NOT use that rule because its page body lives in `article.b-sidebar__content...` (see `_QT_STRIP_SELECTORS`). When adding a source, verify extraction against a real snapshot before trusting it.
5. **CI pipeline** (`.github/workflows/ci.yml`): flake check → nix build + dist/twine → lint → offline pytest with coverage → Dockerfile validation; live-smoke runs only on manual dispatch. If you add a check locally, wire the equivalent into CI.
6. **Implementation references are not documentation.** Caelestia/Noctalia/dots-hyprland results carry `kind: real-world implementation` and every tool docstring says the docs win on API disputes. Noctalia's ref is pinned to its `legacy-v4` branch deliberately (its `main` moved to a C++ compositor); a GitHub `truncated: true` tree response is refused rather than silently under-indexed. dots-hyprland's QML root is nested under `dots/.config/quickshell/ii/` and paths are reported relative to it.

## ProjectContext (`quickshell_mcp/sources/project.py`)

A reusable internal abstraction for representing a Quickshell project on disk.
It is **not** a capability or an MCP tool — it is shared infrastructure in the
`sources/` layer that capabilities consume.

### Consumer pattern

```python
from ..sources.project import _build_project_context

ctx = _build_project_context("/path/to/shell")
info = ctx.discover({"qml_files", "imports", "compositor"})
# info = {"qml_files": [...], "imports": [...], "compositor": ["Hyprland"], ...}
# ctx.detection_status("compositor") -> "inferred"
```

### Available fields (all lazy)

| Field | Status | Description |
|-------|--------|-------------|
| `qml_files` | detected | Every `*.qml` under the project root |
| `js_files` | detected | Every `*.js` under the project root |
| `entrypoints` | detected | QML files whose root object is a window type |
| `imports` | detected | All QML import statements across every file |
| `quickshell_modules` | detected / unknown | Imports starting with `Quickshell` |
| `quickshell_version` | inferred / unknown | Version string from `Quickshell` import versions |
| `qt_version` | inferred / unknown | Version string from `Qt*` module import versions |
| `compositor` | inferred / unknown | Quickshell integration namespaces (e.g. `Hyprland`) |
| `config_paths` | detected | Config files at the project root |
| `dependencies` | detected | All distinct import modules |
| `conventions` | inferred | Naming, layout, structure patterns |
| `components` | detected / unknown | QML files under `components/` or `widgets/` dirs |
| `services` | detected / inferred / unknown | `Quickshell.Services.*` imports + `*Service`-named objects |
| `runtime_dependencies` | detected / inferred / unknown | Runtime-hook QML types (Process, IpcHandler, ...) + config keyword hints |
| `environment` | inferred / unknown | `process.env.*` variables referenced in QML |

### Status semantics

- **detected** — directly observed in the filesystem (file lists, import statements)
- **inferred** — derived from detected data (version strings, compositor, conventions)
- **unknown** — no data could be found (no QML files, no version-bearing imports)

### Design rules

- **Never fabricates.** A field without data is `None` / `[]` with status `"unknown"`.
- **Lazy by default.** `discover({needs})` computes only the requested fields.
- **Instance-cached.** Repeated `discover()` calls on the same `_ProjectContext` reuse precomputed values.
- **Shared-cached.** The expensive file-tree scan is cached in the 30-minute in-memory cache keyed by the resolved root path, so a second `_build_project_context` for the same directory skips re-scanning.
- **No HTTP.** ProjectContext is purely local-filesystem: it walks the tree and parses QML text. Any version resolution against the live site is the caller's responsibility.
- **Compositor-independent.** The compositor field reports Quickshell integration namespaces (e.g. `Hyprland`) from `Quickshell.<Name>` imports after excluding core namespaces. No compositor-name list is hardcoded.

### Adding a new field

1. Add the field name to `_ALL_FIELDS` in `project.py`.
2. Add a `_discover_<name>` method that calls `_set(...)` or `_set_inferred(...)`.
3. Call `_scan()` for the raw file/import data; derive your field from it.
4. Add a test in `tests/test_project.py`.

## MCP client configuration

```json
{
  "mcp": {
    "quickshell": {
      "type": "local",
      "command": ["/absolute/path/to/quickshell-mcp/.venv/bin/quickshell-mcp"],
      "enabled": true
    }
  }
}
```

HTTP transport alternative: `QUICKSHELL_DOCS_MCP_TRANSPORT=http` (+ `HOST`/`PORT`). Adjust JSON shape to the actual client schema.

## Commit guidelines

Scoped Commits (`<scope>: <description>`). Small diffs, one logical change per commit. Never auto-commit; the user runs git commands (staging for flake verification is fine).

- `<scope>` — the module, subsystem, or area touched (e.g. `docs`, `qt-docs`, `examples`, `implementations`, `compat`, `migrate`, `validate`, `generate`, `server`, `sources`, `tests`, `ci`, `flake`, `packaging`, `config`, `caches`, `extraction`, `versions`, `utils`, `scripts`, `readme`). Puts what the change touches up front; use `treewide` for whole-tree changes.
- `<description>` — imperative mood, ≤72 chars, no trailing period.
- Body (optional) — details when the subject can't cover the change; bullet the parts.
- Trailers (optional) — additional metadata (`Closes #N`, `Co-authored-by: N`).
- Multi-area changes: comma-separate scopes (`ci,packaging: ...`) or use a broader scope.
- Special commits (reverts, merges, release) can use whatever format fits.

**Version-bump trailer (required for auto-release):**

> ⚠️ A semantic-release CI runs on every merge to `main`. Every commit defaults to a **patch** release. A new feature/tool must signal a minor bump explicitly — there is no type-prefix heuristic anymore. Forgetting `Semver: minor` on a new tool means no minor release.

- `Semver: minor` — new feature, tool, or user-facing addition
- `Semver: major` — breaking API/config change (preferred over `BREAKING CHANGE:`)

Both are matched as trailing lines in the commit body, e.g. a final `Semver: minor` line. Matching requires a literal colon after `Semver:`/`BREAKING CHANGE:`, so prose that merely *mentions* "BREAKING CHANGE" or "Semver" never triggers a bump.

Example:

```
server: add quickshell_search_all tool

Runs one query across every source group.

Semver: minor
Closes #24
```
