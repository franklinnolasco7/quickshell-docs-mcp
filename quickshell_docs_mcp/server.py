"""quickshell-docs-mcp

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
# and external callers survive unchanged.
from .caches import _cache, _cache_get, _cache_set  # noqa: F401
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
from .sources.docs import (  # noqa: F401
    GUIDE_LINK_RE,
    TYPE_LINK_RE,
    _build_index,
    _guide_content_index,
    _guide_page,
    _resolve_version,
    _search_guide_content,
    _search_type_content,
    _type_page,
)
from .sources.examples import (  # noqa: F401
    _example_file,
    _examples_branch,
    _examples_known_paths,
    _examples_listing,
)
from .sources.implementations import (  # noqa: F401
    _GITHUB_API,
    _IMPL_QUERY_STOPWORDS,
    _IMPL_TOPICS,
    _impl_branch,
    _impl_component,
    _impl_entry_meta,
    _impl_file,
    _impl_repo_config,
    _impl_topics_for_query,
    _norm_source,
    _search_implementations,
)
from .sources.qt_docs import (  # noqa: F401
    _QT_ANCHOR_RE,
    _QT_MODULE_LINK_RE,
    _QT_TYPE_LINK_RE,
    _VALUE_TYPES_BUCKET,
    _build_qt_index,
    _normalize_qt_module,
    _qt_type_page,
    _resolve_qt_slug,
)
from .sources.search_all import _search_everything  # noqa: F401
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

mcp = FastMCP("quickshell-docs")


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
    example configs, and real-world Caelestia/Noctalia implementations.
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
    """Search real-world Quickshell shells (Caelestia, Noctalia) for
    implementations: 'find a bar implementation', 'find a control center
    example', 'find Quickshell IPC usage', 'find multi-monitor
    implementation', 'find workspace widget', 'find notification/OSD/launcher
    implementation', 'find lock screen', 'find wallpaper handling',
    'find Quickshell animations', 'find service patterns', 'find reusable QML
    components', 'find Hyprland/Niri integration', 'find volume/audio
    implementation', 'find wifi/network implementation', 'find bluetooth',
    'find brightness', 'find battery implementation', 'find media controls'.
    Restrict to one shell with source='caelestia' or source='noctalia'; to
    compare approaches, call once per shell. These are practical references,
    NOT API docs: verify API surface with quickshell_search/
    quickshell_get_type. Get file contents via quickshell_get_implementation."""
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
    """Read a QML file from the Caelestia or Noctalia shells (get paths from
    quickshell_search_implementations). Pass find='osd' / find='workspace' /
    find='ipc' etc. to jump to the most relevant section instead of pulling
    the whole large file. This is a real-world implementation reference, NOT
    official documentation: when it disagrees with quickshell.org or
    doc.qt.io, trust the docs."""
    _record_tool("quickshell_get_implementation")

    return _impl_file(source, path, find, max_chars)


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
