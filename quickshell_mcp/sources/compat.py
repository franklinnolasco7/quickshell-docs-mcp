"""Version-aware API compatibility checking for Quickshell.

Determines whether a Quickshell API, QML property, method, signal, type, or
implementation pattern is compatible with a specific Quickshell version.  It
reuses the existing version-management, doc-index, and type-page systems
(``_resolve_version``, ``list_versions``, ``_build_index``, ``_parse_members``)
and never infers compatibility from a single ``latest`` page alone: it
cross-references every published version and the changelog before reporting.
"""

from __future__ import annotations

import re
from difflib import get_close_matches
from typing import Any, TypedDict

import httpx

from ..caches import _cache_get, _cache_set
from ..config import BASE
from ..extraction import _fetch_page_markdown
from ..versions import _resolve_version, _version_sort_key, list_versions
from .docs import _build_index
from .qt_docs import _build_qt_index, _qt_docs_base, _resolve_qt_slug
from .validate import (
    _COMMON_QML_MEMBERS,
    _close_matches,
    _parse_members,
    _parse_structure,
    _qt_module_for_type,
    _tokenize,
)

_CHANGELOG_CACHE_KEY = "compat:changelog"
_CHANGELOG_VERSION_RE = re.compile(r"^##\s+(v\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)*)\s*$", re.MULTILINE)


def _changelog_sections() -> list[dict[str, str]]:
    """Split the changelog page into per-version sections, newest first.

    Returns ``[{version, url, text}]``.  Raw HTML is cached by ``_fetch_raw``;
    the extracted markdown is cached in-memory for the session.
    """
    cached = _cache_get(_CHANGELOG_CACHE_KEY)
    if cached is not None:
        return cached
    url = f"{BASE}/changelog/"
    markdown = _fetch_page_markdown(url)
    sections: list[dict[str, str]] = []
    pos = 0
    while True:
        match = _CHANGELOG_VERSION_RE.search(markdown, pos)
        if not match:
            break
        version = match.group(1)
        section_start = match.end()
        next_match = _CHANGELOG_VERSION_RE.search(markdown, section_start)
        section_end = next_match.start() if next_match else len(markdown)
        sections.append(
            {"version": version, "url": url, "text": markdown[section_start:section_end].strip()}
        )
        pos = section_end
    _cache_set(_CHANGELOG_CACHE_KEY, sections)
    return sections


def _changelog_hits(terms: list[str]) -> list[dict[str, str]]:
    """Search changelog sections for any of *terms* (word-boundary match).

    Returns recency-ordered ``[{version, url, text}]`` entries; empty when
    nothing matches.
    """
    hits: list[dict[str, str]] = []
    for section in _changelog_sections():
        matched_lines: list[str] = []
        for term in terms:
            pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
            for line in section["text"].splitlines():
                if pattern.search(line):
                    matched_lines.append(line.strip())
        if matched_lines:
            hits.append(
                {
                    "version": section["version"],
                    "url": section["url"],
                    "text": "\n".join(matched_lines[:5]),
                }
            )
    return hits


# Members start lowercase (exclusiveZone, onStatusChanged); types and
# namespaces are CamelCase.
_MEMBER_RE = re.compile(r"^[a-z]|^on[A-Z]")


class _ApiRef(TypedDict):
    namespace_hint: str | None
    type_name: str
    member: str | None


def _parse_api_ref(api: str) -> _ApiRef:
    """Split ``[Namespace.]Type[.member]`` into its parts.

    Returns ``{namespace_hint, type_name, member}``.  The trailing segment is
    treated as a member only when it starts lowercase (or ``on<Upper>``); all
    preceding segments form the type path.
    """
    parts = api.split(".")
    member: str | None = None
    type_end = len(parts)
    for i in range(len(parts) - 1, -1, -1):
        if _MEMBER_RE.match(parts[i]):
            member = parts[i]
            type_end = i
            break
    type_parts = parts[:type_end]
    if not type_parts:
        raise ValueError(f"'{api}' does not contain a type name")
    type_name = type_parts[-1]
    namespace_hint = ".".join(type_parts[:-1]) if len(type_parts) > 1 else None
    return {"namespace_hint": namespace_hint, "type_name": type_name, "member": member}


def _namespace_for_type(
    type_name: str, version: str, namespace_hint: str | None = None
) -> str | None:
    """Return the full namespace containing *type_name* in *version*'s index.

    With a *namespace_hint*, only namespaces that equal it or end with
    ``.hint`` (case-insensitive) are considered.  Without one, the first
    namespace containing the type wins.
    """
    index = _build_index(version)
    for ns, names in index["types_by_namespace"].items():
        if type_name not in names:
            continue
        if namespace_hint is None:
            return ns
        ns_lower = ns.lower()
        hint_lower = namespace_hint.lower()
        if ns_lower == hint_lower or ns_lower.endswith(f".{hint_lower}"):
            return ns
    return None


def _resolve_namespace(
    type_name: str, version: str, namespace_hint: str | None = None
) -> tuple[str | None, str | None]:
    """Resolve *type_name* to ``(quickshell_namespace, qt_module)``."""
    qs_ns = _namespace_for_type(type_name, version, namespace_hint)
    if qs_ns is not None:
        return qs_ns, None
    qt_module = _qt_module_for_type(type_name)
    if qt_module is not None:
        return None, qt_module
    return None, None


def _type_source_url(
    namespace: str | None, module: str | None, type_name: str, version: str
) -> str | None:
    if namespace:
        return f"{BASE}/docs/{version}/types/{namespace}/{type_name}/"
    if module:
        try:
            slug, _ = _resolve_qt_slug(type_name, module, None)
        except ValueError:
            return None
        return f"{_qt_docs_base(None)}/qml-{slug}.html"
    return None


def _type_members(type_name: str, namespace: str, version: str) -> dict[str, Any] | None:
    """Fetch and parse a type page, returning its members plus raw markdown.

    Returns ``{"properties", "signals", "methods", "base", "markdown"}`` or
    ``None`` when the page cannot be fetched.
    """
    url = f"{BASE}/docs/{version}/types/{namespace}/{type_name}/"
    try:
        markdown = _fetch_page_markdown(url)
    except (httpx.HTTPError, RuntimeError):
        return None
    members = _parse_members(markdown, source_url=url)
    return {
        "properties": members.properties,
        "signals": members.signals,
        "methods": members.methods,
        "base": members.base,
        "markdown": markdown,
    }


def _member_kind(members: dict[str, Any], name: str) -> str | None:
    """Classify *name* on a type as ``"property"``/``"signal"``/``"method"``
    or ``None`` when undocumented."""
    if name in members["properties"]:
        return "property"
    if name in members["signals"]:
        return "signal"
    if name in members["methods"]:
        return "method"
    return None


def _api_in_version(
    type_name: str,
    member: str | None,
    version: str,
    *,
    namespace_hint: str | None = None,
) -> dict[str, Any] | None:
    """Check whether *type_name* (and *member*) exists in *version*.

    Returns a result dict, or ``None`` when the version's index is unreachable.
    """
    if member is not None and member.endswith("()"):
        # "Type.method()" is how agents write method calls; strip the call
        # syntax so the lookup matches the documented method name.
        member = member[:-2]
    try:
        _build_index(version)
    except (httpx.HTTPError, RuntimeError):
        return None

    ns, module = _resolve_namespace(type_name, version, namespace_hint)
    if ns is None and module is None:
        return {
            "type_present": False,
            "member_present": None,
            "member_kind": None,
            "namespace": None,
            "module": None,
            "type_url": None,
            "members": None,
        }

    type_url = _type_source_url(ns, module, type_name, version)

    if member is None:
        return {
            "type_present": True,
            "member_present": None,
            "member_kind": None,
            "namespace": ns,
            "module": module,
            "type_url": type_url,
            "members": None,
        }

    # Common QML members (anchors, x, y, width, ...) exist on every
    # QObject-derived type regardless of the docs page listing them.
    if member in _COMMON_QML_MEMBERS:
        return {
            "type_present": True,
            "member_present": True,
            "member_kind": "property",
            "namespace": ns,
            "module": module,
            "type_url": type_url,
            "members": None,
        }

    if ns is None:
        # Qt type: the Quickshell docs don't host the page, so members are
        # not verifiable here.
        return {
            "type_present": True,
            "member_present": None,
            "member_kind": None,
            "namespace": ns,
            "module": module,
            "type_url": type_url,
            "members": None,
        }

    members = _type_members(type_name, ns, version)
    if members is None:
        return {
            "type_present": True,
            "member_present": None,
            "member_kind": None,
            "namespace": ns,
            "module": module,
            "type_url": type_url,
            "members": None,
        }

    kind = _member_kind(members, member)
    if kind is None and member.lower().endswith("changed"):
        # QML auto-generates onPropertyChanged change signals for every
        # property, so they are valid even when undocumented.
        prop_name = member[: -len("changed")]
        if prop_name in _COMMON_QML_MEMBERS or prop_name in members["properties"]:
            kind = "signal"

    return {
        "type_present": True,
        "member_present": kind is not None,
        "member_kind": kind,
        "namespace": ns,
        "module": module,
        "type_url": type_url,
        "members": members,
    }


def _scan_versions(
    type_name: str,
    member: str | None,
    *,
    namespace_hint: str | None = None,
    exclude: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Check API presence across every published version (newest first).

    Only versions whose index is reachable are included.  *exclude* skips
    versions already checked.
    """
    results: dict[str, dict[str, Any]] = {}
    for version in list_versions():
        if exclude and version in exclude:
            continue
        result = _api_in_version(type_name, member, version, namespace_hint=namespace_hint)
        if result is not None:
            results[version] = result
    return results


_CHANGELOG_RENAME_RE = re.compile(
    r"(?:has been )?renamed to\s+[`']?(?P<new_name>[\w.]+)[`']?",
    re.IGNORECASE,
)
_CHANGELOG_BREAKING_RE = re.compile(r"Breaking Changes", re.IGNORECASE)
_CHANGELOG_ADDED_RE = re.compile(r"^\s*Added\s+", re.IGNORECASE | re.MULTILINE)


def _analyze_changelog(type_name: str, member: str | None, target_version: str) -> dict[str, Any]:
    """Find changelog evidence for the given API.

    Returns ``{changelog_entry, change_info, documentation}`` with any of
    those keys omitted when there is nothing relevant.
    """
    label = _api_label(type_name, member)

    rename = _find_rename(type_name, member)
    if rename is not None:
        version, new_name = rename
        return {
            "changelog_entry": {
                "version": version,
                "url": f"{BASE}/changelog/",
                "text": f"'{label}' was renamed to '{new_name}'.",
            },
            "change_info": {
                "status": "renamed",
                "target_version": version,
                "detail": f"'{label}' was renamed to '{new_name}' in {version}.",
                "likely_replacement": new_name,
            },
            "documentation": [
                {
                    "kind": "changelog",
                    "version": version,
                    "url": f"{BASE}/changelog/",
                    "title": f"Changelog {version}",
                }
            ],
        }

    terms = [type_name] + ([member] if member else [])
    hits = _changelog_hits(terms)
    if not hits:
        return {}

    entry = hits[0]
    changelog_entry: dict[str, str] = {
        "version": entry["version"],
        "url": entry["url"],
        "text": entry["text"],
    }
    documentation = [
        {
            "kind": "changelog",
            "version": entry["version"],
            "url": entry["url"],
            "title": f"Changelog {entry['version']}",
        }
    ]

    target_hits = [h for h in hits if h["version"] == target_version]
    if target_hits and _CHANGELOG_BREAKING_RE.search(target_hits[0]["text"]):
        return {
            "changelog_entry": changelog_entry,
            "change_info": {
                "status": "changed",
                "target_version": target_version,
                "detail": f"'{label}' has a breaking-change entry in {target_version}.",
                "likely_replacement": None,
            },
            "documentation": documentation,
        }

    added_in: str | None = None
    for hit in hits:
        for line in hit["text"].splitlines():
            if not _CHANGELOG_ADDED_RE.match(line):
                continue
            if type_name not in line or (member is not None and member not in line):
                continue
            added_in = hit["version"]
            break
        if added_in:
            break

    change_info: dict[str, Any] | None = None
    if added_in:
        change_info = {
            "status": "introduced",
            "target_version": added_in,
            "detail": f"'{label}' was added in {added_in}.",
            "likely_replacement": None,
        }
    return {
        "changelog_entry": changelog_entry,
        "change_info": change_info,
        "documentation": documentation,
    }


def _find_rename(type_name: str, member: str | None) -> tuple[str, str] | None:
    """Return ``(version, new_name)`` when the changelog explicitly renames
    the API, scanning every section for a ``renamed to`` line mentioning it."""
    for section in _changelog_sections():
        for line in section["text"].splitlines():
            if "renamed to" not in line.lower() or type_name not in line:
                continue
            if member is not None and member not in line:
                continue
            match = _CHANGELOG_RENAME_RE.search(line)
            if match:
                return section["version"], match.group("new_name").rstrip(".")
    return None


def _check_deprecation(members: dict[str, Any] | None, member: str | None) -> str | None:
    """Return a short note when the type page marks *member* (or the type)
    as deprecated, else ``None``."""
    if members is None:
        return None
    markdown = members.get("markdown", "")
    if "deprecated" not in markdown.lower():
        return None
    if member is None:
        return "The type documentation marks this type as deprecated."
    for line in markdown.splitlines():
        if member in line and "deprecated" in line.lower():
            return f"'{member}' is marked as deprecated in the type documentation."
    return None


def _similar_type_names(needle: str, version: str, n: int = 5) -> list[str]:
    index = _build_index(version)
    all_names = [name for names in index["types_by_namespace"].values() for name in names]
    qt_index = _build_qt_index()
    all_names += [name for names in qt_index["modules"].values() for name in names]
    return _close_matches(needle, all_names, n=n)


def _similar_member_names(needle: str, members: dict[str, Any] | None, n: int = 3) -> list[str]:
    if members is None:
        return []
    candidates = list(members.get("properties", {}))
    candidates += list(members.get("signals", set()))
    candidates += list(members.get("methods", set()))
    matches = get_close_matches(needle, candidates, n=n, cutoff=0.4)
    if matches:
        return matches
    low = needle.lower()
    return [c for c in candidates if low in c.lower() or c.lower() in low][:n]


def _api_label(type_name: str, member: str | None) -> str:
    return f"{type_name}.{member}" if member else type_name


def _compat_at(
    type_name: str,
    member: str | None,
    version: str,
    *,
    namespace_hint: str | None = None,
) -> dict[str, Any]:
    """Determine the compatibility of one API with one Quickshell version."""
    label = _api_label(type_name, member)
    result = _api_in_version(type_name, member, version, namespace_hint=namespace_hint)

    if result is None:
        return {
            "compatibility": "uncertain",
            "target_version": version,
            "detected_api": {"type": type_name, "member": member, "origin": "unknown"},
            "earliest_known_version": None,
            "latest_known_version": None,
            "change_info": None,
            "changelog_entry": None,
            "documentation": [],
            "confidence": "low",
            "explanation": f"Could not reach the documentation index for {version}.",
        }

    ns = result["namespace"]
    module = result["module"]
    origin = "quickshell" if ns else ("qt" if module else "unknown")

    if not result["type_present"]:
        return _verdict_type_absent(
            type_name, member, version, label, origin, namespace_hint=namespace_hint
        )

    changelog_data = _analyze_changelog(type_name, member, version)

    if member and result["member_present"] is False:
        return _verdict_member_absent(
            type_name, member, version, label, result, changelog_data, namespace_hint=namespace_hint
        )

    confidence = "high"
    explanation = f"'{label}' exists in {version}."
    if member is not None and result["member_present"] is None:
        # Qt type or a member that could not be verified against the page.
        confidence = "medium"
        explanation = (
            f"'{type_name}' exists in {version}. Member '{member}' could not be "
            "verified against the type documentation."
        )
    elif origin == "qt":
        confidence = "medium"
        explanation = (
            f"'{label}' is a Qt/QML API, not a Quickshell type; its availability "
            "is governed by your Qt/QtQuick version, not the Quickshell one."
        )

    change_info = changelog_data.get("change_info")
    deprecation = _check_deprecation(result.get("members"), member)
    if deprecation:
        change_info = {
            "status": "deprecated",
            "target_version": version,
            "detail": deprecation,
            "likely_replacement": None,
        }
        confidence = "medium"
        explanation = f"'{label}' exists in {version} but is marked as deprecated."
    elif change_info and change_info.get("status") == "changed":
        explanation = f"'{label}' exists in {version} but has a breaking-change entry."

    documentation = list(changelog_data.get("documentation", []))
    if result["type_url"]:
        documentation.append(
            {
                "kind": "type_page",
                "version": version,
                "url": result["type_url"],
                "title": label,
            }
        )

    return {
        "compatibility": "compatible",
        "target_version": version,
        "detected_api": {"type": type_name, "member": member, "origin": origin, "namespace": ns},
        "earliest_known_version": version,
        "latest_known_version": version,
        "change_info": change_info,
        "changelog_entry": changelog_data.get("changelog_entry"),
        "documentation": documentation,
        "confidence": confidence,
        "explanation": explanation,
    }


def _verdict_type_absent(
    type_name: str,
    member: str | None,
    version: str,
    label: str,
    origin: str,
    *,
    namespace_hint: str | None,
) -> dict[str, Any]:
    """Build the verdict when the type is absent from the requested version."""
    scan = _scan_versions(type_name, member, namespace_hint=namespace_hint, exclude={version})
    present_versions = [v for v, r in scan.items() if r.get("type_present")]
    changelog_data = _analyze_changelog(type_name, member, version)
    change_info = changelog_data.get("change_info")

    if change_info and change_info.get("status") == "renamed":
        return {
            "compatibility": "incompatible",
            "target_version": version,
            "detected_api": {"type": type_name, "member": member, "origin": origin},
            "earliest_known_version": present_versions[-1] if present_versions else None,
            "latest_known_version": present_versions[0] if present_versions else None,
            "change_info": change_info,
            "changelog_entry": changelog_data.get("changelog_entry"),
            "documentation": changelog_data.get("documentation", []),
            "confidence": "high",
            "explanation": f"'{label}' was renamed and does not exist in {version}.",
        }

    close_for_rename = [
        name
        for name in _similar_type_names(type_name, version)
        if _namespace_for_type(name, version) is not None
    ]

    if present_versions:
        earliest = present_versions[-1]  # oldest present
        latest = present_versions[0]  # newest present
        if _version_sort_key(version) < _version_sort_key(earliest):
            status, detail = (
                "introduced",
                (f"'{label}' does not exist in {version}; it was introduced in {earliest}."),
            )
            replacement = None
        else:
            status, detail = (
                "removed",
                (f"'{label}' existed in {latest} but is absent in {version}."),
            )
            replacement = close_for_rename[0] if close_for_rename else None
        doc_url = _type_source_url(
            scan[latest].get("namespace"),
            scan[latest].get("module"),
            type_name,
            latest,
        )
        return {
            "compatibility": "incompatible",
            "target_version": version,
            "detected_api": {"type": type_name, "member": member, "origin": origin},
            "earliest_known_version": earliest,
            "latest_known_version": latest,
            "change_info": {
                "status": status,
                "target_version": earliest if status == "introduced" else version,
                "detail": detail,
                "likely_replacement": replacement,
            },
            "changelog_entry": changelog_data.get("changelog_entry"),
            "documentation": changelog_data.get("documentation", [])
            + (
                [{"kind": "type_page", "version": latest, "url": doc_url, "title": label}]
                if doc_url
                else []
            ),
            "confidence": "high",
            "explanation": detail,
        }

    # No trace in any published version or the Qt index.
    return {
        "compatibility": "uncertain",
        "target_version": version,
        "detected_api": {"type": type_name, "member": member, "origin": origin},
        "earliest_known_version": None,
        "latest_known_version": None,
        "change_info": {
            "status": "not_found",
            "target_version": version,
            "detail": (
                f"'{label}' was not found in any published Quickshell version or Qt documentation."
            ),
            "likely_replacement": close_for_rename[0] if close_for_rename else None,
        },
        "changelog_entry": changelog_data.get("changelog_entry"),
        "documentation": changelog_data.get("documentation", []),
        "confidence": "low",
        "explanation": (
            f"'{label}' was not found in any published Quickshell version or Qt documentation."
        ),
    }


def _verdict_member_absent(
    type_name: str,
    member: str,
    version: str,
    label: str,
    result: dict[str, Any],
    changelog_data: dict[str, Any],
    *,
    namespace_hint: str | None,
) -> dict[str, Any]:
    """Build the verdict when the type exists but the member does not."""
    ns = result["namespace"]
    module = result["module"]
    origin = "quickshell" if ns else ("qt" if module else "unknown")

    change_info = changelog_data.get("change_info")
    if change_info and change_info.get("status") == "renamed":
        return {
            "compatibility": "incompatible",
            "target_version": version,
            "detected_api": {
                "type": type_name,
                "member": member,
                "origin": origin,
                "namespace": ns,
            },
            "earliest_known_version": None,
            "latest_known_version": version,
            "change_info": change_info,
            "changelog_entry": changelog_data.get("changelog_entry"),
            "documentation": changelog_data.get("documentation", []),
            "confidence": "high",
            "explanation": f"'{label}' was renamed and does not exist in {version}.",
        }

    scan = _scan_versions(type_name, member, namespace_hint=namespace_hint, exclude={version})
    member_versions = [v for v, r in scan.items() if r.get("member_present")]
    similar = _similar_member_names(member, result.get("members"))

    if member_versions:
        earliest = member_versions[-1]  # oldest present
        latest = member_versions[0]  # newest present
        if _version_sort_key(version) <= _version_sort_key(earliest):
            status, detail, target = (
                "introduced",
                (f"'{label}' does not exist in {version}; it was introduced in {earliest}."),
                earliest,
            )
            doc_version, replacement = earliest, None
        else:
            # The member existed in an older version but is gone by the target.
            status, detail, target = (
                "removed",
                (f"'{label}' existed in {latest} but is absent in {version}."),
                version,
            )
            doc_version, replacement = latest, similar[0] if similar else None
        doc_url = _type_source_url(ns, module, type_name, doc_version)
        return {
            "compatibility": "incompatible",
            "target_version": version,
            "detected_api": {
                "type": type_name,
                "member": member,
                "origin": origin,
                "namespace": ns,
            },
            "earliest_known_version": earliest,
            "latest_known_version": latest,
            "change_info": {
                "status": status,
                "target_version": target,
                "detail": detail,
                "likely_replacement": replacement,
            },
            "changelog_entry": changelog_data.get("changelog_entry"),
            "documentation": changelog_data.get("documentation", [])
            + (
                [{"kind": "type_page", "version": doc_version, "url": doc_url, "title": label}]
                if doc_url
                else []
            ),
            "confidence": "high",
            "explanation": detail,
        }

    detail = f"'{label}' is not a documented property, signal, or method of '{type_name}'."
    explanation = (
        f"'{label}' does not exist in {version}. Did you mean '{similar[0]}'?"
        if similar
        else f"'{label}' does not exist in {version}."
    )
    documentation = list(changelog_data.get("documentation", []))
    if result["type_url"]:
        documentation.append(
            {"kind": "type_page", "version": version, "url": result["type_url"], "title": label}
        )
    return {
        "compatibility": "incompatible",
        "target_version": version,
        "detected_api": {"type": type_name, "member": member, "origin": origin, "namespace": ns},
        "earliest_known_version": None,
        "latest_known_version": version,
        "change_info": {
            "status": "not_found",
            "target_version": version,
            "detail": detail,
            "likely_replacement": similar[0] if similar else None,
        },
        "changelog_entry": changelog_data.get("changelog_entry"),
        "documentation": documentation,
        "confidence": "medium",
        "explanation": explanation,
    }


def _compat_from_code(code: str, version: str) -> dict[str, Any]:
    """Check every API referenced in a QML *code* snippet against *version*.

    Aggregates per-API findings; the overall verdict is ``incompatible`` when
    any referenced API is incompatible, ``uncertain`` when nothing could be
    resolved, else ``compatible``.
    """
    parsed = _parse_structure(_tokenize(code))
    if parsed.malformed:
        return {
            "compatibility": "uncertain",
            "target_version": version,
            "detected_api": {"kind": "code"},
            "earliest_known_version": None,
            "latest_known_version": None,
            "change_info": None,
            "changelog_entry": None,
            "documentation": [],
            "confidence": "low",
            "explanation": f"Could not parse the code snippet: {parsed.malformed}",
        }

    checks: list[tuple[str, str | None, str | None]] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for obj in parsed.objects:
        # Types may be written qualified (Quickshell.Hyprland.HyprlandMonitor);
        # resolve to the base type name plus its namespace so lookups succeed.
        parts = obj.raw.split(".")
        key: tuple[str, str | None, str | None] = (
            parts[-1],
            None,
            ".".join(parts[:-1]) if len(parts) > 1 else None,
        )
        if key not in seen:
            seen.add(key)
            checks.append(key)
    for binding in parsed.bindings:
        parts = binding.object_type.split(".")
        key = (
            parts[-1],
            binding.name,
            ".".join(parts[:-1]) if len(parts) > 1 else None,
        )
        if key not in seen:
            seen.add(key)
            checks.append(key)
    for handler in parsed.handlers:
        signal = handler.signal_name
        # QML handler names capitalize the first letter after "on" (onClosed
        # -> signal_name "Closed"), but the documented signal is lowercase.
        parts = handler.object_type.split(".")
        key = (
            parts[-1],
            signal[0].lower() + signal[1:] if signal else signal,
            ".".join(parts[:-1]) if len(parts) > 1 else None,
        )
        if key not in seen:
            seen.add(key)
            checks.append(key)

    if not checks:
        return {
            "compatibility": "uncertain",
            "target_version": version,
            "detected_api": {"kind": "code"},
            "earliest_known_version": None,
            "latest_known_version": None,
            "change_info": None,
            "changelog_entry": None,
            "documentation": [],
            "confidence": "low",
            "explanation": "No QML objects or property bindings found in the code snippet.",
        }

    findings = [
        _compat_at(type_name, member, version, namespace_hint=namespace_hint)
        for type_name, member, namespace_hint in checks
    ]

    verdicts = [f["compatibility"] for f in findings]
    if all(v == "compatible" for v in verdicts):
        compat, confidence = "compatible", "high"
        explanation = f"All referenced APIs in the code snippet are compatible with {version}."
    elif "incompatible" in verdicts:
        compat, confidence = "incompatible", "high"
        bad = [f for f in findings if f["compatibility"] == "incompatible"]
        labels = [_api_label(f["detected_api"]["type"], f["detected_api"]["member"]) for f in bad]
        explanation = f"Incompatible APIs found in {version}: {', '.join(labels)}."
    else:
        compat, confidence = "uncertain", "low"
        unknown = [f for f in findings if f["compatibility"] == "uncertain"]
        labels = [
            _api_label(f["detected_api"]["type"], f["detected_api"]["member"]) for f in unknown
        ]
        explanation = f"Could not verify compatibility for: {', '.join(labels)}."

    return {
        "compatibility": compat,
        "target_version": version,
        "detected_api": {"kind": "code"},
        "earliest_known_version": None,
        "latest_known_version": None,
        "change_info": None,
        "changelog_entry": None,
        "documentation": [],
        "confidence": confidence,
        "explanation": explanation,
        "findings": findings,
    }


def _incorporate_range(
    result: dict[str, Any],
    target_version: str,
    from_version: str,
    from_result: dict[str, Any],
    label: str,
) -> None:
    """Merge a lower-bound range check into *result*.

    Only an ``incompatible`` verdict counts as proof that the API was absent
    in a version; an ``uncertain`` one is not evidence of introduction or
    removal, so it never downgrades the target verdict.
    """
    to_compat = result["compatibility"]
    from_compat = from_result["compatibility"]

    if to_compat == "compatible" and from_compat == "compatible":
        result["explanation"] = (
            f"'{label}' is compatible with both {from_version} and {target_version}."
        )
    elif to_compat == "compatible" and from_compat == "incompatible":
        result["compatibility"] = "incompatible"
        result["explanation"] = (
            f"'{label}' is not compatible with {from_version} but is with {target_version}; "
            "it was introduced between those versions."
        )
        result["change_info"] = {
            "status": "introduced",
            "target_version": target_version,
            "detail": f"'{label}' was introduced between {from_version} and {target_version}.",
            "likely_replacement": None,
        }
    elif to_compat == "incompatible" and from_compat == "compatible":
        result["compatibility"] = "incompatible"
        result["explanation"] = (
            f"'{label}' is compatible with {from_version} but not with {target_version}."
        )
        result["change_info"] = {
            "status": "removed",
            "target_version": target_version,
            "detail": (
                f"'{label}' was removed or changed between {from_version} and {target_version}."
            ),
            "likely_replacement": None,
        }
    elif to_compat == "compatible" and from_compat == "uncertain":
        # The lower bound couldn't be verified, so introduction cannot be
        # claimed; the target verdict stands.
        result["explanation"] = (
            f"'{label}' is compatible with {target_version} but its presence in "
            f"{from_version} could not be verified."
        )


def _check_compatibility(
    api: str | None = None,
    type: str | None = None,
    code: str | None = None,
    version: str = "latest",
    from_version: str | None = None,
    to_version: str | None = None,
) -> dict[str, Any]:
    """Check whether a Quickshell API, type, or QML snippet is compatible with
    a specific Quickshell version.

    Exactly one of ``api``, ``type``, or ``code`` must be provided.  ``version``
    defaults to the latest published version; ``to_version`` overrides it and
    ``from_version`` adds a lower-bound range check.
    """
    provided = sum(1 for value in (api, type, code) if value is not None)
    if provided != 1:
        raise ValueError(f"Exactly one of api, type, or code must be provided (got {provided}).")

    target = to_version or version
    resolved = _resolve_version(target)
    resolved_from = _resolve_version(from_version) if from_version is not None else None

    if api is not None:
        ref = _parse_api_ref(api)
        type_name = ref["type_name"]
        member = ref["member"]
        namespace_hint = ref["namespace_hint"]
        result = _compat_at(type_name, member, resolved, namespace_hint=namespace_hint)
        if resolved_from is not None:
            from_result = _compat_at(
                type_name, member, resolved_from, namespace_hint=namespace_hint
            )
            _incorporate_range(
                result, resolved, resolved_from, from_result, _api_label(type_name, member)
            )
        result["from_version"] = resolved_from
        return result

    if type is not None:
        result = _compat_at(type, None, resolved)
        if resolved_from is not None:
            from_result = _compat_at(type, None, resolved_from)
            _incorporate_range(result, resolved, resolved_from, from_result, type)
        result["from_version"] = resolved_from
        return result

    result = _compat_from_code(code or "", resolved)
    if resolved_from is not None:
        result["from_version"] = resolved_from
        result["from_compatibility"] = _compat_from_code(code or "", resolved_from).get(
            "compatibility"
        )
    return result
