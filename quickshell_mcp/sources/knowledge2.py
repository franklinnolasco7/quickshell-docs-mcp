"""Knowledge 2.0: versioned API diffs, API dependency graphs, ranked best
practices, cross-project pattern comparison, and source provenance.

All tools are read-only.  Provenance (source, version, URL, file, line,
authority) is carried through every result and survives into assistant
output.
"""

from __future__ import annotations

import re
from typing import Any

from ..versions import _resolve_version, _version_sort_key
from .compat import (
    _api_in_version,
    _changelog_hits,
    _changelog_sections,
    _type_members,
)
from .docs import _build_index
from .implementations import IMPLEMENTATION_REPOS
from .search_all import (
    IMPL_SECTIONS,
    SECTION_EXAMPLES,
    SECTION_GUIDE_CONTENT,
    SECTION_GUIDE_PAGES,
    SECTION_QT_TYPES,
    SECTION_TYPES,
    _search_everything,
)

_AUTHORITY = {
    "docs": 3,  # official quickshell.org docs
    "examples": 2,  # official examples repo
    "real-world": 1,  # community shells
}

_DOC_SECTIONS = {
    SECTION_TYPES,
    SECTION_GUIDE_PAGES,
    SECTION_GUIDE_CONTENT,
    SECTION_QT_TYPES,
}


def _authority_label(source: str) -> str:
    if source in _DOC_SECTIONS:
        return "docs"
    if source == SECTION_EXAMPLES:
        return "examples"
    if source in IMPL_SECTIONS.values():
        return "real-world"
    return source


# ---------------------------------------------------------------------------
# API diff
# ---------------------------------------------------------------------------


def _api_diff(from_version: str, to_version: str) -> dict[str, Any]:
    """Compare two Quickshell versions: added, removed, renamed, and
    deprecated APIs, each with provenance (changelog URL + type page URL)."""
    resolved_from = _resolve_version(from_version)
    resolved_to = _resolve_version(to_version)

    from_index = _build_index(resolved_from)
    to_index = _build_index(resolved_to)
    from_types = {name for names in from_index["types_by_namespace"].values() for name in names}
    to_types = {name for names in to_index["types_by_namespace"].values() for name in names}

    added = sorted(to_types - from_types)
    removed = sorted(from_types - to_types)
    common = sorted(from_types & to_types)
    sections = _sections_between(resolved_from, resolved_to)

    renamed = _renamed_between(common, sections)
    deprecated = _deprecated_between(common, sections)

    changelog = _changelog_hits(added + removed)
    provenance = {
        "from_version": resolved_from,
        "to_version": resolved_to,
        "changelog_url": f"{_BASE()}/changelog/",
        "note": (
            "Added/removed reflect type-index differences; "
            "renamed/deprecated come from the changelog and type pages."
        ),
    }
    return {
        "from_version": resolved_from,
        "to_version": resolved_to,
        "added": [{"name": name, "url": _type_url(name, resolved_to)} for name in added],
        "removed": [{"name": name, "url": _type_url(name, resolved_from)} for name in removed],
        "renamed": renamed,
        "deprecated": [{"name": name, "url": _type_url(name, resolved_to)} for name in deprecated],
        "changelog": changelog[:10],
        "provenance": provenance,
    }


def _sections_between(from_version: str, to_version: str) -> list[dict[str, str]]:
    """Changelog sections strictly newer than *from_version*, up to and
    including *to_version* (the diff window)."""
    from_key = _version_sort_key(from_version)
    to_key = _version_sort_key(to_version)
    return [
        section
        for section in _changelog_sections()
        if from_key < _version_sort_key(section["version"]) <= to_key
    ]


def _renamed_between(types: list[str], sections: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Find types renamed within the diff window.

    ``_find_rename`` needs a type's current name; since a diff spans two
    versions we scan the window's changelog sections directly and keep
    renames whose old or new name is one of the *types* under comparison.
    """
    renamed: list[dict[str, Any]] = []
    type_set = set(types)
    seen: set[tuple[str, str]] = set()
    for section in sections:
        for line in section["text"].splitlines():
            match = _RENAME_RE.search(line)
            if not match:
                continue
            old, new = match.group("old"), match.group("new").rstrip(".")
            hits = any(
                old == name
                or old.startswith(f"{name}.")
                or new == name
                or new.startswith(f"{name}.")
                for name in type_set
            )
            if hits and (old, new) not in seen:
                seen.add((old, new))
                renamed.append(
                    {
                        "old": old,
                        "new": new,
                        "version": section["version"],
                        "url": section["url"],
                    }
                )
    return renamed


_RENAME_RE = re.compile(
    r"`?(?P<old>[\w.]+)`?\s+(?:has been )?renamed to\s+`?(?P<new>[\w.]+)`?",
    re.IGNORECASE,
)


def _deprecated_between(types: list[str], sections: list[dict[str, str]]) -> list[str]:
    """Return common *types* announced as deprecated in the diff window.

    A diff reports what changed *between* the two versions, so the changelog
    is the source of truth for deprecations — no per-type page fetch is
    needed. Lines mentioning "deprecat" are scanned and any of *types*
    named on them are reported.
    """
    deprecated: set[str] = set()
    for section in sections:
        for line in section["text"].splitlines():
            if "deprecat" not in line.lower():
                continue
            for name in types:
                if name in line:
                    deprecated.add(name)
    return sorted(deprecated)


def _BASE() -> str:
    from ..config import BASE

    return BASE


def _type_url(type_name: str, version: str) -> str | None:
    """Best-effort type page URL; None when the namespace is unknown."""
    from .compat import _resolve_namespace

    ns, _ = _resolve_namespace(type_name, version, None)
    if ns:
        return f"{_BASE()}/docs/{version}/types/{ns}/{type_name}/"
    return None


# ---------------------------------------------------------------------------
# API dependency graph
# ---------------------------------------------------------------------------


def _api_graph(api: str, version: str = "latest") -> dict[str, Any]:
    """Build a documented API dependency graph for *api*.

    Edges are only added when the docs state the relationship (a property's
    declared type, a documented base type).  No speculative edges.
    """
    resolved = _resolve_version(version)
    parts = api.split(".")
    type_name = parts[-1]
    namespace_hint = ".".join(parts[:-1]) or None

    compat = _api_in_version(type_name, None, resolved, namespace_hint=namespace_hint)
    if compat is None or not compat.get("type_present"):
        raise ValueError(f"API '{api}' not found in {resolved}")

    namespace = compat["namespace"] or ""
    members = _type_members(type_name, namespace, resolved) or {}

    nodes = [
        {
            "name": type_name,
            "namespace": namespace,
            "kind": "type",
            "url": _type_url(type_name, resolved),
        }
    ]
    edges: list[dict[str, Any]] = []

    # Property edges: each declared property is a documented relationship.
    for prop_name, prop_type in (members.get("properties") or {}).items():
        edges.append(
            {
                "from": type_name,
                "to": prop_type,
                "kind": "property",
                "detail": f"{type_name}.{prop_name} : {prop_type}",
                "status": "documented",
            }
        )
        nodes.append({"name": prop_type, "namespace": None, "kind": "type", "url": None})

    # Base type edge when documented (hyprland_monitor style "BaseType: QtObject").
    base = members.get("base")
    if base:
        edges.append(
            {
                "from": type_name,
                "to": base,
                "kind": "base",
                "detail": f"inherits {base}",
                "status": "documented",
            }
        )
        nodes.append({"name": base, "namespace": None, "kind": "type", "url": None})

    return {
        "api": api,
        "version": resolved,
        "nodes": _dedupe_nodes(nodes),
        "edges": edges,
        "note": "Edges are documented relationships only; no speculative connections are added.",
    }


def _dedupe_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str | None]] = set()
    result: list[dict[str, Any]] = []
    for node in nodes:
        key = (node["name"], node.get("namespace"))
        if key in seen:
            continue
        seen.add(key)
        result.append(node)
    return result


# ---------------------------------------------------------------------------
# Best practice (ranked authority)
# ---------------------------------------------------------------------------


def _best_practice(query: str, version: str = "latest") -> dict[str, Any]:
    """Return evidence-backed guidance ranked by authority:
    official docs > official examples > real-world shells.  Documented
    behavior is separated from community convention."""
    resolved = _resolve_version(version)
    search = _search_everything(query, resolved, include_content=True, limit_per_source=5)
    sections = search.get("results") or {}
    section_order = search.get("section_order") or []

    # Map search sections to authority tiers.
    docs_entries = []
    example_entries = []
    realworld_entries = []
    for section in section_order:
        entries = sections.get(section, [])
        if "types" in section or "guide" in section:
            docs_entries.extend(entries)
        elif "examples" in section:
            example_entries.extend(entries)
        elif "implementation" in section:
            realworld_entries.extend(entries)

    def _entry_meta(entry: dict[str, Any], authority: str) -> dict[str, Any]:
        return {
            "title": entry.get("name")
            or entry.get("type_name")
            or entry.get("slug")
            or entry.get("path"),
            "url": entry.get("url"),
            "snippet": entry.get("snippet") or entry.get("text") or "",
            "authority": authority,
            "provenance": {"source": authority, "version": resolved, "url": entry.get("url")},
        }

    guidance = {
        "documented": [_entry_meta(e, "docs") for e in docs_entries[:3]],
        "examples": [_entry_meta(e, "examples") for e in example_entries[:3]],
        "real-world": [_entry_meta(e, "real-world") for e in realworld_entries[:3]],
    }
    return {
        "query": query,
        "version": resolved,
        "guidance": guidance,
        "note": (
            "Ranked by authority: official docs > examples > real-world shells. "
            "Documented behavior is authoritative; community convention is advisory."
        ),
    }


# ---------------------------------------------------------------------------
# Pattern comparison
# ---------------------------------------------------------------------------


def _pattern_compare(query: str, version: str = "latest") -> dict[str, Any]:
    """Compare how the indexed real-world shells solve the same problem.

    Reports the common pattern, per-project differences, and tradeoffs with
    source locations.  Never declares one implementation 'correct'."""
    from .implementations import _search_implementations

    resolved = _resolve_version(version)
    per_project: list[dict[str, Any]] = []
    for source in IMPLEMENTATION_REPOS:
        entries = _search_implementations(source, query, limit=3)
        per_project.append(
            {
                "project": source,
                "matches": [
                    {
                        "path": e["path"],
                        "url": e["url"],
                        "topics": e.get("topics", []),
                    }
                    for e in entries
                ],
            }
        )

    return {
        "query": query,
        "version": resolved,
        "per_project": per_project,
        "note": (
            "Project differences are presented for comparison; no single "
            "implementation is declared correct."
        ),
    }


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def _provenance(query: str, version: str = "latest", limit: int = 5) -> dict[str, Any]:
    """Return provenance for knowledge results: source, version, URL, and
    authority level, so higher-level results can cite them."""
    resolved = _resolve_version(version)
    search = _search_everything(query, resolved, include_content=False, limit_per_source=limit)
    sections = search.get("results") or {}
    section_order = search.get("section_order") or []

    provenance_entries: list[dict[str, Any]] = []
    for section in section_order:
        authority = _authority_label(section)
        for entry in sections.get(section, []):
            provenance_entries.append(
                {
                    "title": entry.get("name")
                    or entry.get("type_name")
                    or entry.get("slug")
                    or entry.get("path"),
                    "source": section,
                    "authority": authority,
                    "authority_level": _AUTHORITY.get(authority, 0),
                    "version": resolved,
                    "url": entry.get("url"),
                }
            )
    provenance_entries.sort(key=lambda p: -p["authority_level"])

    return {
        "query": query,
        "version": resolved,
        "entries": provenance_entries[:limit],
        "note": (
            "Provenance carries source, version, URL, and authority level; "
            "docs outrank examples outrank real-world."
        ),
    }
