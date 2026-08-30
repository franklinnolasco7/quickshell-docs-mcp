"""quickshell-mcp

An MCP server that gives an LLM live, grounded access to the Quickshell
documentation at https://quickshell.org, so it reads real docs instead of
guessing from stale training data. Fetch real, current data; don't
hallucinate.

Design notes:
- We regex-scan raw HTML for `/docs/vX.Y.Z/...` links rather than depending on
  the site's exact CSS/DOM structure (which is an Astro site and could change
  its markup at any time). This makes version discovery and the type/guide
  index resilient to redesigns.
- "latest version" is computed at runtime from whatever versions are linked
  on the site right now (never hardcoded), so this keeps working after
  future Quickshell releases (e.g. v0.4.0) without code changes.
- Page content is converted from HTML to Markdown so it's cheap on tokens and
  easy for a model to read.

This module is the composition root: the FastMCP instance lives here, every
``@mcp.tool`` wrapper lives here (tool docstrings are the trigger surface a
model matches against), and the actual logic lives in the domain modules.
Helper names are re-exported so tests can keep addressing ``srv.<helper>``.
"""

from __future__ import annotations

import os
import time

import httpx
from mcp.server.fastmcp import FastMCP

from . import utils

# Re-exports: the historical flat-module surface (srv._build_index & friends)
# moved into domain modules; keep every name addressable from here so tests
# and external callers survive unchanged. Tool logic is routed through the
# capability layer, which re-exports the shared-service helpers it needs.
from .caches import _cache, _cache_get, _cache_set  # noqa: F401
from .capabilities.assistant import (  # noqa: F401
    _build_project_context,
    _classify_intent,
    _coding_assistant,
    _detect_compositor,
    _project_info,
    _resolve_version_hint,
    _safe_step,
)
from .capabilities.debugging import (  # noqa: F401
    _binding_inspect,
    _categorize_error,
    _diagnose,
    _explain_error,
    _extract_type_from_code,
    _reload,
    _runtime_errors,
    _trace,
)
from .capabilities.generation import (  # noqa: F401
    _apply_patch,
    _build_section,
    _generate_component,
    _generate_panel,
    _generate_service,
    _interpret_component_query,
    _refactor,
    _style_match,
)
from .capabilities.inspection import (  # noqa: F401
    _screenshot,
    _screenshot_diff,
    _ui_eval,
    _ui_find,
    _ui_get_property,
    _ui_invoke,
    _ui_set_property,
    _ui_tree,
    _ui_windows,
)
from .capabilities.knowledge import (  # noqa: F401
    _GITHUB_API,
    _IMPL_QUERY_STOPWORDS,
    _IMPL_TOPICS,
    _QT_ANCHOR_RE,
    _QT_MODULE_LINK_RE,
    _QT_TYPE_LINK_RE,
    _VALUE_TYPES_BUCKET,
    GUIDE_LINK_RE,
    TYPE_LINK_RE,
    _build_index,
    _build_qt_index,
    _example_file,
    _examples_branch,
    _examples_known_paths,
    _examples_listing,
    _find_pattern,
    _guide_content_index,
    _guide_page,
    _impl_branch,
    _impl_component,
    _impl_entry_meta,
    _impl_file,
    _impl_repo_config,
    _impl_topics_for_query,
    _interpret_query,
    _norm_source,
    _normalize_qt_module,
    _qt_type_page,
    _resolve_qt_slug,
    _resolve_version,
    _search_everything,
    _search_guide_content,
    _search_implementations,
    _search_type_content,
    _type_page,
)
from .capabilities.migration import (  # noqa: F401
    _behavioral_scan,
    _collect_api_refs,
    _import_diff,
    _migrate,
    _migration_plan,
    _symbol_issue,
)
from .capabilities.project import (  # noqa: F401
    _analyze_project,
    _config_conventions,
    _lint_project,
    _map_project,
    _migrate_project,
    _project_compatibility,
    _project_dependencies,
    _search_project,
    _validate_project,
)
from .capabilities.runtime import (  # noqa: F401
    _SESSION_REGISTRY,
    _logs,
    _ping,
    _qs_binary,
    _reset_session,
    _RuntimeProfile,
    _start_session,
    _status_session,
    _stop_session,
)
from .capabilities.testing import (  # noqa: F401
    _assert_snapshot,
    _run_macro_test,
    _run_test,
    _run_test_suite,
    _test_macro,
    _test_record,
    _test_report,
)
from .capabilities.validation import (  # noqa: F401
    _api_in_version,
    _changelog_hits,
    _changelog_sections,
    _check_compatibility,
    _compat_at,
    _compat_from_code,
    _incorporate_range,
    _parse_api_ref,
    _parse_members,
    _parse_structure,
    _scan_versions,
    _tokenize,
    _validate,
)
from .config import (  # noqa: F401
    _QT_STRIP_SELECTORS,
    _RETRY_ATTEMPTS,
    _STRIP_SELECTORS,
    BASE,
    EXAMPLES_REPO_API,
    EXAMPLES_REPO_WEB,
    IMPLEMENTATION_REPOS,
    QT_DOCS_BASE,
)
from .extraction import _extract_main_content, _fetch_page_markdown  # noqa: F401
from .utils import (  # noqa: F401
    _FETCH_STATS,
    _STATS_STARTED,
    _TOOL_CALLS,
    _client,
    _fetch_raw,
    _record_tool,
    _with_source,
    log,
)
from .versions import (  # noqa: F401
    VERSION_RE,
    _latest_version,
    _version_sort_key,
    list_versions,
)

mcp = FastMCP("quickshell-mcp")


def _require_session(session_id: str):
    """Look up a tracked runtime session, raising ValueError if unknown."""
    session = _SESSION_REGISTRY.get(session_id)
    if session is None:
        raise ValueError(f"Unknown runtime session '{session_id}'")
    return session


@mcp.tool()
def quickshell_list_versions(refresh: bool = False) -> dict:
    """List all Quickshell documentation versions currently published on
    quickshell.org, newest first, and report which one is latest.
    Use this before fetching a page if you're unsure which version to use.
    Set refresh=True to bypass the in-process cache."""
    _record_tool("quickshell_list_versions")
    versions = list_versions(refresh=refresh)
    return {"latest": versions[0] if versions else None, "all_versions": versions}


@mcp.tool()
def quickshell_about() -> str:
    """Fetch the Quickshell 'About' page (https://quickshell.org/about/) as
    Markdown. Use this for high-level questions like what Quickshell is,
    who maintains it, and how it's licensed."""
    _record_tool("quickshell_about")
    url = f"{BASE}/about/"
    return _with_source(url, _fetch_page_markdown(url))


@mcp.tool()
def quickshell_changelog() -> str:
    """Fetch the Quickshell changelog (https://quickshell.org/changelog/) as
    Markdown. Use this to answer 'what's new / what changed' questions."""
    _record_tool("quickshell_changelog")
    url = f"{BASE}/changelog/"
    return _with_source(url, _fetch_page_markdown(url))


@mcp.tool()
def quickshell_list_guide_pages(version: str = "latest", refresh: bool = False) -> dict:
    """List the Usage Guide pages available for a given doc version
    (e.g. install-setup, introduction, size-position, qml-language,
    advanced, faq). Defaults to the latest version if none given.
    Set refresh=True to bypass the in-process cache."""
    _record_tool("quickshell_list_guide_pages")
    resolved_version = _resolve_version(version)
    if refresh:
        _cache.clear()
    index = _build_index(resolved_version)
    return {"version": resolved_version, "guide_pages": index["guide_pages"]}


@mcp.tool()
def quickshell_get_guide_page(slug: str, version: str = "latest") -> str:
    """Fetch one Usage Guide page as Markdown, e.g. slug='introduction' or
    slug='qml-language'. Call quickshell_list_guide_pages first if you don't
    know the exact slug. Defaults to the latest doc version."""
    _record_tool("quickshell_get_guide_page")
    return _guide_page(slug, version)


@mcp.tool()
def quickshell_list_types(
    namespace: str | None = None, version: str = "latest", refresh: bool = False
) -> dict:
    """List Quickshell QML types, optionally filtered to one namespace
    (e.g. 'Quickshell.Hyprland', 'Quickshell.Io', 'Quickshell.Services.Pipewire').
    Call with no namespace to see every namespace and its types.
    Defaults to the latest doc version.
    Set refresh=True to bypass the in-process cache."""
    _record_tool("quickshell_list_types")
    resolved_version = _resolve_version(version)
    if refresh:
        _cache.clear()
    index = _build_index(resolved_version)
    types_by_namespace = index["types_by_namespace"]
    if namespace:
        matches = {
            ns: types for ns, types in types_by_namespace.items() if ns.lower() == namespace.lower()
        }
        if not matches:
            close = [ns for ns in types_by_namespace if namespace.lower() in ns.lower()]
            return {
                "version": resolved_version,
                "error": f"No exact namespace match for '{namespace}'.",
                "did_you_mean": close,
            }
        return {"version": resolved_version, "namespaces": matches}
    return {"version": resolved_version, "namespaces": types_by_namespace}


@mcp.tool()
def quickshell_get_type(
    type_name: str, namespace: str = "Quickshell", version: str = "latest"
) -> str:
    """Fetch the documentation page for one QML type as Markdown, e.g.
    type_name='PanelWindow', namespace='Quickshell', or
    type_name='HyprlandMonitor', namespace='Quickshell.Hyprland'.
    Call quickshell_list_types first if you're unsure of the exact
    namespace or type name (they are case-sensitive). Defaults to the
    latest doc version."""
    _record_tool("quickshell_get_type")
    return _type_page(type_name, namespace, version)


@mcp.tool()
def quickshell_search(
    query: str,
    version: str = "latest",
    refresh: bool = False,
    include_content: bool = False,
    include_type_pages: bool = False,
) -> dict:
    """Search Quickshell type names, namespaces, and guide page slugs for a
    substring match (case-insensitive). ALWAYS call this before writing any
    QML that references a Quickshell type or property from memory; never
    guess property/type names, verify them here first.

    Use this whenever a request mentions a desktop-shell feature and you
    don't already know the exact Quickshell type name, e.g.:
    - "battery" / "power" / "upower"       -> search 'battery' or 'power' (UPower, UPowerDevice)
    - "volume" / "audio" / "mixer"         -> search 'audio' or 'volume' (Pipewire, PwNode)
    - "tray" / "system tray"               -> search 'tray' (SystemTray, SystemTrayItem)
    - "workspaces" / "monitor"             -> search 'monitor' or 'workspace'
      (HyprlandMonitor, HyprlandWorkspace, I3Monitor)
    - "notifications"                      -> search 'notification'
      (Notification, NotificationServer)
    - "network" / "wifi"                   -> search 'wifi' or 'network' (WifiDevice, Network)
    - "bluetooth"                          -> search 'bluetooth' (Bluetooth, BluetoothDevice)
    - "clock" / "date" / "time"            -> search 'clock' (SystemClock)

    For concept/how-to questions where the answer is prose rather than a
    type name ("where is IPC documented?", "how do anchors work?"), pass
    include_content=True; this also full-text-searches the guide-page
    bodies. Pass include_type_pages=True to also deep-search the ~200 type
    reference pages for property/method/signal text (slower: first call
    fetches every type page once, then it's cached).

    Returns matches with enough info to call quickshell_get_type or
    quickshell_get_guide_page directly. Namespace and type matches are
    reported separately so a namespace hit doesn't flood the results with
    all of its types. Defaults to the latest doc version.
    Set refresh=True to bypass the in-process cache."""
    _record_tool("quickshell_search")
    resolved_version = _resolve_version(version)
    if refresh:
        _cache.clear()
    index = _build_index(resolved_version)
    query_lower = query.lower()

    type_matches = [
        {"namespace": ns, "type_name": name}
        for ns, types in index["types_by_namespace"].items()
        for name in types
        if query_lower in name.lower()
    ]

    notes = []
    if not include_content:
        notes.append("set include_content=True to also search guide-page text")
    if not include_type_pages:
        notes.append("include_type_pages=True also deep-searches type reference pages")
    result: dict = {
        "version": resolved_version,
        "query": query,
        "namespace_matches": sorted(
            ns for ns in index["types_by_namespace"] if query_lower in ns.lower()
        ),
        "type_matches": type_matches,
        "guide_matches": [slug for slug in index["guide_pages"] if query_lower in slug.lower()],
        "content_matches": [],
        "type_page_matches": [],
        "note": "; ".join(notes),
    }
    if include_content:
        result["content_matches"] = _search_guide_content(query, resolved_version, refresh=refresh)
    if include_type_pages:
        result["type_page_matches"] = _search_type_content(query, resolved_version, refresh=refresh)
    return result


@mcp.tool()
def quickshell_search_all(
    query: str,
    version: str = "latest",
    include_content: bool = False,
    limit_per_source: int = 4,
    refresh: bool = False,
) -> dict:
    """Search ALL sources at once with one natural-language query: Quickshell
    docs (type names, guide pages), Qt/QML types on doc.qt.io, official
    example configs, and real-world implementations (Caelestia, Noctalia, and
    end-4's dots-hyprland).
    Results come back grouped by source, most relevant group first; every
    entry carries a relevance score, a why-it-matched reason, and a URL or
    repo path.

    Use this when you don't know which specialized tool fits ("how do I make
    a workspace bar?", "create a volume OSD") or as a first pass before
    drilling in. API-shaped queries ("PanelWindow", "exclusive zones") rank
    exact type matches first; feature requests rank working implementations
    first.

    This is breadth over depth: follow up with quickshell_get_type /
    quickshell_get_guide_page / quickshell_get_qt_type / quickshell_get_example /
    quickshell_get_implementation for full content. include_content=True also
    full-text-searches guide-page bodies (slower on first call, then cached).
    limit_per_source caps entries per source (default 4, max 10). version pins
    a Quickshell release ('latest' resolves at runtime); refresh=True bypasses
    the cache."""
    _record_tool("quickshell_search_all")
    resolved_version = _resolve_version(version)
    if refresh:
        _cache.clear()
    return _search_everything(
        query,
        resolved_version,
        include_content=include_content,
        limit_per_source=limit_per_source,
    )


@mcp.tool()
def quickshell_find_pattern(
    query: str, version: str = "latest", limit: int = 5, refresh: bool = False
) -> dict:
    """Find real implementations of a FEATURE you want to build, described in
    plain words instead of exact type names: 'Hyprland workspace indicator',
    'macOS-style control center', 'volume OSD', 'system tray', 'animated
    popup', 'floating notification', 'top bar with workspaces', 'launcher
    like Spotlight', 'power menu'. Searches Caelestia, Noctalia, and end-4's
    dots-hyprland (real-world shells) plus the official examples repo,
    interprets aliases ('Spotlight' means launcher, 'hud' means OSD), and
    returns a small ranked set where every entry carries source project, file
    path, why it matched, and the Quickshell APIs that pattern typically
    needs. When several projects solve the same pattern they are grouped so
    you can compare approaches.

    For API/type lookups by name use quickshell_search or
    quickshell_search_all instead; for browsing one repo use
    quickshell_search_implementations. Read matched files via
    quickshell_get_implementation / quickshell_get_example. limit caps total
    implementations (default 5, max 10); version pins a Quickshell release;
    refresh=True bypasses the cache."""
    _record_tool("quickshell_find_pattern")
    resolved_version = _resolve_version(version)
    if refresh:
        _cache.clear()
    return _find_pattern(query, resolved_version, limit=limit)


@mcp.tool()
def quickshell_list_qt_types(
    module: str | None = None, refresh: bool = False, qt_version: str = "latest"
) -> dict:
    """List QML types documented on doc.qt.io for QtQuick and its sibling
    modules (Controls, Layouts, Effects, Shapes, ...), discovered from the
    QtQuick module page. Use this for Qt base types like Rectangle, Text,
    MouseArea, Timer, or RowLayout that Quickshell configs import but the
    Quickshell docs don't describe themselves. For Quickshell-specific types
    use quickshell_list_types instead. qt_version pins a minor (e.g. '6.8',
    '6.7') instead of the newest release.
    Set refresh=True to bypass the in-process cache."""
    _record_tool("quickshell_list_qt_types")

    index = _build_qt_index(refresh=refresh, qt_version=qt_version)
    modules = index["modules"]
    if module:
        wanted = _normalize_qt_module(module)
        match = next((m for m in modules if _normalize_qt_module(m) == wanted), None)
        if match is None:
            raise ValueError(
                f"Unknown Qt module '{module}'. Known modules: {', '.join(sorted(modules))}"
            )
        modules = {match: modules[match]}
    return {
        "source": index["pages"]["qtquick"],
        "sources": index["pages"],
        "modules": modules,
    }


@mcp.tool()
def quickshell_get_qt_type(name: str, module: str | None = None, qt_version: str = "latest") -> str:
    """Fetch one Qt type's reference page from doc.qt.io as Markdown, e.g.
    Rectangle, Text, MouseArea, Timer, Item, RowLayout, or a value type like
    color or vector3d. Use this when a Quickshell config imports QtQuick /
    QtQuick.Controls / QtQuick.Layouts types and you need their properties,
    signals, or syntax. Pass module (e.g. 'qtquick', 'qtquick-controls') to
    disambiguate names that exist in several modules. qt_version pins a
    minor (e.g. '6.8') to match your installed Qt instead of the newest."""
    _record_tool("quickshell_get_qt_type")

    return _qt_type_page(name, module, qt_version)


@mcp.tool()
def quickshell_list_examples(path: str = "") -> dict:
    """List files and folders in the official Quickshell examples repo
    (real-world sample shell/bar/widget configs written by the Quickshell
    authors). Call with no path to list the root, then drill into a folder
    using its path. Pair with quickshell_get_example to read a file's
    contents."""
    _record_tool("quickshell_list_examples")

    try:
        return _examples_listing(path)
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            parent = "/".join(path.strip("/").split("/")[:-1])
            raise ValueError(
                f"No entry '{path}' in the examples repo. "
                f"Known entries here: {', '.join(_examples_known_paths(parent))}"
            ) from error
        raise


@mcp.tool()
def quickshell_get_example(path: str) -> str:
    """Read one file from the official Quickshell examples repo verbatim
    (QML configs, READMEs). Get valid paths from quickshell_list_examples.
    Prefer these maintained examples over writing a shell config from
    memory."""
    _record_tool("quickshell_get_example")

    return _example_file(path)


@mcp.tool()
def quickshell_search_implementations(query: str, source: str = "all", limit: int = 8) -> dict:
    """Search real-world Quickshell shells (Caelestia, Noctalia, and
    end-4's dots-hyprland) for implementations: 'find a bar implementation',
    'find a control center example', 'find Quickshell IPC usage', 'find
    multi-monitor implementation', 'find workspace widget', 'find
    notification/OSD/launcher implementation', 'find lock screen', 'find
    wallpaper handling', 'find Quickshell animations', 'find service
    patterns', 'find reusable QML components', 'find Hyprland/Niri
    integration', 'find volume/audio implementation', 'find wifi/network
    implementation', 'find bluetooth', 'find brightness', 'find battery
    implementation', 'find media controls'.
    Restrict to one shell with source='caelestia', source='noctalia', or
    source='dots-hyprland'; to compare approaches, call once per shell.
    These are practical references, NOT API docs: verify API surface with
    quickshell_search/quickshell_get_type. Get file contents via
    quickshell_get_implementation."""
    _record_tool("quickshell_search_implementations")

    sources = list(IMPLEMENTATION_REPOS) if source == "all" else [_norm_source(source)]
    results: dict[str, list[dict]] = {}
    for src in sources:
        results[src] = _search_implementations(src, query, limit)
    total_matches = sum(len(entries) for entries in results.values())
    note = ""
    if not total_matches:
        known = ", ".join(topic_key for topic_key, _, _, _ in _IMPL_TOPICS)
        note = f"No matches. Try an implementation topic like: {known}"
    return {"query": query, "total_matches": total_matches, "results": results, "note": note}


@mcp.tool()
def quickshell_get_implementation(
    source: str, path: str, find: str | None = None, max_chars: int = 12000
) -> str:
    """Read a QML file from the Caelestia, Noctalia, or dots-hyprland shells
    (get paths from quickshell_search_implementations). Pass find='osd' /
    find='workspace' / find='ipc' etc. to jump to the most relevant section
    instead of pulling the whole large file. This is a real-world
    implementation reference, NOT official documentation: when it disagrees
    with quickshell.org or doc.qt.io, trust the docs."""
    _record_tool("quickshell_get_implementation")

    return _impl_file(source, path, find, max_chars)


@mcp.tool()
def quickshell_explain_error(
    error: str,
    code: str | None = None,
    version: str = "latest",
    filename: str | None = None,
    line_number: int | None = None,
    component: str | None = None,
) -> dict:
    """Explain a Quickshell/QML error and suggest a fix, grounded in the
    actual documentation. Pass the error message; optionally include QML code,
    the filename, line number, component/type name, or Quickshell version for
    a more precise diagnosis.

    The tool verifies reported properties, methods, and signals against the
    Quickshell and Qt type indexes before suggesting fixes, so it never
    recommends APIs that don't exist.

    Use this when you encounter errors like:
    - "Cannot assign to non-existent property"
    - "Type 'X' is not accessible"
    - "X is not a function"
    - "Cannot connect to non-existent signal"
    - "module 'X' is not installed"
    - "Invalid assignment"
    - "Could not find or load the component"
    - binding errors or type mismatches"""
    _record_tool("quickshell_explain_error")
    return _explain_error(
        error=error,
        code=code,
        version=version,
        filename=filename,
        line_number=line_number,
        component=component,
    )


@mcp.tool()
def quickshell_check_compatibility(
    api: str | None = None,
    type: str | None = None,
    code: str | None = None,
    version: str = "latest",
    from_version: str | None = None,
    to_version: str | None = None,
) -> dict:
    """Check whether a Quickshell API, QML property/method/signal, type, or
    code snippet is compatible with a specific Quickshell version. Use this
    before targeting an older release, e.g. 'is PanelWindow.exclusiveZone
    available in v0.2.0?', 'which version introduced SomeType?', 'does this
    QML config work on v0.3.0?', 'was Quickshell.shellRoot renamed?'.

    Pass exactly one of:
    - api: a dotted path like 'PanelWindow.exclusiveZone',
      'Quickshell.Hyprland.HyprlandMonitor', or 'HyprlandWorkspace.activate()'
    - type: a bare type name like 'PanelWindow'
    - code: a QML snippet; every referenced type and property is checked

    version pins the Quickshell release (default 'latest', resolved at
    runtime). to_version overrides version as the target; from_version adds a
    lower-bound so the result reports compatibility across the whole range.

    The verdict is one of 'compatible' / 'incompatible' / 'uncertain', backed
    by per-version documentation and changelog evidence (never a guess from
    the latest page alone). Qt/QML types (Rectangle, Item, ...) are reported
    as compatible with origin 'qt': their availability is governed by your Qt
    version, not the Quickshell one."""
    _record_tool("quickshell_check_compatibility")
    return _check_compatibility(
        api=api,
        type=type,
        code=code,
        version=version,
        from_version=from_version,
        to_version=to_version,
    )


@mcp.tool()
def quickshell_migrate(
    from_version: str,
    to_version: str,
    code: str | None = None,
    api: str | None = None,
    type: str | None = None,
    filename: str | None = None,
) -> dict:
    """Migrate Quickshell/QML code from one Quickshell version to another:
    'migrate this config from v0.2.0 to v0.3.0', 'what do I need to change
    to upgrade to the latest Quickshell?', 'is my config still valid after
    the upgrade?'. Analyzes the code (or a single API/type) against both
    versions and reports every removed, renamed, deprecated, or changed API,
    plus breaking changes from the changelog, each with severity, location,
    the old API, the replacement, why it must change, a suggested migration,
    confidence, and a cited source.

    Pass exactly one of:
    - code: the QML source to migrate
    - api: a dotted path like 'Quickshell.shellRoot' or
      'PanelWindow.exclusiveZone'
    - type: a bare type name like 'LegacyThing'

    Both from_version and to_version are required. The scan covers only
    breaking-change changelog entries between the versions that mention
    the referenced symbols, so a rename that landed at an intermediate
    release is reported with the version it landed in, not as a vague
    'sometime between'. Findings are classified definite / likely /
    manual_review: only changes backed by the docs or changelog are
    definite. This tool analyzes and recommends; it never rewrites code
    or modifies files."""
    _record_tool("quickshell_migrate")
    return _migrate(
        from_version=from_version,
        to_version=to_version,
        code=code,
        api=api,
        type=type,
        filename=filename,
    )


@mcp.tool()
def quickshell_validate_qml(
    source: str, version: str = "latest", filename: str | None = None
) -> dict:
    """Statically validate Quickshell/QML source before you run it: unknown
    types, unknown properties, unknown signals, missing imports, obvious type
    mismatches, and APIs not available in the requested Quickshell version.

    Pass the QML source; optionally pin a Quickshell version (defaults to the
    latest) and give a filename so a root type matching the file stem is
    treated as a local component instead of an unknown type.

    The check is a lightweight heuristic that complements qmlls, not a
    replacement: it validates types/properties/signals against the Quickshell
    and Qt docs, skips JavaScript bodies, and reports things it cannot resolve
    as info diagnostics rather than errors. Returns structured diagnostics
    with line/column, severity, confidence, and a docs source URL for each
    finding.

    Use this while writing a config (e.g. after noticing 'Cannot assign to
    non-existent property' in your logs) to catch typos early:
    - unknown type or namespace
    - property/signal/method not documented on a type
    - invalid assignment to a scalar-typed property
    - missing 'import Quickshell.X' for a used namespace
    - type not present in the requested Quickshell version"""
    _record_tool("quickshell_validate_qml")
    return _validate(source=source, version=version, filename=filename)


@mcp.tool()
def quickshell_generate_component(
    description: str,
    version: str = "latest",
    compositor: str | None = None,
    style: str | None = None,
    context: str | None = None,
    filename: str | None = None,
    project: str | None = None,
) -> dict:
    """Generate a minimal, source-grounded Quickshell QML component from a
    plain-language description, e.g. 'Create a Hyprland workspace indicator',
    'animated volume OSD', 'top bar with workspaces, clock and system tray',
    'popup control center', or 'notification popup'.

    The generator researches the request, assembles a small component from
    curated templates, and BEFORE returning it verifies every Quickshell type
    and property/method it references against the requested version (via the
    compatibility machinery) and runs the static validator on the assembled
    QML. Any API that cannot be verified is surfaced rather than silently
    emitted, so the result never claims an API is valid without checking.

    The result also includes a 'verified_surface': the documented
    properties/methods/signals of every type the component uses, so you can
    freely rewrite the QML against verified members. When no curated template
    matches the request, the result carries that verified surface plus
    supporting references instead of a component, so you can compose the
    component yourself from grounded building blocks. Only one top-level
    window is generated; additional requested windows are reported in
    'assumptions' rather than embedded.

    Inputs:
    - description: what to build, in plain words
    - version: Quickshell release to target (default 'latest', resolved at runtime)
    - compositor: e.g. 'hyprland' to use compositor-specific types
    - style: optional style/behavior hints (surfaced in 'assumptions')
    - context: optional existing project context (surfaced, never read)
    - filename: suggested filename; derived from the description by default

    The result includes the generated QML, the imports/types it needs, any
    compositor or external-service dependency, per-API verification evidence,
    validation diagnostics, supporting references, and the assumptions made.
    Official documentation always wins over examples and real-world
    implementations when they disagree. This tool writes nothing to disk.

    Pass project= a path to the project root to make generation project-aware:
    the target version and compositor default to the project's detected
    values, and detected conventions are surfaced as assumptions."""
    _record_tool("quickshell_generate_component")
    return _generate_component(
        description=description,
        version=version,
        compositor=compositor,
        style=style,
        context=context,
        filename=filename,
        project=project,
    )


@mcp.tool()
def quickshell_generate_service(
    description: str,
    version: str = "latest",
    compositor: str | None = None,
    project: str | None = None,
) -> dict:
    """Generate a generic, architecture-neutral Quickshell service
    abstraction for a common application concern. The first version returns a
    verified service skeleton with declared imports and a placeholder service
    object you can extend; it is deliberately generic rather than a giant
    library of service templates. No nonexistent Quickshell APIs are emitted.
    Pass project= to align the target version and compositor with the project.
    """
    _record_tool("quickshell_generate_service")
    return _generate_service(
        description=description, version=version, compositor=compositor, project=project
    )


@mcp.tool()
def quickshell_generate_panel(
    description: str,
    version: str = "latest",
    compositor: str | None = None,
    project: str | None = None,
) -> dict:
    """Generate high-level panel scaffolding for a bar, OSD, launcher,
    dashboard, control center, or notification panel. This is scaffolding,
    not a full design generator: it reuses the component generator and
    project style detection, and outputs minimal, valid, extendable QML.
    Pass project= to align version, compositor, and conventions with the
    project.
    """
    _record_tool("quickshell_generate_panel")
    return _generate_panel(
        description=description, version=version, compositor=compositor, project=project
    )


@mcp.tool()
def quickshell_refactor(project: str, old: str, new: str) -> dict:
    """Propose a safe refactoring (rename component, property, or reference)
    across a Quickshell project: rename an identifier everywhere it appears
    as a whole token. Returns structured edits plus a unified diff. Never
    writes files — apply the edits with quickshell_apply_patch when you are
    ready.
    """
    _record_tool("quickshell_refactor")
    return _refactor(project, old, new)


@mcp.tool()
def quickshell_apply_patch(
    project: str,
    edits: list[dict],
    expected_base_hashes: dict[str, str] | None = None,
) -> dict:
    """Apply a previously generated edit set to a Quickshell project, but only
    when explicitly requested. This is a mutating operation.

    Validates that every edit path stays inside the authorized project root,
    the patch is well-formed, not stale (optionally by expected file hashes),
    and would not silently overwrite conflicting edits. Only whole-token
    occurrences are replaced, and a target must be unique or the patch is
    rejected. Reports every changed file. Nothing outside the project root is
    ever touched.
    """
    _record_tool("quickshell_apply_patch")
    return _apply_patch(
        project,
        edits=edits,
        expected_base_hashes=expected_base_hashes,
    )


@mcp.tool()
def quickshell_style_match(project: str) -> dict:
    """Analyze an existing Quickshell project and infer reusable UI
    conventions: colors, corner radius, font sizes, spacing, animation
    durations, component structure, and naming patterns. Returns
    evidence-backed findings (values actually present and their frequency),
    never design opinions. Generation tools can consume this style
    representation later.
    """
    _record_tool("quickshell_style_match")
    return _style_match(project)


@mcp.tool()
def quickshell_coding_assistant(
    request: str,
    version: str = "latest",
    compositor: str | None = None,
    code: str | None = None,
    error: str | None = None,
    filename: str | None = None,
    from_version: str | None = None,
    to_version: str | None = None,
    context: str | None = None,
    project: str | None = None,
) -> dict:
    """High-level Quickshell development assistant for AI coding agents.

    Give it one plain-language development request and it routes the work
    through the other tools, returning a structured, source-grounded result:
    - build: 'build a Hyprland workspace bar', 'add an animated volume popup'
    - debug: 'why is this PanelWindow failing?', 'fix this QML error' (pass
      error= and/or code=)
    - migrate: 'migrate this shell from v0.2 to v0.3' (from_version/to_version
      pin the range)
    - adapt a pattern: 'find an implementation of this feature and adapt it'
    - research: 'how should I structure this component?', 'what is PanelWindow?'

    The assistant picks the minimal set of lower-level tools needed (search,
    pattern lookup, type/guide pages, compatibility, migration, generation,
    validation), runs each step in isolation so a failing source never sinks
    the whole answer, deduplicates searches, reuses the shared cache, and
    never modifies files. version pins the Quickshell release. Results clearly
    separate verified facts (official docs) from recommendations, and every
    claim carries a source URL. For a single, focused lookup call the specific
    tool directly instead.

    Pass project= a path to the Quickshell project root to ground the answer
    in that project: the assistant infers its Quickshell version and
    compositor from the project's QML imports and uses them as defaults, and
    returns a 'project' section describing what was detected (version,
    compositor, QML files, each marked detected/inferred/unknown). An invalid
    path is reported in that section instead of failing the request."""
    _record_tool("quickshell_coding_assistant")
    return _coding_assistant(
        request=request,
        version=version,
        compositor=compositor,
        code=code,
        error=error,
        filename=filename,
        from_version=from_version,
        to_version=to_version,
        context=context,
        project=project,
    )


@mcp.tool()
def quickshell_project_analyze(project: str) -> dict:
    """Inspect a Quickshell project and produce a structured project overview
    containing, where detectable: Quickshell version, Qt version, entrypoints,
    QML files, JS files, imports, Quickshell modules, components, services,
    compositor integrations, runtime dependencies, and project configuration.

    Builds on the shared ProjectContext. Unknown or undetected values are
    explicitly marked; no information is fabricated. File listings are capped
    to a reasonable sample; the full list is available via the specialized
    project tools.
    """
    _record_tool("quickshell_project_analyze")
    return _analyze_project(project)


@mcp.tool()
def quickshell_project_map(project: str) -> dict:
    """Build a machine-readable project graph showing relationships between
    QML components, imports, service dependencies, entrypoints, and module
    dependencies. Relies on reliable static relationships.

    The output clearly distinguishes:
    - confirmed relationships (directly observed import statements, type
      matches against local file stems)
    - inferred relationships (references that could not be proven local)

    Reports cyclic component usage and references that match no local file
    and no known namespace.
    """
    _record_tool("quickshell_project_map")
    return _map_project(project)


@mcp.tool()
def quickshell_project_find(project: str, query: str) -> dict:
    """Project-aware search: find where a concept, API, type, or property
    is used in a Quickshell project. Supports both exact textual matching
    and semantic/project-aware matching (type names, import modules).

    Returns file, location, match context, and why the result matched.
    Exact textual matches are ranked first; semantic matches follow.
    """
    _record_tool("quickshell_project_find")
    return _search_project(project, query)


@mcp.tool()
def quickshell_project_dependencies(project: str) -> dict:
    """Detect a Quickshell project's dependencies from source and
    configuration, without executing anything.

    Classes are:
    - required: Quickshell and Qt modules the project imports
    - optional: imports that match known namespaces without local files
    - detected: runtime hooks, services, config keywords, environment
      variable references
    - missing: imports that resolve to neither a known namespace nor a
      local component
    """
    _record_tool("quickshell_project_dependencies")
    return _project_dependencies(project)


@mcp.tool()
def quickshell_project_config(project: str) -> dict:
    """Detect a Quickshell project's configuration conventions:
    entrypoints, configuration files, environment variables, structural
    conventions, and runtime hints. Inferred values include confidence
    levels; directly observed values carry high confidence.
    """
    _record_tool("quickshell_project_config")
    return _config_conventions(project)


@mcp.tool()
def quickshell_project_validate(project: str, version: str = "latest") -> dict:
    """Run the static QML validator across an entire Quickshell project and
    aggregate syntax errors, import problems, type problems, property and
    signal issues, version mismatches, and deprecated or unavailable APIs.

    Results are grouped by file and severity. One bad file never prevents
    analysis of the rest: unreadable files are reported and skipped. Reuses
    the existing validator rather than duplicating logic.
    """
    _record_tool("quickshell_project_validate")
    return _validate_project(project, version=version)


@mcp.tool()
def quickshell_project_lint(project: str) -> dict:
    """Run quality-oriented lint checks across a Quickshell project.

    Every rule has a stable diagnostic code, severity, explanation, and
    remediation. Rules are conservative and evidence-based; they flag
    suspicious patterns (duplicate imports, duplicate object ids, suspicious
    timers) rather than subjective style opinions. The rule table is
    extensible for future additions.
    """
    _record_tool("quickshell_project_lint")
    return _lint_project(project)


@mcp.tool()
def quickshell_project_compatibility(project: str, version: str = "latest") -> dict:
    """Analyze a whole project's Quickshell API compatibility against a
    target version: unavailable, deprecated, or changed APIs with affected
    files and concrete locations.

    Reuses the version compatibility engine. A verdict of 'uncertain' means
    the docs did not prove availability either way — it is never reported as
    a runtime incompatibility.
    """
    _record_tool("quickshell_project_compatibility")
    return _project_compatibility(project, version=version)


@mcp.tool()
def quickshell_project_migrate(project: str, from_version: str, to_version: str) -> dict:
    """Analyze a whole Quickshell project for what must change to move from
    one Quickshell version to another: breaking and deprecated APIs, required
    changes, and a machine-readable proposed-edit list.

    Never modifies files. Every proposed edit carries file, line, and
    old/new API context so it can be applied safely. Reuses the existing
    migration engine per file.
    """
    _record_tool("quickshell_project_migrate")
    return _migrate_project(project, from_version=from_version, to_version=to_version)


@mcp.tool()
def quickshell_runtime_start(
    project: str,
    entrypoint: str | None = None,
    config_dir: str | None = None,
    environment: dict[str, str] | None = None,
    compositor: str | None = None,
    arguments: list[str] | None = None,
) -> dict:
    """Start a managed, isolated Quickshell runtime session for a project.

    Launches ``qs`` with isolated XDG directories so it never touches your
    real desktop session or other quickshell instances. Returns a session id
    and tracks the process for later status, logs, ping, stop, and reset.
    This is a mutating operation: it launches a process."""
    _record_tool("quickshell_runtime_start")
    profile = _RuntimeProfile(
        project_root=project,
        entrypoint=entrypoint,
        config_dir=config_dir,
        environment=environment or {},
        compositor=compositor,
        arguments=arguments or [],
    )
    return _start_session(profile).to_dict()


@mcp.tool()
def quickshell_runtime_stop(session_id: str) -> dict:
    """Stop a managed runtime session safely (SIGTERM, then SIGKILL on timeout).

    Handles already-exited and orphaned processes; stops only the tracked
    session's process group, never unrelated user processes. Mutating."""
    _record_tool("quickshell_runtime_stop")
    session = _require_session(session_id)
    _stop_session(session)
    return session.to_dict()


@mcp.tool()
def quickshell_runtime_reset(session_id: str) -> dict:
    """Reset a managed runtime session to a clean state.

    Stops the current session, cleans up its isolated temp dirs, and starts a
    fresh session with the same profile under a new session id. Mutating."""
    _record_tool("quickshell_runtime_reset")
    session = _require_session(session_id)
    fresh = _reset_session(session)
    return fresh.to_dict()


@mcp.tool()
def quickshell_runtime_status(session_id: str) -> dict:
    """Return structured status for a runtime session: session id, running
    state, PID, startup duration, exit code, and profile identity. Read-only."""
    _record_tool("quickshell_runtime_status")
    session = _require_session(session_id)
    return _status_session(session)


@mcp.tool()
def quickshell_runtime_logs(
    session_id: str,
    stream: str | None = None,
    severity: str | None = None,
    text: str | None = None,
    limit: int = 200,
) -> dict:
    """Return structured logs from a runtime session with optional filtering
    by stream (stdout/stderr), text, and a bounded limit. Read-only."""
    _record_tool("quickshell_runtime_logs")
    session = _require_session(session_id)
    lines = _logs(session, stream=stream, severity=severity, text=text, limit=limit)
    return {"session_id": session_id, "logs": lines, "count": len(lines)}


@mcp.tool()
def quickshell_runtime_ping(session_id: str) -> dict:
    """Lightweight readiness/health check for a runtime session.

    Distinguishes: process_running, exited (with exit code), or unhealthy.
    Fast, read-only."""
    _record_tool("quickshell_runtime_ping")
    session = _require_session(session_id)
    return _ping(session)


@mcp.tool()
def quickshell_windows(session_id: str) -> dict:
    """Enumerate windows/surfaces belonging to a managed Quickshell runtime
    session. Read-only. Requires a compositor adapter; when unavailable
    returns an empty list with an explanatory note (never fails)."""
    _record_tool("quickshell_windows")
    return _ui_windows(session_id)


@mcp.tool()
def quickshell_screenshot(session_id: str) -> dict:
    """Capture a screenshot from a managed Quickshell runtime session.

    Requires the ``grim`` compositor screenshot tool on PATH. Returns the
    image path or an "unavailable" note. Read-only."""
    _record_tool("quickshell_screenshot")
    return _screenshot(session_id)


@mcp.tool()
def quickshell_screenshot_diff(baseline: str, actual: str, output: str | None = None) -> dict:
    """Compare two runtime screenshots with ImageMagick ``compare``.

    Returns whether they differ, the diff image path, and a metric.
    Deterministic for CI. Read-only."""
    _record_tool("quickshell_screenshot_diff")
    return _screenshot_diff(baseline, actual, output=output)


@mcp.tool()
def quickshell_ui_tree(session_id: str, depth: int = 3) -> dict:
    """Inspect the live QML object tree of a managed runtime session.

    Returns a compact, depth-limited hierarchy from the injected
    'inspector' IpcHandler target. Read-only."""
    _record_tool("quickshell_ui_tree")
    return _ui_tree(session_id, depth=depth)


@mcp.tool()
def quickshell_ui_find(session_id: str, query: str) -> dict:
    """Search the live QML object tree of a managed runtime session by name,
    type, text, or property. Returns stable references for later runtime
    tools. Read-only."""
    _record_tool("quickshell_ui_find")
    return _ui_find(session_id, query)


@mcp.tool()
def quickshell_ui_get_property(session_id: str, target: str, property_name: str) -> dict:
    """Read a live QML property value from a managed runtime object via
    ``qs ipc prop get``. Validates the object/property exist. Read-only."""
    _record_tool("quickshell_ui_get_property")
    return _ui_get_property(session_id, target, property_name)


@mcp.tool()
def quickshell_ui_set_property(
    session_id: str, target: str, property_name: str, value: str
) -> dict:
    """Set a live QML property on a managed runtime object. Mutating.

    Requires an explicit runtime session, validates the property exists,
    returns the old and new values, and never modifies project files."""
    _record_tool("quickshell_ui_set_property")
    return _ui_set_property(session_id, target, property_name, value)


@mcp.tool()
def quickshell_ui_invoke(
    session_id: str, target: str, method: str, arguments: list[str] | None = None
) -> dict:
    """Invoke a QML method on a managed runtime object via ``qs ipc call``.
    Mutating. Validates the method and arguments; enforces runtime session
    boundaries; no arbitrary process/system calls."""
    _record_tool("quickshell_ui_invoke")
    return _ui_invoke(session_id, target, method, arguments=arguments)


@mcp.tool()
def quickshell_ui_eval(session_id: str, js_code: str, timeout: int = 5) -> dict:
    """HIGH-RISK: evaluate QML/JavaScript in a managed runtime session.

    Explicitly opt-in, session-scoped, with an execution timeout and output
    limits. No filesystem or process access is granted. Prefer
    quickshell_ui_get_property / quickshell_ui_invoke for controlled reads
    and calls."""
    _record_tool("quickshell_ui_eval")
    return _ui_eval(session_id, js_code, timeout=timeout)


@mcp.tool()
def quickshell_test(session_id: str, test: dict) -> dict:
    """Run a single machine-readable runtime test against a managed
    Quickshell session.

    A test has a name, a list of steps (wait, invoke, set_property), and a
    list of assertions (object_exists, property_equals, property_contains,
    property_matches, visible, enabled, text_matches, window_exists). Returns
    pass/fail, per-step and per-assertion results, duration, and an optional
    screenshot on failure. Mutating (drives the runtime)."""
    _record_tool("quickshell_test")
    return _run_test(session_id, test)


@mcp.tool()
def quickshell_test_suite(session_id: str, tests: list[dict]) -> dict:
    """Run multiple named runtime tests in isolation. One failing test never
    corrupts the rest of the suite. Returns pass/fail totals and per-test
    results. Mutating."""
    _record_tool("quickshell_test_suite")
    return _run_test_suite(session_id, tests)


@mcp.tool()
def quickshell_assert(session_id: str, assertion: dict) -> dict:
    """Run a single reusable assertion primitive against a managed runtime
    session: object_exists, property_equals, property_contains,
    property_matches, visible, enabled, text_matches, window_exists.

    Returns a structured pass/fail with useful context. Read-only."""
    _record_tool("quickshell_assert")
    return _assert_snapshot(session_id, assertion)


@mcp.tool()
def quickshell_test_macro(name: str, steps: list[dict] | None = None) -> dict:
    """Define or retrieve a reusable parameterized runtime macro: a named
    sequence of safe runtime steps that tests can invoke. Pass steps= to
    save a macro; omit steps to load one by name. Macros are project-scoped
    for the process. Read-only."""
    _record_tool("quickshell_test_macro")
    return _test_macro(name, steps)


@mcp.tool()
def quickshell_test_record(session_id: str, actions: list[dict]) -> dict:
    """Record a list of runtime actions into a reproducible test
    representation. Uses stable selectors (target + method/property), not
    fragile generated object ids. Read-only."""
    _record_tool("quickshell_test_record")
    return _test_record(session_id, actions)


@mcp.tool()
def quickshell_test_report(session_id: str, suite: dict) -> dict:
    """Produce a structured test report: passed/failed tests, durations,
    assertions, runtime logs, screenshots, and diagnostics. Suitable for
    both an LLM and human CI output. Read-only."""
    _record_tool("quickshell_test_report")
    return _test_report(session_id, suite)


@mcp.tool()
def quickshell_runtime_diagnose(session_id: str) -> dict:
    """Diagnose a managed runtime session: combine runtime logs, errors,
    project context, and version info into a probable root cause with
    confidence. Never fabricates a cause when evidence is insufficient.
    Read-only."""
    _record_tool("quickshell_runtime_diagnose")
    return _diagnose(session_id)


@mcp.tool()
def quickshell_runtime_errors(session_id: str, limit: int = 50) -> dict:
    """Extract and normalize common Quickshell/QML runtime problems from a
    session's stderr: import failures, undefined properties, type mismatches,
    binding loops, component load failures, JS exceptions, and signal/method
    errors. Original error text is preserved. Read-only."""
    _record_tool("quickshell_runtime_errors")
    return _runtime_errors(session_id, limit=limit)


@mcp.tool()
def quickshell_trace(session_id: str, action: str, steps: int = 10) -> dict:
    """Trace a selected runtime interaction across observable state
    transitions. Reports observed log events; inferred transitions are always
    kept separate from observed evidence. Read-only."""
    _record_tool("quickshell_trace")
    return _trace(session_id, action, steps=steps)


@mcp.tool()
def quickshell_binding_inspect(session_id: str, target: str, property_name: str) -> dict:
    """Inspect a binding on a managed runtime object: current live value,
    likely source expression (from the project QML), and files that
    reference it. Read-only."""
    _record_tool("quickshell_binding_inspect")
    return _binding_inspect(session_id, target, property_name)


@mcp.tool()
def quickshell_reload(session_id: str, hard: bool = False) -> dict:
    """Reload a managed runtime session, preserving session tracking. Reuses
    the lifecycle implementation; cleans up after failed reloads. Never
    touches production Quickshell processes. Mutating."""
    _record_tool("quickshell_reload")
    return _reload(session_id, hard=hard)


@mcp.tool()
def quickshell_stats() -> dict:
    """Report session usage stats for this MCP server: per-tool call counts,
    network fetches vs cache hits, and process uptime. Use this to check how
    much the server has been consulted and how much it hit the live site vs
    its 30-minute cache."""
    _record_tool("quickshell_stats")
    return {
        "tool_calls": dict(sorted(utils._TOOL_CALLS.items(), key=lambda item: -item[1])),
        "cache_hits": utils._FETCH_STATS["cache_hits"],
        "network_fetches": utils._FETCH_STATS["network_fetches"],
        "uptime_seconds": round(time.time() - utils._STATS_STARTED, 1),
    }


def main() -> None:
    transport = os.environ.get("QUICKSHELL_DOCS_MCP_TRANSPORT", "stdio").strip().lower()
    if transport in ("http", "streamable-http"):
        host = os.environ.get("QUICKSHELL_DOCS_MCP_HOST", "127.0.0.1").strip()
        try:
            port = int(os.environ.get("QUICKSHELL_DOCS_MCP_PORT", "8000") or "8000")
        except ValueError:
            log.warning("invalid QUICKSHELL_DOCS_MCP_PORT; falling back to 8000")
            port = 8000
        mcp.settings.host = host
        mcp.settings.port = port
        log.info("serving MCP over streamable HTTP at http://%s:%d/mcp", host, port)
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
