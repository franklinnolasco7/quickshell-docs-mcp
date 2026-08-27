# AGENTS.md

Guidance for AI agents (Claude Code, opencode, etc.) working on this repository.

## Scope

Governs agent behavior within `quickshell-mcp` only. This is a single-author personal tool, so keep changes proportional: no release automation, no features without a stated consumer, no dependencies without a reason.

## Project overview

An MCP server that serves live Quickshell documentation from quickshell.org so LLMs read real docs instead of hallucinating API surface (the API has shifted heavily between releases). Two companion sources round it out: Qt type docs from doc.qt.io (base types like Rectangle that Quickshell configs import but quickshell.org doesn't document) and the official quickshell-examples repo via its Gitea API. Everything is fetched at query time; nothing is hardcoded.

## Project structure

- `quickshell_mcp/`, the package itself:
  - `config.py`: URLs, repo identities, strip-selector lists, TTL/retry constants
  - `caches.py`: 30-minute in-process cache
  - `utils.py`: logging, HTTP client, `_fetch_raw` (retry + stats), citation prefix; domain modules call `utils._fetch_raw` by module attribute so tests monkeypatch one seam
  - `versions.py`, `extraction.py`: runtime version discovery; HTML→Markdown with per-source strip rules
  - `sources/`: one logic module per upstream (`docs`, `qt_docs`, `examples`, `implementations`); no MCP decorators here
  - `server.py`: FastMCP instance, every `@mcp.tool()` wrapper + docstring (the trigger surface), `main()`, and re-exports of helper names so tests keep addressing `srv.<helper>`
- `tests/`: offline pytest suite driven by saved snapshots in `tests/fixtures/`. `conftest.py` provides `mock_fetch` (patches `utils._fetch_raw`), `docs_fixture_urls`, `http_404`, and an autouse cache/stats reset.
- `scripts/smoke_test.py`: end-to-end stdio client; drives the server like a real MCP session against the live sites.
- `flake.nix` / `Dockerfile` / `.github/workflows/ci.yml`: packaging + CI. `CLAUDE.md` is a symlink to this file.

## Design principles (do not violate)

1. **Never hardcode a Quickshell version.** `"latest"` resolves at runtime by regex-scanning pages for `/docs/vX.Y.Z/` links. A hardcoded version string outside tests/fixtures is a bug.
2. **Regex over CSS selectors for structural discovery.** `VERSION_RE`, `TYPE_LINK_RE`, `GUIDE_LINK_RE` scan raw HTML for URL patterns, not DOM structure; quickshell.org is an Astro site that can redesign. Keep this pattern for new discovery logic.
3. **Every fetched page returns its source URL** (`_with_source`). Don't strip it from new fetch-based tools.
4. **Scaffold-style generation is out of scope.** The server documents; it does not synthesize configs. Generated-code tools were removed deliberately; point users at `quickshell_get_example` instead. If a generation need ever returns, it must ship a verification checklist like the old scaffold did.
5. **Tool docstrings are the trigger surface.** Models reach for tools by matching phrasing against docstrings (see `quickshell_search`'s keyword map). Write docstrings for how users ask, not what the code does.
6. **Fail loudly with suggestions.** A 404 raises `ValueError` with did-you-mean candidates from `_build_index`, never silent empty results.

## Test harness

The suite is offline by construction: `mock_fetch` replaces `_fetch_raw`, serving saved real-page snapshots (`tests/fixtures/*.html`) or raising on unexpected URLs. No test touches the network unless marked `live`.

Rules for test cases in this repo:

1. **Test the private helpers, not the decorated tools**: `_guide_page`, `_type_page`, `_build_index`, `_build_qt_index`, `_search_guide_content`, `_examples_listing`, `list_versions`. They hold the logic; `@mcp.tool()` wrappers are thin (recording + delegation). Exception: stats assertions go through the tool functions, since `_record_tool` lives there.
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
6. **Implementation references are not documentation.** Caelestia/Noctalia results carry `kind: real-world implementation` and every tool docstring says the docs win on API disputes. Noctalia's ref is pinned to its `legacy-v4` branch deliberately (its `main` moved to a C++ compositor); a GitHub `truncated: true` tree response is refused rather than silently under-indexed.

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

Conventional Commits (`feat:`, `fix:`, `docs:`, `refactor:`, `chore:`). Small diffs, one logical change per commit. Never auto-commit; the user runs git commands (staging for flake verification is fine).
