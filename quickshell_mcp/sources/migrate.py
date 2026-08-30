"""Migration analysis for Quickshell/QML code across Quickshell versions.

Determines what a QML config (or a single API/type) must change to keep
working after upgrading from one Quickshell version to another.  It is an
orchestrator over the compatibility and changelog machinery in ``compat``:
per-symbol verdicts come from ``_compat_at`` at both endpoints, and the
changelog sections strictly between the versions drive the intermediate
and breaking-change findings that an endpoint comparison alone would miss
(a rename that landed at an intermediate release is reported with the
version it landed in, not as a vague "sometime between").

The tool reports; it never rewrites code.  Findings are classified
``definite`` (backed by the docs or changelog), ``likely`` (documented but
low-impact, e.g. a deprecation), or ``manual_review`` (evidence points at a
change but the exact migration is not provable).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, TypedDict

import httpx

from ..config import BASE
from ..versions import _resolve_version, _version_sort_key
from .compat import (
    _api_label,
    _changelog_sections,
    _compat_at,
    _parse_api_ref,
    _type_members,
)
from .docs import _build_index
from .validate import _close_matches, _parse_structure, _tokenize

# "Use Foo instead." directions inside changelog and type-page notes are the
# strongest documented replacement evidence the site gives us.
_REPLACEMENT_RE = re.compile(r"use\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s+instead", re.IGNORECASE)
_BREAKING_HEADING_RE = re.compile(r"^##\s+Breaking Changes", re.IGNORECASE)
_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


class _MigrationIssue(TypedDict):
    line: int | None
    column: int | None
    file: str | None
    severity: str  # error | warning | info
    classification: str  # definite | likely | manual_review
    confidence: str  # high | medium | low
    status: str  # renamed | removed | deprecated | changed | introduced |
    #              not_found | import_removed | behavior | malformed | cannot_verify
    code: str
    old_api: str
    new_api: str | None
    reason: str
    suggestion: str
    changed_in_version: str | None
    source: dict | None  # {"text", "url", "version"}


class _ApiRef(TypedDict):
    type_name: str
    member: str | None
    namespace_hint: str | None
    line: int | None
    col: int | None


def _term_re(term: str) -> re.Pattern[str]:
    return re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)


def _collect_api_refs(parsed: Any) -> list[_ApiRef]:
    """Every distinct (type, member) referenced by a parsed snippet, with the
    location of its first occurrence.

    Mirrors the normalization ``_compat_from_code`` uses so lookups resolve
    the same way: qualified names are split into base type plus namespace, and
    handler names are lowercased to the documented signal name.
    """
    refs: list[_ApiRef] = []
    seen: set[tuple[str, str | None, str | None]] = set()

    def add(
        type_name: str,
        member: str | None,
        ns: str | None,
        line: int | None,
        col: int | None,
    ) -> None:
        key = (type_name, member, ns)
        if key in seen:
            return
        seen.add(key)
        refs.append(
            {
                "type_name": type_name,
                "member": member,
                "namespace_hint": ns,
                "line": line,
                "col": col,
            }
        )

    for obj in parsed.objects:
        parts = obj.raw.split(".")
        ns = ".".join(parts[:-1]) if len(parts) > 1 else None
        add(parts[-1], None, ns, obj.line, obj.col)
    for binding in parsed.bindings:
        parts = binding.object_type.split(".")
        ns = ".".join(parts[:-1]) if len(parts) > 1 else None
        add(parts[-1], binding.name, ns, binding.line, binding.col)
    for handler in parsed.handlers:
        signal = handler.signal_name
        member = signal[0].lower() + signal[1:] if signal else signal
        parts = handler.object_type.split(".")
        ns = ".".join(parts[:-1]) if len(parts) > 1 else None
        add(parts[-1], member, ns, handler.line, handler.col)
    return refs


def _drop_local_refs(refs: list[_ApiRef], filename: str | None) -> list[_ApiRef]:
    """A type matching the filename stem is a sibling component, not a docs
    type, so it and its members must never be flagged."""
    stem = Path(filename).stem if filename else None
    if not stem:
        return refs
    return [ref for ref in refs if ref["type_name"] != stem]


def _issue(
    *,
    location: dict | None,  # {"line": int, "column": int}
    severity: str,
    classification: str,
    confidence: str,
    status: str,
    old_api: str,
    new_api: str | None,
    reason: str,
    suggestion: str,
    changed_in_version: str | None,
    source: dict | None,
    file: str | None = None,
) -> _MigrationIssue:
    return {
        "line": location["line"] if location else None,
        "column": location["column"] if location else None,
        "file": file,
        "severity": severity,
        "classification": classification,
        "confidence": confidence,
        "status": status,
        "code": f"migration_{status}",
        "old_api": old_api,
        "new_api": new_api,
        "reason": reason,
        "suggestion": suggestion,
        "changed_in_version": changed_in_version,
        "source": source,
    }


def _first_doc(verdict: dict[str, Any]) -> dict | None:
    """The changelog or type-page citation from a compat verdict, if any."""
    docs = verdict.get("documentation") or []
    for doc in docs:
        if doc.get("kind") == "changelog":
            return {
                "text": "quickshell.org changelog",
                "url": doc["url"],
                "version": doc.get("version"),
            }
    for doc in docs:
        if doc.get("kind") == "type_page":
            return {
                "text": "quickshell.org type docs",
                "url": doc["url"],
                "version": doc.get("version"),
            }
    return None


def _replacement_from_text(text: str) -> str | None:
    match = _REPLACEMENT_RE.search(text)
    return match.group(1) if match else None


def _deprecated_replacement(
    type_name: str,
    member: str | None,
    namespace: str | None,
    version: str,
) -> str | None:
    """The ``Use Foo instead`` direction from the type page, when the member
    is documented as deprecated there."""
    if member is None or namespace is None:
        return None
    members = _type_members(type_name, namespace, version)
    if members is None:
        return None
    for line in members.get("markdown", "").splitlines():
        if member not in line or "deprecated" not in line.lower():
            continue
        replacement = _replacement_from_text(line)
        if replacement:
            return replacement
    return None


def _type_is_deprecated(type_name: str, namespace: str | None, version: str) -> bool:
    """Whether the type page deprecates the type itself, not just a member.

    The compat check treats any page containing the word "deprecated" as a
    deprecated type; for migration only a page that says so about the type
    name should suppress nothing, so this is a stricter re-check.
    """
    if namespace is None:
        return False
    members = _type_members(type_name, namespace, version)
    if members is None:
        return False
    for line in members.get("markdown", "").splitlines():
        if type_name in line and "deprecated" in line.lower():
            return True
    return False


def _symbol_issue(
    ref: _ApiRef,
    from_version: str,
    to_version: str,
) -> _MigrationIssue | None:
    """Compare one symbol against both endpoints and classify the migration.

    Returns ``None`` when the symbol is compatible in both versions and has no
    documented deprecation or breaking change.
    """
    type_name = ref["type_name"]
    member = ref["member"]
    namespace_hint = ref["namespace_hint"]
    label = _api_label(type_name, member)
    location = {"line": ref["line"], "column": ref["col"]} if ref["line"] is not None else None

    to_result = _compat_at(type_name, member, to_version, namespace_hint=namespace_hint)
    from_result = _compat_at(type_name, member, from_version, namespace_hint=namespace_hint)

    to_compat = to_result["compatibility"]
    from_compat = from_result["compatibility"]
    change_info: dict[str, Any] | None = to_result.get("change_info")
    status = change_info.get("status") if change_info else None
    confidence = to_result.get("confidence", "low")
    source = _first_doc(to_result)

    if to_compat == "uncertain":
        status = status or "not_found"
        new_api = change_info.get("likely_replacement") if change_info else None
        return _issue(
            location=location,
            severity="info",
            classification="manual_review",
            confidence=confidence,
            status=status,
            old_api=label,
            new_api=new_api,
            reason=to_result["explanation"],
            suggestion=(f"Confirm whether '{label}' exists in {to_version} before migrating."),
            changed_in_version=None,
            source=source,
        )

    if to_compat == "incompatible":
        if status == "renamed":
            new_api = change_info.get("likely_replacement") if change_info else None
            renamed_in = change_info.get("target_version") if change_info else None
            return _issue(
                location=location,
                severity="error",
                classification="definite",
                confidence="high",
                status="renamed",
                old_api=label,
                new_api=new_api,
                reason=(f"'{label}' was renamed and does not exist in {to_version}."),
                suggestion=(f"Replace '{label}' with '{new_api}' (renamed in {renamed_in})."),
                changed_in_version=renamed_in,
                source=source,
            )

        if status in ("removed", None):
            # Present in some older version, gone by the target.  A documented
            # replacement ("Use Foo instead") makes the migration definite;
            # without one the removal is still definite but the replacement is
            # a guess and must be reviewed.
            changelog_entry = to_result.get("changelog_entry") or {}
            changelog_text = changelog_entry.get("text", "")
            replacement = _replacement_from_text(changelog_text)
            fuzzy = change_info.get("likely_replacement") if change_info else None
            if replacement is None and fuzzy:
                replacement = fuzzy
            # The removal version is the changelog release that names the API
            # when there is one; otherwise fall back to the compat verdict.
            removed_in = None
            if type_name in changelog_text or (member and member in changelog_text):
                removed_in = changelog_entry.get("version")
            if removed_in is None:
                removed_in = change_info.get("target_version") if change_info else None
            if replacement and _replacement_from_text(changelog_text):
                return _issue(
                    location=location,
                    severity="error",
                    classification="definite",
                    confidence="high",
                    status="removed",
                    old_api=label,
                    new_api=replacement,
                    reason=(
                        f"'{label}' was removed; the changelog directs migrating "
                        f"to '{replacement}'."
                    ),
                    suggestion=f"Replace '{label}' with '{replacement}'.",
                    changed_in_version=removed_in,
                    source=source,
                )
            if replacement:
                return _issue(
                    location=location,
                    severity="warning",
                    classification="manual_review",
                    confidence="medium",
                    status="removed",
                    old_api=label,
                    new_api=replacement,
                    reason=(
                        f"'{label}' was removed and a possible replacement is "
                        f"'{replacement}', but it is not documented explicitly."
                    ),
                    suggestion=(
                        f"Verify '{replacement}' against the {to_version} docs "
                        f"before replacing '{label}' with it."
                    ),
                    changed_in_version=removed_in,
                    source=source,
                )
            return _issue(
                location=location,
                severity="error" if from_compat == "compatible" else "warning",
                classification="definite" if from_compat == "compatible" else "manual_review",
                confidence=confidence,
                status="removed",
                old_api=label,
                new_api=None,
                reason=(f"'{label}' was removed and no replacement is documented."),
                suggestion=(f"Remove or rework usage of '{label}' for {to_version}."),
                changed_in_version=removed_in,
                source=source,
            )

        if status == "introduced":
            introduced_in = change_info.get("target_version") if change_info else None
            return _issue(
                location=location,
                severity="warning",
                classification="manual_review",
                confidence=confidence,
                status="introduced",
                old_api=label,
                new_api=None,
                reason=(
                    f"'{label}' is not available in {to_version}; it is "
                    f"introduced in {introduced_in}."
                ),
                suggestion=(
                    f"'{label}' does not exist yet in {to_version}; do not "
                    "introduce it in migrated code."
                ),
                changed_in_version=introduced_in,
                source=source,
            )

        new_api = change_info.get("likely_replacement") if change_info else None
        return _issue(
            location=location,
            severity="info",
            classification="manual_review",
            confidence=confidence,
            status="not_found",
            old_api=label,
            new_api=new_api,
            reason=to_result["explanation"],
            suggestion=f"Resolve '{label}' manually against the {to_version} docs.",
            changed_in_version=None,
            source=source,
        )

    # to_compat == "compatible"
    if status == "deprecated":
        if member is None and not _type_is_deprecated(
            type_name, to_result["detected_api"].get("namespace"), to_version
        ):
            return None
        new_api = _deprecated_replacement(
            type_name,
            member,
            to_result["detected_api"].get("namespace"),
            to_version,
        )
        return _issue(
            location=location,
            severity="warning",
            classification="likely",
            confidence="medium",
            status="deprecated",
            old_api=label,
            new_api=new_api,
            reason=f"'{label}' exists in {to_version} but is marked as deprecated.",
            suggestion=(
                f"Plan to replace '{label}'"
                + (f" with '{new_api}'" if new_api else "")
                + "; it still works but may be removed later."
            ),
            changed_in_version=None,
            source=source,
        )

    if status == "changed":
        new_api = change_info.get("likely_replacement") if change_info else None
        detail = change_info.get("detail") if change_info else None
        target = change_info.get("target_version") if change_info else None
        return _issue(
            location=location,
            severity="warning",
            classification="manual_review",
            confidence="medium",
            status="changed",
            old_api=label,
            new_api=new_api,
            reason=detail or to_result["explanation"],
            suggestion=f"Review how '{label}' is used; its behavior may have changed.",
            changed_in_version=target,
            source=source,
        )

    if from_compat == "incompatible":
        introduced_in = (from_result.get("change_info") or {}).get("target_version")
        return _issue(
            location=location,
            severity="info",
            classification="manual_review",
            confidence="medium",
            status="introduced",
            old_api=label,
            new_api=None,
            reason=(
                f"'{label}' is available in {to_version} but not in the source {from_version}."
            ),
            suggestion=(
                f"The code already uses '{label}', which requires at least "
                f"{introduced_in}; confirm the source version is accurate."
            ),
            changed_in_version=introduced_in,
            source=source,
        )

    return None


def _filter_subsumed(issues: list[_MigrationIssue]) -> list[_MigrationIssue]:
    """Drop member-level issues when the owning type is gone or unknown.

    A removed, renamed, or unresolved type makes every member finding
    redundant noise; a merely deprecated type keeps its member findings,
    which carry the actionable replacement.
    """
    gone = {"removed", "renamed", "not_found", "introduced"}
    gone_types = {
        issue["old_api"]
        for issue in issues
        if "." not in issue["old_api"] and issue["status"] in gone
    }
    if not gone_types:
        return issues
    return [
        issue
        for issue in issues
        if "." not in issue["old_api"] or issue["old_api"].split(".")[0] not in gone_types
    ]


def _breaking_lines(section_text: str) -> list[str]:
    """The ``- item`` bullets under a ``## Breaking Changes`` heading."""
    lines = section_text.splitlines()
    in_breaking = False
    bullets: list[str] = []
    for line in lines:
        if _BREAKING_HEADING_RE.match(line):
            in_breaking = True
            continue
        if in_breaking and line.startswith("## "):
            break
        if in_breaking and line.strip().startswith("- "):
            bullets.append(line.strip())
    return bullets


def _dotted_members(line: str) -> set[str]:
    """Member names referenced as ``Type.member`` in a line."""
    return set(re.findall(r"\b[A-Z]\w*\.([a-z]\w*)", line))


def _term_matches_line(term: str, line: str) -> bool:
    """True when a changelog line mentions *term* in a relevant way.

    A member term matches on a standalone word boundary; a type term matches
    only when it appears standalone and not merely as a qualifier for a
    member-specific change (e.g. ``PanelWindow.layer`` does not match the
    type term ``PanelWindow``).
    """
    if not term:
        return False
    if term[0].islower() or term.startswith("on"):
        return _term_re(term).search(line) is not None
    return re.search(rf"\b{re.escape(term)}\b(?!\.)", line) is not None


def _behavioral_scan(
    terms: set[str],
    skip_terms: set[str],
    from_version: str,
    to_version: str,
    term_location: dict[str, dict | None],
) -> list[_MigrationIssue]:
    """Breaking-changelog entries between the versions that mention a used
    symbol, reported as review-only findings.

    A changelog line is evidence a change happened, not proof that a specific
    usage is affected, so these are always ``manual_review``.
    """
    scannable = terms - skip_terms
    if not scannable:
        return []
    findings: list[_MigrationIssue] = []
    for section in _changelog_sections():
        version = section["version"]
        if not (
            _version_sort_key(from_version)
            < _version_sort_key(version)
            <= _version_sort_key(to_version)
        ):
            continue
        for line in _breaking_lines(section["text"]):
            matched = [term for term in scannable if _term_matches_line(term, line)]
            if not matched:
                continue
            location = next(
                (term_location[term] for term in matched if term in term_location),
                None,
            )
            findings.append(
                _issue(
                    location=location,
                    severity="warning",
                    classification="manual_review",
                    confidence="low",
                    status="behavior",
                    old_api=line,
                    new_api=None,
                    reason=(
                        f"A breaking-change entry in {version} mentions symbols used in the code."
                    ),
                    suggestion=(
                        f"Review the changelog entry from {version} and adjust the affected usage."
                    ),
                    changed_in_version=version,
                    source={
                        "text": "quickshell.org changelog",
                        "url": section["url"],
                        "version": version,
                    },
                )
            )
    return findings


def _import_diff(parsed: Any, from_version: str, to_version: str) -> list[_MigrationIssue]:
    """Imports that referenced a Quickshell namespace dropped by the target."""

    def _index_namespaces(version: str) -> set[str] | None:
        try:
            return set(_build_index(version)["types_by_namespace"])
        except (httpx.HTTPError, RuntimeError):
            return None

    from_namespaces = _index_namespaces(from_version)
    to_namespaces = _index_namespaces(to_version)
    if from_namespaces is None or to_namespaces is None:
        return [
            _issue(
                location=None,
                severity="info",
                classification="manual_review",
                confidence="low",
                status="cannot_verify",
                old_api="",
                new_api=None,
                reason="Could not load the docs index for one or both versions.",
                suggestion="Ensure the versions exist and their docs indexes are reachable.",
                changed_in_version=None,
                source=None,
            )
        ]
    findings: list[_MigrationIssue] = []
    seen: set[str] = set()
    for imp in parsed.imports:
        module = imp.module
        if module in seen:
            continue
        seen.add(module)
        if not (module in from_namespaces or module in to_namespaces):
            continue  # Qt or third-party modules are out of scope
        if module in from_namespaces and module not in to_namespaces:
            candidates = _close_matches(module, sorted(to_namespaces), n=2)
            replacement = candidates[0] if candidates else None
            findings.append(
                _issue(
                    location={"line": imp.line, "column": imp.col},
                    severity="warning",
                    classification="manual_review",
                    confidence="medium",
                    status="import_removed",
                    old_api=f"import {module}",
                    new_api=f"import {replacement}" if replacement else None,
                    reason=(
                        f"The namespace '{module}' exists in {from_version} but "
                        f"is absent from {to_version}."
                    ),
                    suggestion=(
                        "Update or remove the import"
                        + (f", for example 'import {replacement}'" if replacement else "")
                        + "."
                    ),
                    changed_in_version=None,
                    source={
                        "text": "quickshell.org docs index",
                        "url": f"{BASE}/docs/{to_version}/guide/",
                        "version": to_version,
                    },
                )
            )
    return findings


def _verdict(issues: list[_MigrationIssue]) -> str:
    if not issues:
        return "compatible"
    if any(issue["severity"] in ("error", "warning") for issue in issues):
        return "changes_required"
    if any(issue["status"] in ("not_found", "cannot_verify") for issue in issues):
        return "uncertain"
    return "compatible"


def _migration_plan(issues: list[_MigrationIssue], from_version: str, to_version: str) -> list[str]:
    if not issues:
        return [f"No API migration is required to go from {from_version} to {to_version}."]

    def sort_key(issue: _MigrationIssue) -> tuple[bool, Any, int]:
        version = issue["changed_in_version"]
        return (
            version is None,
            _version_sort_key(version) if version else (),
            _SEVERITY_ORDER.get(issue["severity"], 3),
        )

    steps: list[str] = []
    for issue in sorted(issues, key=sort_key):
        version = f" in {issue['changed_in_version']}" if issue["changed_in_version"] else ""
        status = issue["status"]
        if status == "renamed":
            step = f"Rename {issue['old_api']} to {issue['new_api']} (renamed{version})."
        elif status == "removed":
            if issue["new_api"]:
                step = f"Replace {issue['old_api']} with {issue['new_api']} (removed{version})."
            else:
                step = f"Remove or rework {issue['old_api']} (removed{version})."
        elif status == "deprecated":
            step = f"Replace deprecated {issue['old_api']}."
        elif status == "import_removed":
            step = f"Update or remove {issue['old_api']} (absent in {to_version})."
        elif status == "behavior":
            step = f"Review breaking-change note{version}: {issue['old_api']}"
        elif status == "introduced":
            step = (
                f"Note: {issue['old_api']} is not available in {from_version}"
                f" (introduced{version})."
            )
        else:
            step = f"Review {issue['old_api']} manually: {issue['reason']}"
        steps.append(f"{step} [{issue['classification']}]")
    return steps


def _migrate(
    from_version: str,
    to_version: str,
    code: str | None = None,
    api: str | None = None,
    type: str | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    """Analyze what a QML snippet (or a single API/type) must change to move
    from *from_version* to *to_version*.

    Exactly one of ``code``, ``api``, or ``type`` must be provided.  Both
    versions are required and must be ordered oldest to newest.  Returns a
    report of classified migration issues plus an ordered plan; it never
    rewrites the code.
    """
    provided = sum(1 for value in (code, api, type) if value is not None)
    if provided != 1:
        raise ValueError(f"Exactly one of code, api, or type must be provided (got {provided}).")
    if not from_version or not to_version:
        raise ValueError("Both from_version and to_version are required.")

    resolved_from = _resolve_version(from_version)
    resolved_to = _resolve_version(to_version)
    if _version_sort_key(resolved_from) > _version_sort_key(resolved_to):
        raise ValueError(
            f"from_version {resolved_from} is newer than to_version {resolved_to}; "
            "the range must be ordered oldest to newest."
        )

    issues: list[_MigrationIssue] = []
    refs: list[_ApiRef] = []
    terms: set[str] = set()
    flagged_terms: set[str] = set()
    term_location: dict[str, dict | None] = {}
    parsed = None

    if code is not None:
        parsed = _parse_structure(_tokenize(code))
        if parsed.malformed:
            issues.append(
                _issue(
                    location=None,
                    severity="error",
                    classification="manual_review",
                    confidence="high",
                    status="malformed",
                    old_api=code.strip().splitlines()[-1] if code.strip() else "",
                    new_api=None,
                    reason=f"Could not parse the code: {parsed.malformed}",
                    suggestion="Fix the QML syntax before migrating.",
                    changed_in_version=None,
                    source=None,
                )
            )
        elif not parsed.objects and not parsed.imports:
            issues.append(
                _issue(
                    location=None,
                    severity="info",
                    classification="manual_review",
                    confidence="low",
                    status="cannot_verify",
                    old_api="",
                    new_api=None,
                    reason="No QML objects or imports found in the code.",
                    suggestion="Provide QML that declares at least one object or import.",
                    changed_in_version=None,
                    source=None,
                )
            )
        else:
            refs = _drop_local_refs(_collect_api_refs(parsed), filename)
            for ref in refs:
                issue = _symbol_issue(ref, resolved_from, resolved_to)
                if issue is not None:
                    issues.append(issue)
                    if issue["classification"] in ("definite", "likely"):
                        flagged_terms.add(ref["type_name"])
                        if ref["member"]:
                            flagged_terms.add(ref["member"])
            issues = _filter_subsumed(issues)
            issues.extend(_import_diff(parsed, resolved_from, resolved_to))
            for ref in refs:
                for term in (ref["type_name"],) + ((ref["member"],) if ref["member"] else ()):
                    terms.add(term)
                    term_location.setdefault(
                        term,
                        {"line": ref["line"], "column": ref["col"]}
                        if ref["line"] is not None
                        else None,
                    )
    else:
        if api is not None:
            api_ref = _parse_api_ref(api)
            ref = _ApiRef(
                type_name=api_ref["type_name"],
                member=api_ref["member"],
                namespace_hint=api_ref["namespace_hint"],
                line=None,
                col=None,
            )
        else:
            ref = _ApiRef(
                type_name=type or "",
                member=None,
                namespace_hint=None,
                line=None,
                col=None,
            )
        issue = _symbol_issue(ref, resolved_from, resolved_to)
        if issue is not None:
            issues.append(issue)
        terms = {ref["type_name"]} | ({ref["member"]} if ref["member"] else set())
        term_location = {}

    if parsed is not None and parsed.malformed:
        verdict = "uncertain"
    else:
        issues.extend(
            _behavioral_scan(terms, flagged_terms, resolved_from, resolved_to, term_location)
        )
        verdict = _verdict(issues)

    counts = {"definite": 0, "likely": 0, "manual_review": 0}
    for issue in issues:
        counts[issue["classification"]] += 1
        if filename:
            issue["file"] = filename

    issues.sort(
        key=lambda issue: (
            _SEVERITY_ORDER.get(issue["severity"], 3),
            issue["line"] or 10**9,
        )
    )

    return {
        "from_version": resolved_from,
        "to_version": resolved_to,
        "summary": {"verdict": verdict, "counts": counts},
        "issues": issues,
        "migration_plan": _migration_plan(issues, resolved_from, resolved_to),
        "note": (
            "Analysis is grounded in the published docs and changelog; it "
            "recommends migrations, it does not rewrite code. Items marked "
            "manual_review need a human check before applying."
        ),
    }
