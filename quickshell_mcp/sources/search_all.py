"""Cross-source unified search: one natural-language query fanned out across
every indexed source (quickshell.org types/guides, doc.qt.io Qt types, the
official examples repo, Caelestia/Noctalia/dots-hyprland implementations).
This module only composes and ranks; every section delegates to the existing
per-source helpers, so caching and URL construction stay in one place."""

from __future__ import annotations

import re

from ..config import BASE, IMPLEMENTATION_REPOS, QT_DOCS_BASE
from .docs import _build_index, _search_guide_content
from .examples import _examples_listing
from .implementations import (
    _IMPL_QUERY_STOPWORDS,
    _IMPL_TOPICS,
    _impl_topics_for_query,
    _search_implementations,
)
from .qt_docs import _VALUE_TYPES_BUCKET, _build_qt_index

# Relevance tiers; higher means a more confident match. Exact type names beat
# substrings, Quickshell-specific hits beat generic Qt ones, real-world
# implementations rank by matched topic count.
_EXACT_QS_TYPE = 95
_SUBSTRING_QS_TYPE = 70
_NAMESPACE_MATCH = 50
_EXACT_QT_TYPE = 85
_SUBSTRING_QT_TYPE = 60
_SLUG_EXACT = 60
_SLUG_SUBSTRING = 45
_IMPL_TOPIC_BASE = 50
_IMPL_TOPIC_PER = 8
_IMPL_TOPIC_CAP = 80
_IMPL_TOKEN_ONLY = 40
_CONTENT_BASE = 30
_CONTENT_CAP = 58
_EXAMPLE_MATCH = 35
# Decisive but not absolute: a boosted impl section (max 80 + 15) still
# loses to an exact type name (85/95, + 5).
_INTENT_BOOST = 15

SECTION_TYPES = "quickshell_types"
SECTION_GUIDE_PAGES = "quickshell_guide_pages"
SECTION_GUIDE_CONTENT = "guide_content"
SECTION_QT_TYPES = "qt_types"
SECTION_EXAMPLES = "official_examples"
IMPL_SECTIONS = {src: f"{src}_implementations" for src in IMPLEMENTATION_REPOS}

_API_SECTIONS = (SECTION_TYPES, SECTION_QT_TYPES)
# Stable tie-break for sections whose best relevance is equal.
_CATEGORY_ORDER = (
    SECTION_TYPES,
    SECTION_GUIDE_PAGES,
    SECTION_GUIDE_CONTENT,
    SECTION_QT_TYPES,
    SECTION_EXAMPLES,
    *IMPL_SECTIONS.values(),
)


def _query_tokens(query: str) -> list[str]:
    return [
        token
        for token in re.split(r"[^a-z0-9]+", query.lower())
        if len(token) > 2 and token not in _IMPL_QUERY_STOPWORDS
    ]


def _search_quickshell_types(
    index: dict, version: str, tokens: list[str], query_lower: str, limit: int
) -> list[dict]:
    entries: list[dict] = []
    for ns, names in index["types_by_namespace"].items():
        ns_lower = ns.lower()
        if query_lower in ns_lower or any(token in ns_lower for token in tokens):
            entries.append(
                {
                    "kind": "namespace",
                    "namespace": ns,
                    "relevance": _NAMESPACE_MATCH,
                    "match_reason": "namespace name matches the query",
                    "hint": f"quickshell_list_types(namespace='{ns}') lists its types",
                }
            )
        for name in names:
            name_lower = name.lower()
            matched = [token for token in tokens if token in name_lower]
            exact = query_lower == name_lower or any(token == name_lower for token in tokens)
            substring = bool(matched) or query_lower in name_lower
            if not (exact or substring):
                continue
            hit = next((token for token in matched if token in name_lower), None)
            reason = "exact type name" if exact else f"type name contains '{hit or query_lower}'"
            entries.append(
                {
                    "kind": "api reference",
                    "namespace": ns,
                    "type_name": name,
                    "url": f"{BASE}/docs/{version}/types/{ns}/{name}/",
                    "relevance": _EXACT_QS_TYPE if exact else _SUBSTRING_QS_TYPE,
                    "match_reason": reason,
                    "_hits": len(matched),
                }
            )
    # Within a tier, a type matching more of the query's words wins:
    # HyprlandWorkspace beats HyprlandEvent for "hyprland workspace".
    type_entries = sorted(
        (entry for entry in entries if entry["kind"] == "api reference"),
        key=lambda entry: (-entry["relevance"], -entry["_hits"], str(entry.get("type_name") or "")),
    )
    # Namespace hits survive the limit: they carry no page of their own but
    # tell the caller where a group of types lives.
    namespace_entries = sorted(
        (entry for entry in entries if entry["kind"] == "namespace"),
        key=lambda entry: entry["namespace"],
    )
    for entry in type_entries:
        entry.pop("_hits", None)
    return type_entries[:limit] + namespace_entries[:2]


def _search_guide_slugs(
    index: dict, version: str, tokens: list[str], query_lower: str, limit: int
) -> list[dict]:
    entries: list[dict] = []
    for slug in index["guide_pages"]:
        slug_lower = slug.lower()
        exact = query_lower == slug_lower or any(token == slug_lower for token in tokens)
        if (
            not exact
            and query_lower not in slug_lower
            and not any(token in slug_lower for token in tokens)
        ):
            continue
        entries.append(
            {
                "kind": "guide page",
                "slug": slug,
                "url": f"{BASE}/docs/{version}/guide/{slug}/",
                "relevance": _SLUG_EXACT if exact else _SLUG_SUBSTRING,
                "match_reason": (
                    "guide page title matches" if exact else "guide page title contains the query"
                ),
            }
        )
    entries.sort(key=lambda entry: (-entry["relevance"], entry["slug"]))
    return entries[:limit]


def _decorate_guide_content(query: str, version: str, limit: int) -> list[dict]:
    decorated: list[dict] = []
    for match in _search_guide_content(query, version, limit=limit):
        match["kind"] = "guide text match"
        match["relevance"] = min(_CONTENT_CAP, _CONTENT_BASE + match["occurrences"])
        match["match_reason"] = f"{match['occurrences']} occurrence(s) in the guide body"
        decorated.append(match)
    return decorated


def _search_qt_types(tokens: list[str], query_lower: str, limit: int) -> list[dict]:
    modules = _build_qt_index()["modules"]
    entries: list[dict] = []
    for module, names in modules.items():
        for name in names:
            name_lower = name.lower()
            matched = [token for token in tokens if token in name_lower]
            exact = query_lower == name_lower or any(token == name_lower for token in tokens)
            if not exact and not matched and query_lower not in name_lower:
                continue
            slug = name_lower if module == _VALUE_TYPES_BUCKET else f"{module}-{name_lower}"
            hit = next((token for token in matched if token in name_lower), None)
            entries.append(
                {
                    "kind": "qt api reference",
                    "module": module,
                    "type_name": name,
                    "url": f"{QT_DOCS_BASE}/qml-{slug}.html",
                    "relevance": _EXACT_QT_TYPE if exact else _SUBSTRING_QT_TYPE,
                    "match_reason": (
                        "exact type name" if exact else f"type name contains '{hit or query_lower}'"
                    ),
                    "_hits": len(matched),
                }
            )
    entries.sort(
        key=lambda entry: (
            -entry["relevance"],
            -entry["_hits"],
            entry["module"],
            entry["type_name"],
        )
    )
    for entry in entries:
        entry.pop("_hits", None)
    return entries[:limit]


def _search_examples_root(tokens: list[str], query_lower: str, limit: int) -> list[dict]:
    listing = _examples_listing("")
    entries: list[dict] = []
    for item in listing["entries"]:
        path_lower = item["path"].lower()
        if query_lower not in path_lower and not any(token in path_lower for token in tokens):
            continue
        entries.append(
            {
                "kind": "official example",
                "path": item["path"],
                "entry_type": item["type"],
                "repo": listing["repo"],
                "branch": listing["branch"],
                "relevance": _EXAMPLE_MATCH,
                "match_reason": "example name/path matches the query",
                "read_with": f"quickshell_get_example(path='{item['path']}')",
            }
        )
    entries.sort(key=lambda entry: entry["path"])
    return entries[:limit]


def _search_impl_source(source: str, query: str, tokens: list[str], limit: int) -> list[dict]:
    section_entries: list[dict] = []
    for meta in _search_implementations(source, query, limit):
        topics = meta.get("topics") or []
        if topics:
            relevance = min(_IMPL_TOPIC_CAP, _IMPL_TOPIC_BASE + _IMPL_TOPIC_PER * len(topics))
            reason = "implementation topic(s): " + ", ".join(topics)
        elif not tokens:
            relevance, reason = _IMPL_TOKEN_ONLY, "structural tour (broad query)"
        else:
            relevance, reason = _IMPL_TOKEN_ONLY, "query token appears in the file path"
        meta["relevance"] = relevance
        meta["match_reason"] = reason
        section_entries.append(meta)
    return section_entries


def _search_everything(
    query: str, version: str, include_content: bool = False, limit_per_source: int = 4
) -> dict:
    """Fan `query` across all indexed sources and group + rank the results."""
    limit = max(1, min(int(limit_per_source), 10))
    tokens = _query_tokens(query)
    query_lower = query.lower().strip()
    errors: dict[str, str] = {}
    sections: dict[str, list[dict]] = {}

    if not query_lower:
        return {
            "query": query,
            "version": version,
            "total_matches": 0,
            "results": {},
            "section_order": [],
            "errors": {},
            "note": "Empty query. Pass keywords, a type name, or an implementation topic.",
        }

    def attempt(section: str, builder) -> None:
        try:
            entries = builder()
        except Exception as error:  # noqa: BLE001 - one flaky source must not sink the rest
            errors[section] = str(error)
            return
        if entries:
            sections[section] = entries

    attempt(
        SECTION_TYPES,
        lambda: _search_quickshell_types(
            _build_index(version), version, tokens, query_lower, limit
        ),
    )
    attempt(
        SECTION_GUIDE_PAGES,
        lambda: _search_guide_slugs(_build_index(version), version, tokens, query_lower, limit),
    )
    if include_content:
        attempt(SECTION_GUIDE_CONTENT, lambda: _decorate_guide_content(query, version, limit))
    attempt(SECTION_QT_TYPES, lambda: _search_qt_types(tokens, query_lower, limit))
    attempt(SECTION_EXAMPLES, lambda: _search_examples_root(tokens, query_lower, limit))
    for source, section in IMPL_SECTIONS.items():
        attempt(section, lambda source=source: _search_impl_source(source, query, tokens, limit))

    if errors and not sections:
        raise ValueError(f"Every source failed: {errors}")

    impl_topics = _impl_topics_for_query(query)
    api_intent = any(
        entry["relevance"] >= _EXACT_QT_TYPE
        for section in _API_SECTIONS
        for entry in sections.get(section, [])
    )

    def order_key(section: str) -> tuple[int, int]:
        best = max(entry["relevance"] for entry in sections[section])
        if section in IMPL_SECTIONS.values() and impl_topics:
            best += _INTENT_BOOST
        if section in _API_SECTIONS and api_intent:
            best += _INTENT_BOOST
        return (-best, _CATEGORY_ORDER.index(section))

    section_order = sorted(sections, key=order_key)

    note_parts: list[str] = ["grouped by source, most relevant group first"]
    if impl_topics:
        matched_keys = ", ".join(topic_key for topic_key, _, _ in impl_topics)
        note_parts.append(f"implementation topics detected: {matched_keys}")
    if api_intent:
        note_parts.append("exact API/type matches ranked first")
    note_parts.append(
        "follow up with quickshell_get_type / quickshell_get_guide_page / "
        "quickshell_get_qt_type / quickshell_get_example / quickshell_get_implementation"
    )
    if not include_content:
        note_parts.append("include_content=True also full-text-searches guide bodies")
    if errors:
        note_parts.append("unavailable sources: " + ", ".join(errors))
    if not sections:
        topic_keys = ", ".join(topic_key for topic_key, _, _, _ in _IMPL_TOPICS)
        note_parts.insert(
            0,
            "No matches. Searched: quickshell types, guide pages, Qt types, "
            f"official examples, and the implementation shells ({topic_keys} "
            "are known implementation topics). Try shorter keywords or a type name.",
        )

    return {
        "query": query,
        "version": version,
        "total_matches": sum(len(entries) for entries in sections.values()),
        "results": sections,
        "section_order": section_order,
        "errors": errors,
        "note": "; ".join(note_parts),
    }
