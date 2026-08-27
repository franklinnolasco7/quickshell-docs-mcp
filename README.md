<!-- mcp-name: io.github.franklinnolasco7/quickshell-mcp -->

# quickshell-mcp

**An MCP server that gives AI coding agents source-grounded access to Quickshell, QML, and Qt.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/quickshell-mcp?logo=pypi&logoColor=white)](https://pypi.org/project/quickshell-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/quickshell-mcp?logo=python&logoColor=white)](https://github.com/franklinnolasco7/quickshell-mcp/blob/main/pyproject.toml)
[![codecov](https://codecov.io/gh/franklinnolasco7/quickshell-mcp/graph/badge.svg)](https://codecov.io/gh/franklinnolasco7/quickshell-mcp)
[![Tests](https://img.shields.io/github/actions/workflow/status/franklinnolasco7/quickshell-mcp/ci.yml?label=Tests&logo=github)](https://github.com/franklinnolasco7/quickshell-mcp/actions/workflows/ci.yml)

---

Search APIs, discover implementation patterns, explain errors, and validate QML **before** your agent writes or runs code.

## Why

Quickshell changes quickly, and AI coding agents can generate QML from outdated or incomplete training data. `quickshell-mcp` lets agents verify APIs against current documentation, find proven implementation patterns, and validate generated QML instead of relying on memory.

> [!IMPORTANT]
> When sources disagree, official documentation always takes precedence.

## Table of Contents

- [Quick start](#quick-start)
- [What it provides](#what-it-provides)
- [Knowledge sources](#knowledge-sources)
- [Configure](#configure)
- [Tools](#tools)
- [Typical workflow](#typical-workflow)
- [Static validation](#static-validation)
- [Source priority](#source-priority)
- [Caching](#caching)
- [References](#references)
- [Limitations](#limitations)
- [License](#license)

## Quick start

```bash
pip install quickshell-mcp        # or: uvx quickshell-mcp
```

Then point your MCP client at it (see [Configure](#configure) below).

<details>
<summary>Install from source</summary>

```bash
git clone https://github.com/franklinnolasco7/quickshell-mcp
cd quickshell-mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```
</details>

<details>
<summary>Install with Nix</summary>

```bash
nix run github:franklinnolasco7/quickshell-mcp
```
</details>

<details>
<summary>Install with Docker</summary>

```bash
docker build -t quickshell-mcp .
docker run --rm -i quickshell-mcp     # speaks MCP over stdio
```
</details>

## What it provides

| | |
|---|---|
| **Quickshell docs** | Version-aware type references, guides, and changelogs |
| **Qt/QML docs** | QtQuick, Controls, Layouts, and other base types |
| **Official examples** | Working Quickshell example configurations |
| **Real-world implementations** | Searchable Caelestia and Noctalia patterns |
| **Error explanations** | Grounded diagnosis of QML and Quickshell errors |
| **QML validation** | Static checks for types, properties, signals, imports, and version compatibility |
| **Version compatibility** | Whether an API or QML snippet works on a specific Quickshell release |
| **Unified search** | Search across multiple sources in one call |

## Knowledge sources

```mermaid
flowchart LR
    A[Quickshell docs]
    B[Qt/QML docs]
    C[Official examples]
    D[Caelestia]
    E[Noctalia]
    M((quickshell-mcp))
    Agent[AI coding agent]

    A --> M
    B --> M
    C --> M
    D --> M
    E --> M
    M --> Agent

    classDef official fill:#cdeaff,stroke:#1c6dd0,stroke-width:1px,color:#0b3661
    classDef community fill:#ffe3c2,stroke:#d8871b,stroke-width:1px,color:#5c3a05
    classDef core fill:#c9f2d8,stroke:#1f9e5c,stroke-width:2px,color:#0b3d24
    classDef agent fill:#ead6ff,stroke:#8a3ff0,stroke-width:1px,color:#3a1466

    class A,B,C official
    class D,E community
    class M core
    class Agent agent
```

Official documentation is authoritative. Examples and real-world implementations provide practical reference material (see [Source priority](#source-priority)).

## Configure

**opencode** (`opencode.json`):

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

**Claude Desktop**: same JSON under `claude_desktop_config.json`, wrapped in `mcpServers`.

For HTTP transport, set `QUICKSHELL_DOCS_MCP_TRANSPORT=http` (plus optional `HOST`/`PORT`).

> [!TIP]
> Set `QUICKSHELL_DOCS_MCP_LOG=DEBUG` for verbose request logging on stderr.
>
> The `QUICKSHELL_DOCS_MCP_*` environment variable prefix is retained for backwards compatibility with earlier releases.

## Tools

#### Discovery

| Tool | What it does |
|---|---|
| `quickshell_search` | Search Quickshell type names, namespaces, and guide slugs; optionally full-text including deep search over type pages |
| `quickshell_search_all` | One-call unified search across Quickshell docs/types, Qt types, official examples, and Caelestia/Noctalia implementations |
| `quickshell_find_pattern` | Describe a feature in plain words and get matching real-world implementations with per-pattern API hints |

#### Documentation

| Tool | What it does |
|---|---|
| `quickshell_list_versions` | List published documentation versions and the latest |
| `quickshell_list_types` / `quickshell_get_type` | Browse and fetch Quickshell QML type docs |
| `quickshell_list_guide_pages` / `quickshell_get_guide_page` | Fetch usage guide pages as Markdown |
| `quickshell_about` / `quickshell_changelog` | Fetch project metadata and changelog |

#### Qt / QML

| Tool | What it does |
|---|---|
| `quickshell_list_qt_types` / `quickshell_get_qt_type` | Browse and fetch Qt-side types (QtQuick, Controls, Layouts, ...) |
| `quickshell_validate_qml` | Statically validate QML source |

#### Examples & implementations

| Tool | What it does |
|---|---|
| `quickshell_list_examples` / `quickshell_get_example` | Browse and read official example configs |
| `quickshell_search_implementations` | Search Caelestia and Noctalia for patterns (bar, OSD, IPC, ...) |
| `quickshell_get_implementation` | Read implementation files, narrowed via `find=` |

#### Debugging & session

| Tool | What it does |
|---|---|
| `quickshell_explain_error` | Explain a QML/Quickshell error and suggest a fix, grounded in actual docs |
| `quickshell_check_compatibility` | Check whether an API, type, or QML snippet is compatible with a specific Quickshell version |
| `quickshell_stats` | Session call counts and cache-hit ratio |

> Page-fetching tools accept `version="latest"` (default) or an explicit version like `"v0.3.0"`. Cache-backed tools accept `refresh=True` to bypass the 30-minute cache.

## Typical workflow

```mermaid
flowchart TD
    A[Search] --> B[Find implementation pattern]
    B --> C[Verify API]
    C --> D[Write QML]
    D --> E[Validate]
    E -->|errors| F[Fix errors]
    F --> E
    E -->|clean| G[Done]

    classDef discover fill:#cdeaff,stroke:#1c6dd0,stroke-width:1px,color:#0b3661
    classDef build fill:#ffe3c2,stroke:#d8871b,stroke-width:1px,color:#5c3a05
    classDef check fill:#c9f2d8,stroke:#1f9e5c,stroke-width:1px,color:#0b3d24
    classDef fix fill:#ffd1d1,stroke:#d13b3b,stroke-width:1px,color:#5c0b0b
    classDef done fill:#e3d6ff,stroke:#7b3ff0,stroke-width:2px,color:#2f1466

    class A,B,C discover
    class D build
    class E check
    class F fix
    class G done
```

### Example

Instead of asking an AI agent to guess how to create a workspace indicator in Quickshell, the agent can search for the API, find existing implementations, verify the requested version, generate the QML, and validate it before running it:

```mermaid
flowchart LR
    A[quickshell_search_all] --> B[quickshell_find_pattern]
    B --> C[quickshell_list_versions /<br/>quickshell_get_type]
    C --> D[generate QML]
    D --> E[quickshell_validate_qml]
    E --> F[quickshell_explain_error]

    classDef tool fill:#cdeaff,stroke:#1c6dd0,stroke-width:1px,color:#0b3661
    classDef action fill:#ffe3c2,stroke:#d8871b,stroke-width:1px,color:#5c3a05
    classDef debug fill:#ffd1d1,stroke:#d13b3b,stroke-width:1px,color:#5c0b0b

    class A,B,C tool
    class D action
    class E,F debug
```

## Static validation

`quickshell_validate_qml` performs lightweight static analysis against the same Quickshell and Qt documentation indexes used by the other tools. It can detect:

- Unknown Quickshell and Qt types
- Unknown properties, methods, and signals
- Missing imports
- Obvious type mismatches
- APIs unavailable in the requested Quickshell version

> [!TIP]
> `quickshell_validate_qml` is designed to complement `qmlls`, not replace it. Dynamic JavaScript and local component resolution are intentionally outside its scope.

```json
{"source": "PanelWindow { foo: 123 }", "version": "latest", "filename": "panel.qml"}
```

## Version compatibility

`quickshell_check_compatibility` tells you whether a Quickshell API, QML property/method/signal, type, or whole snippet works on a specific release. Pass exactly one of `api`, `type`, or `code`; pin the release with `version` (or `from_version`/`to_version` for a range).

It never concludes from the latest docs page alone: it cross-references the requested version's type index and pages plus the changelog, and returns `uncertain` rather than guessing when the evidence is insufficient. Qt/QML types (Rectangle, Item, ...) come back as `compatible` with `origin: "qt"`, because their availability is set by your Qt version, not the Quickshell one.

```json
{"api": "PanelWindow.exclusiveZone", "version": "v0.2.0"}
{"api": "Quickshell.shellRoot", "version": "v0.3.1"}
{"code": "PanelWindow { exclusiveZone: 1 }", "version": "v0.1.0"}
```

The result includes the verdict, the version evidence (earliest/latest known), any change or rename with a likely replacement, the matching changelog entry, and cited documentation URLs.

## Source priority

When sources disagree, in order of authority:

1. Official Quickshell documentation
2. Official Qt documentation
3. Official Quickshell examples
4. Real-world implementations

Real-world implementations are practical references, not authoritative API definitions.

## Caching

Documentation indexes are cached locally under `~/.cache/quickshell-mcp`.

| Cache type | TTL |
|---|---|
| Fetched pages (in-memory/disk) | 30 minutes |
| Bulk documentation indexes (disk) | 30 days |

Use `refresh=True` to bypass the short-lived cache where supported. The cache location and disk TTL can be configured with the existing `QUICKSHELL_DOCS_MCP_*` environment variables.

## References

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

- Validation is static and heuristic; it complements `qmlls`.
- Dynamic JavaScript and local component resolution are limited.
- Official examples may target different Quickshell versions.
- Deep documentation searches can be slower on a cold cache.
- Real-world implementations are references and may contain outdated patterns.

## License

[MIT](LICENSE)