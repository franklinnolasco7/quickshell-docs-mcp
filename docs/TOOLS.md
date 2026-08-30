# Tool reference

Full per-tool listing for `quickshell-mcp`. For a category-level overview, see the [What it provides](../README.md#what-it-provides) table in the README.

Tools are grouped by capability. Most are read-only; the few that change state are marked **mutating**, and `quickshell_ui_eval` is **high-risk** (evaluates JavaScript in a session, opt-in only).

## Knowledge

| Tool | What it does |
|---|---|
| `quickshell_list_versions` | List published documentation versions and the latest |
| `quickshell_list_types` / `quickshell_get_type` | Browse and fetch Quickshell QML type docs |
| `quickshell_list_guide_pages` / `quickshell_get_guide_page` | Fetch usage guide pages as Markdown |
| `quickshell_about` / `quickshell_changelog` | Fetch project metadata and changelog |
| `quickshell_list_qt_types` / `quickshell_get_qt_type` | Browse and fetch Qt-side types (QtQuick, Controls, Layouts, ...) |
| `quickshell_list_examples` / `quickshell_get_example` | Browse and read official example configs |
| `quickshell_search_implementations` | Search Caelestia, Noctalia, and dots-hyprland for patterns |
| `quickshell_get_implementation` | Read implementation files, narrowed via `find=` |
| `quickshell_search` | Search type names, namespaces, and guide slugs |
| `quickshell_search_all` | One-call unified search across every source |
| `quickshell_find_pattern` | Describe a feature and get matching implementations with per-pattern API hints |

## Knowledge 2.0

| Tool | What it does |
|---|---|
| `quickshell_api_diff` | Compare two versions: added, removed, renamed, deprecated with provenance |
| `quickshell_api_graph` | Documented property/type dependency graph, no speculative edges |
| `quickshell_best_practice` | Guidance ranked by authority (docs > examples > real-world) |
| `quickshell_pattern_compare` | How each shell solves the same problem, tradeoffs not verdicts |
| `quickshell_provenance` | Source, version, URL, and authority level for knowledge results |

## Validation

| Tool | What it does |
|---|---|
| `quickshell_validate_qml` | Statically validate QML source |
| `quickshell_check_compatibility` | Check whether an API, type, or snippet is compatible with a version |

## Generation and refactoring

| Tool | What it does |
|---|---|
| `quickshell_generate_component` | Minimal verified QML component from a plain-language description |
| `quickshell_generate_panel` | Generate a panel component, reusing the generator |
| `quickshell_generate_service` | Generate a service component, reusing the generator |
| `quickshell_refactor` | High-confidence whole-token edits plus a unified diff, no writes |
| `quickshell_style_match` | Evidence-backed conventions (spacing, types, colors, radius, animation) |
| `quickshell_apply_patch` | **mutating** Apply an explicit, validated edit set to a project |

## Migration

| Tool | What it does |
|---|---|
| `quickshell_migrate` | Analyze what QML must change between Quickshell versions |

## Project

| Tool | What it does |
|---|---|
| `quickshell_project_analyze` | Structured project overview, unknown values marked |
| `quickshell_project_map` | Static project graph with confirmed vs inferred edges |
| `quickshell_project_find` | Project-scoped search with location and context |
| `quickshell_project_dependencies` | Classify dependencies without executing anything |
| `quickshell_project_config` | Config conventions with confidence |
| `quickshell_project_validate` | Static validation across every QML file, grouped by file and severity |
| `quickshell_project_lint` | Extensible rule table (unused imports, duplicate ids, suspicious timers) |
| `quickshell_project_compatibility` | Per-file compatibility checks with affected files and locations |
| `quickshell_project_migrate` | Per-file migration analysis with machine-readable proposed edits, no writes |

## Runtime sessions

Opt-in and **mutating**: these launch and stop real `qs` processes in isolated XDG directories. They require `qs` on PATH.

| Tool | What it does |
|---|---|
| `quickshell_runtime_start` | Start an isolated session from a profile |
| `quickshell_runtime_stop` | Stop a session (SIGTERM, then SIGKILL on timeout) |
| `quickshell_runtime_reset` | Stop and relaunch the session under a new id |
| `quickshell_runtime_status` | Session status, PID, uptime, exit code |
| `quickshell_runtime_logs` | Filtered log lines (stream, text, bounded limit) |
| `quickshell_runtime_ping` | Readiness check: running, exited, or unhealthy |

## Visual and UI inspection

Screenshots need `grim` and a compositor; UI tree and property reads need an `inspector` IpcHandler target. Missing dependencies are reported as "unavailable" instead of failing. See [External tools](../README.md#external-tools) for the full list of runtime dependencies.

| Tool | What it does |
|---|---|
| `quickshell_windows` | Enumerate windows/surfaces of a session |
| `quickshell_screenshot` | Capture a bounded screenshot (region or object) |
| `quickshell_screenshot_diff` | Compare two screenshots |
| `quickshell_screenshot_region` | Object- or rectangle-targeted capture |
| `quickshell_ui_tree` | Depth-limited object tree |
| `quickshell_ui_find` | Find objects by name, type, or text |
| `quickshell_ui_get_property` | Read a live property |
| `quickshell_ui_set_property` | **mutating** Set a property, returns old and new |
| `quickshell_ui_invoke` | **mutating** Invoke a method via IPC, never raw eval |
| `quickshell_ui_eval` | **high-risk** Evaluate JavaScript in a session (opt-in, timeout and output limits) |
| `quickshell_ui_snapshot` | Serializable screenshot plus UI tree plus metadata |
| `quickshell_visual_check` | Objective UI analysis of a screenshot with confidence |
| `quickshell_visual_diff` | Baseline vs actual comparison with threshold and ignored regions |

## Testing

Runs machine-readable tests against a live session. **mutating** capability.

| Tool | What it does |
|---|---|
| `quickshell_test` | Run one test: steps then assertions, screenshot on failure |
| `quickshell_test_suite` | Run several tests in isolation |
| `quickshell_assert` | Assertion primitives (property, visibility, text, window) |
| `quickshell_test_macro` | Reusable test macros |
| `quickshell_test_record` | Record runtime actions into a reproducible test |
| `quickshell_test_report` | Structured report for a suite |

## Debugging

| Tool | What it does |
|---|---|
| `quickshell_explain_error` | Explain an error and suggest a fix, grounded in docs |
| `quickshell_runtime_diagnose` | Correlate logs, errors, project context, and docs into a root cause |
| `quickshell_runtime_errors` | Normalized runtime errors, original text preserved |
| `quickshell_trace` | Observed events vs inferred transitions |
| `quickshell_binding_inspect` | Live binding value plus static source expression |
| `quickshell_reload` | **mutating** Stop and relaunch a session under the same profile |

## Performance

| Tool | What it does |
|---|---|
| `quickshell_profile` | Bounded CPU/memory sampling of a session |
| `quickshell_profile_component` | Static component analysis |
| `quickshell_profile_bindings` | Binding re-evaluation chains |
| `quickshell_profile_timers` | Suspicious timer configuration |
| `quickshell_profile_object_tree` | Object counts and repeated patterns |
| `quickshell_performance_diagnose` | Correlated hypotheses with evidence and confidence |

## Desktop adapters

Each adapter detects its binary at runtime and reports "not available" when missing. Never assumes a service exists.

| Tool | What it does |
|---|---|
| `quickshell_hyprland_info` | `hyprctl` monitors, workspaces, active workspace, clients |
| `quickshell_wayland_layers` | Wayland layer scaffold, needs a compositor adapter |
| `quickshell_pipewire_info` | `pw-cli` sinks and sources |
| `quickshell_dbus_services` | `busctl` service discovery, no invocation |
| `quickshell_system_diagnostics` | Verified-only missing commands and services |

## Ecosystem

| Tool | What it does |
|---|---|
| `quickshell_nix_diagnostics` | flake.nix, devShells, nixpkgs inputs, non-Nix fallback |
| `quickshell_runtime_dependencies` | Static runtime dependency detection |
| `quickshell_profile_save/list/get/delete` | Named, versioned in-memory profile registry |
| `quickshell_profile_export/import` | JSON round-trips with schema-version guard |

## Intelligence

| Tool | What it does |
|---|---|
| `quickshell_project_memory` | Explicit, evidence-backed project memory (save, list, get, clear, reset) |
| `quickshell_project_architecture` | Evidence-cited architecture recommendations |
| `quickshell_regression_detect` | Validation plus screenshot comparison against baselines |
| `quickshell_root_cause` | Correlate static and live evidence, inferred vs observed separated |
| `quickshell_task_plan` | Inspect-before-modify minimal tool-set plan, stops at verification |

## Agent orchestration

Each tool runs an explicit staged plan with per-step results and failure isolation, composing the lower-level tools.

| Tool | What it does |
|---|---|
| `quickshell_build_feature` | Analyze, research, generate, validate, optionally apply |
| `quickshell_debug` | Explain an error, then correlate live runtime evidence |
| `quickshell_migrate_project` | API delta summary plus per-file migration engine |
| `quickshell_test_feature` | Isolated session, suite, screenshot on failure, stop |
| `quickshell_optimize` | Profile plus static analysis plus correlated diagnosis |
| `quickshell_engineer` | Full loop: build, test, debug, optimize, verify |

## Assistant

| Tool | What it does |
|---|---|
| `quickshell_coding_assistant` | Route a plain-language request through the pipeline and get a structured result |

## System

| Tool | What it does |
|---|---|
| `quickshell_stats` | Session call counts and cache-hit ratio |

> Page-fetching tools accept `version="latest"` (default) or an explicit version like `"v0.3.0"`. Cache-backed tools accept `refresh=True` to bypass the 30-minute cache.