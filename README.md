<!-- mcp-name: io.github.franklinnolasco7/quickshell-mcp -->

# quickshell-mcp

**An MCP server that connects AI coding agents to live Quickshell, QML, and Qt documentation.**

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![PyPI](https://img.shields.io/pypi/v/quickshell-mcp?logo=pypi&logoColor=white)](https://pypi.org/project/quickshell-mcp/)
[![MCP Registry](https://img.shields.io/badge/MCP%20Registry-active-blue)](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.franklinnolasco7%2Fquickshell-mcp/versions/latest)
[![Python](https://img.shields.io/pypi/pyversions/quickshell-mcp?logo=python&logoColor=white)](https://github.com/franklinnolasco7/quickshell-mcp/blob/main/pyproject.toml)
[![codecov](https://codecov.io/gh/franklinnolasco7/quickshell-mcp/graph/badge.svg)](https://codecov.io/gh/franklinnolasco7/quickshell-mcp)
[![Tests](https://img.shields.io/github/actions/workflow/status/franklinnolasco7/quickshell-mcp/ci.yml?label=Tests&logo=github)](https://github.com/franklinnolasco7/quickshell-mcp/actions/workflows/ci.yml)

---

Search APIs, discover implementation patterns, explain errors, and validate QML **before** your agent writes or runs code.

## Why

Quickshell changes quickly, and AI coding agents can generate QML from outdated or incomplete training data. `quickshell-mcp` lets agents verify APIs against current documentation, find existing implementation patterns, and validate generated QML instead of guessing from memory.

> [!IMPORTANT]
> When sources disagree, official documentation always takes precedence.

## Table of Contents

- [Quick start](#quick-start)
- [What it provides](#what-it-provides)
- [Knowledge sources](#knowledge-sources)
- [Configure](#configure)
- [Tools](#tools)
- [Typical workflow](#typical-workflow)
- [Advanced usage](#advanced-usage)
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

Also installable via the [Model Context Protocol Registry](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.franklinnolasco7%2Fquickshell-mcp/versions/latest).

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
| **Real-world implementations** | Searchable Caelestia, Noctalia, and dots-hyprland patterns |
| **Error explanations** | Grounded diagnosis of QML and Quickshell errors |
| **QML validation** | Static checks for types, properties, signals, imports, and version compatibility |
| **Version compatibility** | Whether an API or QML snippet works on a specific Quickshell release |
| **Migration** | Analyze what a QML config must change to keep working after an upgrade |
| **Component generation** | Minimal, source-grounded QML components from a plain-language description |
| **Unified search** | Search across multiple sources in one call |
| **Coding assistant** | One plain-language request routed through the right tools, returning a structured, source-grounded result |

## Knowledge sources

```mermaid
flowchart LR
    A[Quickshell docs]
    B[Qt/QML docs]
    C[Official examples]
    D[Caelestia]
    E[Noctalia]
    F[dots-hyprland]
    M((quickshell-mcp))
    Agent[AI coding agent]

    A --> M
    B --> M
    C --> M
    D --> M
    E --> M
    F --> M
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
| `quickshell_search_all` | One-call unified search across Quickshell docs/types, Qt types, official examples, and all implementation shells |
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
| `quickshell_search_implementations` | Search Caelestia, Noctalia, and dots-hyprland for patterns (bar, OSD, IPC, ...) |
| `quickshell_get_implementation` | Read implementation files, narrowed via `find=` |

#### Debugging & session

| Tool | What it does |
|---|---|
| `quickshell_explain_error` | Explain a QML/Quickshell error and suggest a fix, grounded in actual docs |
| `quickshell_check_compatibility` | Check whether an API, type, or QML snippet is compatible with a specific Quickshell version |
| `quickshell_migrate` | Analyze what a QML config must change to keep working after a Quickshell upgrade |
| `quickshell_generate_component` | Generate a minimal QML component from a plain-language description, with every API verified against the docs |
| `quickshell_coding_assistant` | Route a plain-language development request (build, debug, migrate, adapt, research) through the right tools and get a structured, source-grounded result |
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
    C --> D[quickshell_generate_component]
    D --> E[quickshell_validate_qml]
    E --> F[quickshell_explain_error]

    classDef tool fill:#cdeaff,stroke:#1c6dd0,stroke-width:1px,color:#0b3661
    classDef action fill:#ffe3c2,stroke:#d8871b,stroke-width:1px,color:#5c3a05
    classDef debug fill:#ffd1d1,stroke:#d13b3b,stroke-width:1px,color:#5c0b0b

    class A,B,C tool
    class D,E action
    class F debug
```

## Advanced usage

<details>
<summary><b>Static validation, version compatibility, migration, component generation, and the coding assistant</b>: catch bad QML, verify API support per release, plan upgrades, generate components, or route a whole development task through the assistant</summary>

### Static validation

`quickshell_validate_qml` checks QML against the same Quickshell and Qt documentation indexes the other tools use. It catches:

- Unknown Quickshell and Qt types
- Unknown properties, methods, and signals
- Missing imports
- Obvious type mismatches
- APIs unavailable in the requested Quickshell version

> `quickshell_validate_qml` complements `qmlls`; it does not replace it. Dynamic JavaScript and local component resolution are outside its scope.

```json
{"source": "PanelWindow { foo: 123 }", "version": "latest", "filename": "panel.qml"}
```

### Version compatibility

`quickshell_check_compatibility` checks whether a Quickshell API, QML property/method/signal, type, or whole snippet works on a specific release. Pass one of `api`, `type`, or `code`; choose the release with `version` (or use `from_version`/`to_version` for a range).

It does not judge from the latest docs page alone. It cross-references the requested version's type index and pages plus the changelog, and returns `uncertain` when the evidence is not enough. Qt/QML types (Rectangle, Item, ...) show as `compatible` with `origin: "qt"`, because your Qt version sets their availability, not the Quickshell one.

```json
{"api": "PanelWindow.exclusiveZone", "version": "v0.2.0"}
{"api": "Quickshell.shellRoot", "version": "v0.3.1"}
{"code": "PanelWindow { exclusiveZone: 1 }", "version": "v0.1.0"}
```

The result includes the verdict, the version evidence (earliest/latest known), any rename or change with a likely replacement, the matching changelog entry, and cited documentation URLs.

### Migrating between versions

`quickshell_migrate` analyzes what a QML config must change to keep working when upgrading from one Quickshell version to another. Pass the QML source (or a single `api`/`type`), plus `from_version` and `to_version` (both required, ordered oldest to newest).

It reports every removed, renamed, deprecated, or changed API with severity, location, the old and new API, why it must change, a suggested migration, confidence, and a cited source. It also scans the breaking-change changelog entries between the versions that mention the referenced symbols, so a rename that landed at an intermediate release is reported with the version it landed in. Findings are classified `definite` (backed by the docs or changelog), `likely` (documented but low-impact, e.g. deprecation), or `manual_review` (evidence suggests a change but the exact migration is not provable).

The tool analyzes and recommends; it never rewrites code or files.

```json
{
  "code": "Quickshell { shellRoot: \"/tmp\" }\nPanelWindow { exclusiveZone: 1 }",
  "from_version": "v0.1.0",
  "to_version": "v0.3.1"
}
```

The report includes the overall verdict (`compatible`, `changes_required`, `uncertain`), the per-issue findings, and an ordered migration plan.

### Component generation

`quickshell_generate_component` turns a plain-language description into a minimal QML component, e.g. "Create a Hyprland workspace indicator", "animated volume OSD", "top bar with workspaces, clock and system tray", "popup control center", or "notification popup".

```json
{"description": "volume OSD", "version": "latest", "compositor": "hyprland"}
```

The generator searches for the request (using the same search and pattern tools as the rest), builds a small component from the section templates, then checks every Quickshell type and property/method it references against the requested version with `quickshell_check_compatibility` and runs the assembled QML through `quickshell_validate_qml`. An API that cannot be verified is shown in the result, not silently emitted, so the output never passes off an unverified API as valid.

The result includes the generated QML plus:

- `dependencies`: imports, required Quickshell types, and Qt types
- `verified_surface`: the documented properties/methods/signals of every type the component uses, so you can rewrite the QML against verified members
- `integration`: compositor and external-service requirements (Hyprland socket, PipeWire, a notification daemon, ...)
- `verification`: per-API compatibility verdicts and an overall `verified`/`unverified` flag
- `validation`: the diagnostics from the static validator
- `references`: documentation, official examples, and real-world implementations to compare against
- `assumptions`: the conservative choices made (default palette, unrecognized compositor, requested windows that were not embedded)

`compositor="hyprland"` generates Hyprland-specific types; any other value is noted and generates no compositor-specific code. A request that matches no template still returns `verified_surface` plus `references`, so you can compose the component yourself. Each generated file contains one top-level window: if a request mentions several windows (such as a bar and a notification popup), the primary one is generated and the rest are listed under `assumptions` instead of being nested. The tool writes nothing to disk.

### Coding assistant

`quickshell_coding_assistant` is an orchestration layer over the other tools, for tasks that span several of them. Give it one plain-language development request and it runs a fixed pipeline of stages: search, verify, generate, validate, migrate, orchestrate. Each stage activates only the tools the request needs. The result is structured and source-grounded, with sections for understanding, relevant APIs, recommended approach, implementation references, compatibility, validation, remaining issues, sources, and a terminal `grounded_result`.

```json
{"request": "Build a Hyprland workspace bar"}
{"request": "Why is this PanelWindow failing?", "code": "PanelWindow { foo: 1 }"}
{"request": "Migrate this shell from v0.2 to v0.3", "from_version": "v0.2.0", "to_version": "v0.3.1"}
{"request": "Find an implementation of a volume OSD and adapt the pattern"}
```

Requests map to five intents, each running the relevant pipeline stages:

- **build** ("build/add/make a ...") delegates the search and verify stages to `quickshell_generate_component`, which runs them internally, and its validated QML becomes `grounded_result`.
- **debug** ("why is X failing?", "fix this error") runs search (`quickshell_explain_error`) and verify (relevant type page + compatibility), then validate (`quickshell_validate_qml`); `grounded_result` is the diagnosis and fix.
- **migrate** ("migrate/upgrade from vX to vY") runs search (breaking-change changelog when no code is given), validate against the target version, and migrate (`quickshell_migrate`); `grounded_result` is the ordered migration plan.
- **pattern** ("find an implementation ... and adapt it") runs search (`quickshell_find_pattern`, with a short excerpt of the top implementation) and verify (compatibility of the hinted APIs); `grounded_result` is the excerpt plus verified APIs.
- **research** ("what is X?", "how do I ...?") runs search (all sources) and verify (top type and guide pages + compatibility); `grounded_result` lists the resolved types and guides.

Version and compositor come from the request text (`0.2`, `hyprland`) or from the `version`/`compositor`/`from_version`/`to_version` parameters. Loose version hints resolve at runtime against the published list. Each step runs in isolation, so a failing source shows up in `errors` instead of failing the whole request. The result carries an `orchestration` trace of the tools used and a deduplicated `sources` list. The `basis` tags on approach steps and the `verified` flag on API entries separate verified facts (from the official docs) from recommendations. The assistant writes nothing to disk.

**When to use it:** multi-step development requests, or when you do not yet know which single tool fits. For a single, focused lookup (one type page, one error message, one version check) call the specific tool directly; it is cheaper and gives the raw answer.

</details>

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
| dots-hyprland | https://github.com/end-4/dots-hyprland | Real-world implementation references (the "ii" shell) |

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
