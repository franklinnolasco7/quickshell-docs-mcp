"""Pattern-oriented lookup: interpret what the caller wants to build and find
real implementations of it. A curated alias layer ("spotlight" -> launcher,
"hud" -> OSD) expands the query into the existing implementation-topic
machinery; every hinted API type is validated against the docs index in the
test suite, so curation cannot invent types."""

from __future__ import annotations

import re

from ..config import IMPLEMENTATION_REPOS
from .docs import _build_index
from .implementations import _impl_topics_for_query
from .search_all import (
    _query_tokens,
    _search_examples_root,
    _search_guide_slugs,
    _search_impl_source,
    _search_qt_types,
    _search_quickshell_types,
)

# Grouping and global ranking must see every scored file, not just the top N
# per source, so the per-source scan runs uncapped and the requested limit is
# applied afterwards. The bound sits far above any tracked repo's QML count.
_IMPL_SCAN_LIMIT = 10_000

# Curated pattern records keyed to _IMPL_TOPICS keys. `aliases` are phrases
# that should activate the topic even though they share no substring with it;
# `api_hints` are type names a builder of this pattern will likely need.
# Only records that ADD something beyond the raw topic list live here.
_PATTERNS: list[dict] = [
    {
        "key": "bar",
        "aliases": ["menu bar", "status bar", "top bar", "taskbar"],
        "api_hints": ["PanelWindow"],
    },
    {"key": "panel", "aliases": [], "api_hints": ["PanelWindow"]},
    {
        "key": "control-center",
        "aliases": ["quick settings"],
        "api_hints": ["PanelWindow"],
    },
    {
        "key": "notifications",
        "aliases": ["notification center", "toast"],
        "api_hints": ["Notification", "NotificationServer"],
    },
    {
        "key": "osd",
        "aliases": ["hud", "on-screen display"],
        "api_hints": ["PanelWindow", "PopupAnchor"],
    },
    {
        "key": "launcher",
        "aliases": ["spotlight", "app launcher", "launchpad"],
        "api_hints": ["IpcHandler", "Process"],
    },
    {"key": "lock", "aliases": [], "api_hints": ["WlSessionLock"]},
    {
        "key": "workspaces",
        "aliases": ["workspace indicator", "workspace switcher"],
        "api_hints": ["HyprlandMonitor", "HyprlandWorkspace", "I3Workspace"],
    },
    {"key": "tray", "aliases": [], "api_hints": ["SystemTray", "SystemTrayItem"]},
    {"key": "ipc", "aliases": [], "api_hints": ["FileView", "IpcHandler"]},
    {"key": "services", "aliases": [], "api_hints": ["FileView", "Process"]},
    {"key": "animations", "aliases": ["animated"], "api_hints": ["EasingCurve"]},
    {"key": "hyprland", "aliases": [], "api_hints": ["HyprlandMonitor", "HyprlandWorkspace"]},
    {"key": "audio", "aliases": ["volume control"], "api_hints": ["Pipewire", "PwNodeAudio"]},
    {"key": "network", "aliases": [], "api_hints": ["Network", "WifiDevice"]},
    {"key": "bluetooth", "aliases": [], "api_hints": ["Bluetooth", "BluetoothDevice"]},
    {"key": "battery", "aliases": [], "api_hints": ["UPower", "UPowerDevice"]},
    {"key": "media", "aliases": [], "api_hints": ["MprisPlayer"]},
]

_PATTERN_BY_KEY = {pattern["key"]: pattern for pattern in _PATTERNS}

# Longest alias first, so "notification center" wins over shorter overlaps and
# the dedup dict records the most specific reason. \b keeps near misses like
# "toaster"/"toast" apart while hyphens still count as boundaries.
_ALIAS_MATCHERS: list[tuple[re.Pattern[str], str, dict]] = sorted(
    (
        (re.compile(rf"\b{re.escape(alias)}\b"), alias, pattern)
        for pattern in _PATTERNS
        for alias in pattern["aliases"]
    ),
    key=lambda matcher: -len(matcher[1]),
)


def _interpret_query(query: str) -> list[tuple[dict, str]]:
    """Map a build request onto pattern records, most specific first.

    Multi-word aliases win over single words ("notification center" beats the
    bare notification topic); anything still unmatched falls through to the
    existing topic-phrase machinery so coverage never shrinks."""
    query_lower = query.lower()
    matched: dict[str, tuple[dict, str]] = {}

    for alias_re, alias, pattern in _ALIAS_MATCHERS:
        if pattern["key"] in matched:
            continue
        if alias_re.search(query_lower):
            matched[pattern["key"]] = (pattern, f"alias '{alias}'")

    for topic_key, _, _ in _impl_topics_for_query(query):
        if topic_key in matched:
            continue
        record = _PATTERN_BY_KEY.get(topic_key) or {
            "key": topic_key,
            "aliases": [],
            "api_hints": [],
        }
        matched[topic_key] = (record, f"topic phrase '{topic_key}'")

    return list(matched.values())


def _hints_for(entry_topics: list[str], patterns: list[dict]) -> list[str]:
    """API hints relevant to one result: intersect the entry's topics with the
    interpreted patterns; fall back to all of them when only tokens matched."""
    hits = [pattern for pattern in patterns if pattern["key"] in entry_topics]
    pool = hits or patterns
    names: set[str] = set()
    for pattern in pool:
        names.update(pattern["api_hints"])
    return sorted(names)


def _find_pattern(query: str, version: str, limit: int = 5) -> dict:
    """Interpret `query` as something to build, then return real
    implementations of that pattern plus minimal supporting references."""
    limit = max(1, min(int(limit), 10))
    errors: dict[str, str] = {}

    if not query.strip():
        return {
            "query": query,
            "version": version,
            "interpreted_as": [],
            "total_matches": 0,
            "implementations": [],
            "examples": [],
            "docs": {},
            "cross_project_patterns": [],
            "errors": {},
            "note": "Empty query. Describe what you want to build.",
        }

    interpreted = _interpret_query(query)
    pattern_records = [pattern for pattern, _ in interpreted]
    # Alias hits must reach the path scorer: append the canonical topic keys
    # so the existing topic fragments light up without touching its scoring.
    expanded_keys = " ".join(pattern["key"] for pattern in pattern_records)
    effective_query = f"{query} {expanded_keys}".strip()
    tokens = _query_tokens(effective_query)

    merged: list[dict] = []
    for source in IMPLEMENTATION_REPOS:
        try:
            entries = _search_impl_source(source, effective_query, tokens, _IMPL_SCAN_LIMIT)
        except Exception as error:  # noqa: BLE001 - isolate per source
            errors[f"{source}_implementations"] = str(error)
            continue
        for entry in entries:
            entry["api_hints"] = _hints_for(entry.get("topics") or [], pattern_records)
            merged.append(entry)

    merged.sort(key=lambda entry: (-entry["relevance"], entry["path"]))
    implementations = merged[:limit]
    # Comparing approaches is the point of this tool: if a second project
    # scored anything, trade the last slot so it shows up instead of letting
    # one repo monopolize the cap. With a single slot there is nothing to
    # trade; the highest-ranked entry always wins.
    if len(merged) > limit > 1:
        included = {entry["source"] for entry in implementations}
        for entry in merged[limit:]:
            if entry["source"] not in included:
                implementations[-1] = entry
                included.add(entry["source"])
                break

    examples: list[dict] = []
    try:
        examples = _search_examples_root(tokens, query.lower(), 3)
    except Exception as error:  # noqa: BLE001
        errors["official_examples"] = str(error)

    docs: dict[str, list[dict]] = {}
    if pattern_records or tokens:
        try:
            index = _build_index(version)
            sections = (
                ("types", _search_quickshell_types(index, version, tokens, query.lower(), 4)),
                ("guides", _search_guide_slugs(index, version, tokens, query.lower(), 2)),
            )
            for name, entries in sections:
                if entries:
                    docs[name] = entries
            qt_entries = _search_qt_types(tokens, query.lower(), 3)
            if qt_entries:
                docs["qt_types"] = qt_entries
        except Exception as error:  # noqa: BLE001
            errors["docs"] = str(error)

    cross_project_patterns: list[dict] = []
    for pattern in pattern_records:
        # Group from the uncapped collection: capping exists to keep the
        # implementation list small, not to hide that both projects ship
        # this pattern.
        projects = {
            source: sorted(
                entry["path"]
                for entry in merged
                if entry["source"] == source and pattern["key"] in (entry.get("topics") or [])
            )
            for source in IMPLEMENTATION_REPOS
        }
        hit_sources = [source for source, paths in projects.items() if paths]
        if len(hit_sources) >= 2:
            cross_project_patterns.append(
                {
                    "pattern": pattern["key"],
                    "projects": {source: paths[:2] for source, paths in projects.items() if paths},
                    "api_hints": pattern["api_hints"],
                }
            )

    total = len(implementations) + len(examples) + sum(len(v) for v in docs.values())

    note_parts: list[str] = []
    if interpreted:
        summary = "; ".join(f"{pattern['key']} ({reason})" for pattern, reason in interpreted)
        note_parts.append(f"interpreted as: {summary}")
    else:
        known = ", ".join(pattern["key"] for pattern in _PATTERNS)
        note_parts.insert(0, f"No known pattern matched. Known patterns: {known}")
    note_parts.append("read files with quickshell_get_implementation / quickshell_get_example")
    if errors:
        note_parts.append("unavailable sources: " + ", ".join(errors))

    return {
        "query": query,
        "version": version,
        "interpreted_as": [
            {
                "pattern": pattern["key"],
                "why": reason,
                "apis": pattern["api_hints"],
            }
            for pattern, reason in interpreted
        ],
        "total_matches": total,
        "implementations": implementations,
        "examples": examples,
        "docs": docs,
        "cross_project_patterns": cross_project_patterns,
        "errors": errors,
        "note": "; ".join(note_parts),
    }
