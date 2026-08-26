# quickshell-docs-mcp

Live Quickshell documentation for AI coding agents.

[![PyPI](https://img.shields.io/pypi/v/quickshell-docs-mcp?logo=pypi&logoColor=white&cacheSeconds=300)](https://pypi.org/project/quickshell-docs-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/quickshell-docs-mcp?logo=python&logoColor=white&cacheSeconds=300)](https://github.com/franklinnolasco7/quickshell-docs-mcp/blob/main/pyproject.toml)
[![codecov](https://codecov.io/gh/franklinnolasco7/quickshell-docs-mcp/graph/badge.svg)](https://codecov.io/gh/franklinnolasco7/quickshell-docs-mcp)

---

An MCP server that gives AI agents live access to the official [Quickshell](https://quickshell.org) documentation, so they stop guessing QML API names from stale training data.

Also included:

- Qt base types (`Rectangle`, `RowLayout`, ...) from doc.qt.io
- Official example configs from [quickshell-examples](https://git.outfoxxed.me/quickshell/quickshell-examples)
- Real-world implementations, searchable across the Caelestia and Noctalia shells

Every result carries its source URL. When implementations disagree with the docs, the docs win.

## Table of Contents

- [Install](#install)
- [Configure](#configure)
- [Tools](#tools)
- [Source Hierarchy](#source-hierarchy)
- [References](#references)
- [Development](#development)
- [Limitations](#limitations)
- [License](#license)

## Install

```bash
pip install quickshell-docs-mcp        # or: uvx quickshell-docs-mcp
```

<details>
<summary>From source</summary>

```bash
git clone https://github.com/franklinnolasco7/quickshell-docs-mcp
cd quickshell-docs-mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

</details>

<details>
<summary>Nix</summary>

```bash
nix run github:franklinnolasco7/quickshell-docs-mcp
```

</details>

<details>
<summary>Docker</summary>

```bash
docker build -t quickshell-docs-mcp .
docker run --rm -i quickshell-docs-mcp     # speaks MCP over stdio
```

</details>

## Configure

**opencode** (`opencode.json`):

```json
{
  "mcp": {
    "quickshell-docs": {
      "type": "local",
      "command": ["/absolute/path/to/quickshell-docs-mcp/.venv/bin/quickshell-docs-mcp"],
      "enabled": true
    }
  }
}
```

**Claude Desktop**: same JSON under `claude_desktop_config.json`, wrapped in `mcpServers`. For HTTP transport, set `QUICKSHELL_DOCS_MCP_TRANSPORT=http` (plus optional `HOST`/`PORT`).

> Set `QUICKSHELL_DOCS_MCP_LOG=DEBUG` for verbose request logging on stderr.
> Bulk doc indexes persist on disk (`~/.cache/quickshell-docs-mcp`, 30-day freshness). Relocate or disable with `QUICKSHELL_DOCS_MCP_DISK_CACHE`, re-tune with `QUICKSHELL_DOCS_MCP_DISK_TTL_HOURS`.

## Tools

| Tool | What it does |
|---|---|
| `quickshell_search` | Search type names, guide slugs, optionally full text including deep search over type pages. Call this before writing QML from memory. |
| `quickshell_search_all` | One-call unified search across Quickshell docs/types, Qt types, official examples, and Caelestia/Noctalia implementations; grouped by source, ranked by relevance |
| `quickshell_find_pattern` | Describe what you want to build ("Spotlight-style launcher") and get matching real-world implementations with per-pattern API hints and cross-project grouping |
| `quickshell_list_versions` | Published doc versions and the latest |
| `quickshell_list_types` / `quickshell_get_type` | Browse and fetch Quickshell QML type docs |
| `quickshell_list_guide_pages` / `quickshell_get_guide_page` | Usage Guide pages as Markdown |
| `quickshell_about` / `quickshell_changelog` | About and Changelog pages |
| `quickshell_list_qt_types` / `quickshell_get_qt_type` | Qt-side types (QtQuick, Controls, Layouts, ...) |
| `quickshell_list_examples` / `quickshell_get_example` | Official example configs |
| `quickshell_search_implementations` | Find bar/OSD/IPC/... patterns in Caelestia or Noctalia |
| `quickshell_get_implementation` | Read those files, narrowed via `find=` |
| `quickshell_explain_error` | Explain a QML error grounded in live docs — verifies type/property existence and suggests fixes |
| `quickshell_stats` | Session call counts and cache-hit ratio |

Page-fetching tools accept `version="latest"` (default) or an explicit version like `"v0.3.0"`. Cache-backed tools accept `refresh=True` to bypass the 30-minute cache.

## Source Hierarchy

1. Official documentation (quickshell.org, doc.qt.io), authoritative
2. Official examples, next in line
3. Caelestia / Noctalia results, practical references labeled `real-world implementation`

## References

Data comes from these upstream sources:

| Source | URL | What it provides |
|---|---|---|
| Quickshell docs | https://quickshell.org | Type references, usage guide, changelog |
| Qt docs | https://doc.qt.io/qt-6 | QtQuick base types (Rectangle, RowLayout, etc.) |
| Quickshell examples | https://git.outfoxxed.me/quickshell/quickshell-examples | Official example configs |
| Caelestia shell | https://github.com/caelestia-dots/shell | Real-world implementation references |
| Noctalia shell | https://github.com/noctalia-dev/noctalia (legacy-v4) | Real-world implementation references |

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, workflow, and how to submit changes.

## Limitations

- Deep type-page search (`include_type_pages=True`) fetches every type page once per machine (~15s cold, then cached on disk for 30 days across sessions; `refresh=True` forces a refetch). Plain name search stays instant.
- Example configs may target a different Quickshell version than yours; listings include a `last_modified` date so you can judge their age.

## License

[MIT](LICENSE)
