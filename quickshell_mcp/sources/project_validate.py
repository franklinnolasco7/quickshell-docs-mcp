"""Project-wide validation: run the existing validation, lint, compatibility,
and migration engines across every QML file of a project.

Each tool reuses an existing engine rather than duplicating logic, and each
treats files independently so one bad file never blocks analysis of the rest.
All tools are read-only.

Diagnostics are grouped by file and severity; every finding carries a stable
code, a location where known, and a source reference.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

from .compat import _check_compatibility
from .migrate import _collect_api_refs, _migrate
from .project import _build_project_context
from .validate import _parse_structure, _tokenize, _validate

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _qml_sources(project_root: str) -> list[str]:
    ctx = _build_project_context(project_root)
    return cast(dict[str, Any], ctx.discover({"qml_files"}))["qml_files"]


def _read(path: str) -> str | None:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


# ---------------------------------------------------------------------------
# quickshell_project_validate
# ---------------------------------------------------------------------------


def _validate_project(project_root: str, version: str = "latest") -> dict[str, Any]:
    """Run the static validator across the project, grouped by file and severity."""
    ctx = _build_project_context(project_root)
    root = ctx.root

    grouped: dict[str, list[dict[str, Any]]] = {}
    totals = {"errors": 0, "warnings": 0, "infos": 0}
    failures: list[dict[str, Any]] = []

    for path_str in _qml_sources(project_root):
        source = _read(path_str)
        if source is None:
            failures.append(
                {
                    "file": str(Path(path_str).relative_to(root)),
                    "error": "unreadable file, skipped",
                }
            )
            continue
        report = _validate(source, version=version, filename=str(Path(path_str).relative_to(root)))
        diags = report.get("diagnostics") or []
        grouped[str(Path(path_str).relative_to(root))] = diags
        for diag in diags:
            severity = diag.get("severity")
            if severity in totals:
                totals[severity] += 1

    return {
        "project_root": str(root),
        "version": version,
        "summary": totals,
        "files": {name: {"diagnostics": diags} for name, diags in grouped.items()},
        "unreadable": failures,
        "note": "Per-file isolation: an unreadable file is skipped, never blocking the rest.",
    }


# ---------------------------------------------------------------------------
# quickshell_project_lint
# ---------------------------------------------------------------------------

# Extensible rule table. Each rule: code, severity, explanation, remediation,
# and a check(source, parsed) -> list[dict] of findings.
_LINT_RULES: list[dict[str, Any]] = []


def _register_lint_rule(code, severity, explanation, remediation, check) -> None:
    _LINT_RULES.append(
        {
            "code": code,
            "severity": severity,
            "explanation": explanation,
            "remediation": remediation,
            "check": check,
        }
    )


def _rule_duplicate_import(source: str, parsed) -> list[dict[str, Any]]:
    seen: dict[str, list[int]] = {}
    for imp in parsed.imports:
        seen.setdefault(imp.module, []).append(imp.line)
    findings: list[dict[str, Any]] = []
    for module, lines in seen.items():
        if len(lines) > 1:
            findings.append(
                {"api": module, "line": lines[0], "detail": f"imported on lines {lines}"}
            )
    return findings


def _rule_duplicate_object_id(source: str, parsed) -> list[dict[str, Any]]:
    ids: dict[str, list[tuple[int, str]]] = {}
    for binding in parsed.bindings:
        if binding.name != "id":
            continue
        match = re.match(r"^\"(.*)\"$", _literal_text(source, binding))
        if not match:
            continue
        ids.setdefault(match.group(1), []).append((binding.line, binding.object_type))
    findings: list[dict[str, Any]] = []
    for value, uses in ids.items():
        if len(uses) > 1:
            for line, _obj_type in uses[1:]:
                findings.append(
                    {
                        "api": value,
                        "line": line,
                        "detail": f"duplicate id '{value}' (also on line {uses[0][0]})",
                    }
                )
    return findings


def _rule_suspicious_timer(source: str, parsed) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for binding in parsed.bindings:
        if binding.object_type != "Timer" or binding.name not in ("interval", "repeat"):
            continue
        text = _literal_text(source, binding)
        value = _number(text)
        if binding.name == "interval" and value is not None and value <= 0:
            findings.append(
                {
                    "api": "interval",
                    "line": binding.line,
                    "detail": f"Timer interval of {text}ms is non-positive; it may spin",
                }
            )
        elif binding.name == "repeat" and value == 0:
            findings.append(
                {
                    "api": "repeat",
                    "line": binding.line,
                    "detail": "Timer repeat=0 fires once and stops",
                }
            )
    return findings


def _literal_text(source: str, binding) -> str:
    pattern = re.compile(rf"\b{re.escape(binding.name)}\s*[:=]\s*(\"[^\"]*\"|[^,;}}]+)")
    for line in source.splitlines():
        match = pattern.search(line)
        if match:
            return match.group(1).strip().strip(",").strip()
    return ""


def _number(text: str) -> int | None:
    try:
        return int(text)
    except ValueError:
        return None


_register_lint_rule(
    "duplicate_import",
    "warning",
    "The same module is imported more than once in one file.",
    "Remove the duplicate import statement.",
    _rule_duplicate_import,
)
_register_lint_rule(
    "duplicate_object_id",
    "error",
    "Two objects in the same file share an id.",
    "Give each object a unique id.",
    _rule_duplicate_object_id,
)
_register_lint_rule(
    "suspicious_timer",
    "warning",
    "A Timer has a non-positive interval or a repeat=0 that fires once.",
    "Check the Timer's interval and repeat configuration.",
    _rule_suspicious_timer,
)


def _lint_project(project_root: str) -> dict[str, Any]:
    """Run the extensible lint rule table across every QML file."""
    ctx = _build_project_context(project_root)
    root = ctx.root
    findings: dict[str, list[dict[str, Any]]] = {}

    for path_str in _qml_sources(project_root):
        source = _read(path_str)
        if source is None:
            continue
        parsed = _parse_structure(_tokenize(source))
        file_findings: list[dict[str, Any]] = []
        for rule in _LINT_RULES:
            for finding in rule["check"](source, parsed):
                file_findings.append(
                    {
                        "code": rule["code"],
                        "severity": rule["severity"],
                        "message": rule["explanation"],
                        "remediation": rule["remediation"],
                        **finding,
                    }
                )
        if file_findings:
            findings[str(Path(path_str).relative_to(root))] = file_findings

    return {
        "project_root": str(root),
        "rules": [{"code": r["code"], "severity": r["severity"]} for r in _LINT_RULES],
        "findings": findings,
        "note": "Lint rules are conservative and evidence-based; no style opinions.",
    }


# ---------------------------------------------------------------------------
# quickshell_project_compatibility
# ---------------------------------------------------------------------------


def _project_compatibility(project_root: str, version: str = "latest") -> dict[str, Any]:
    """Check the whole project's API compatibility against a target version."""
    ctx = _build_project_context(project_root)
    root = ctx.root

    affected: dict[str, list[dict[str, Any]]] = {}
    summary = {"compatible": 0, "incompatible": 0, "uncertain": 0}

    for path_str in _qml_sources(project_root):
        source = _read(path_str)
        if source is None:
            continue
        parsed = _parse_structure(_tokenize(source))
        refs = _collect_api_refs(parsed)
        file_results: list[dict[str, Any]] = []
        for ref in refs:
            if ref["member"]:
                compat = _check_compatibility(
                    api=f"{ref['type_name']}.{ref['member']}", version=version
                )
                api_name = f"{ref['type_name']}.{ref['member']}"
            else:
                compat = _check_compatibility(type=ref["type_name"], version=version)
                api_name = ref["type_name"]
            verdict = compat.get("compatibility")
            if verdict in summary:
                summary[verdict] += 1
            file_results.append(
                {
                    "api": api_name,
                    "compatibility": verdict,
                    "confidence": compat.get("confidence"),
                    "explanation": compat.get("explanation"),
                    "line": ref["line"],
                    "column": ref["col"],
                    "url": _first_doc_url(compat),
                }
            )
        if file_results:
            affected[str(Path(path_str).relative_to(root))] = file_results

    return {
        "project_root": str(root),
        "version": version,
        "summary": summary,
        "affected_files": affected,
        "note": "Compatibility reflects API availability; 'uncertain' is not runtime-missing.",
    }


def _first_doc_url(compat: dict[str, Any]) -> str | None:
    for doc in compat.get("documentation") or []:
        if doc.get("url"):
            return doc["url"]
    return None


# ---------------------------------------------------------------------------
# quickshell_project_migrate
# ---------------------------------------------------------------------------


def _migrate_project(project_root: str, from_version: str, to_version: str) -> dict[str, Any]:
    """Analyze what every file must change to move between Quickshell versions.

    Never writes files: returns per-file migration issues and a
    machine-readable proposed-edit list with enough context to apply safely.
    """
    ctx = _build_project_context(project_root)
    root = ctx.root

    per_file: dict[str, dict[str, Any]] = {}
    proposed_edits: list[dict[str, Any]] = []
    issue_count = 0

    for path_str in _qml_sources(project_root):
        source = _read(path_str)
        if source is None:
            continue
        report = _migrate(
            from_version=from_version,
            to_version=to_version,
            code=source,
            filename=str(Path(path_str).relative_to(root)),
        )
        issues = report.get("issues") or []
        issue_count += len(issues)
        per_file[str(Path(path_str).relative_to(root))] = {
            "verdict": (report.get("summary") or {}).get("verdict"),
            "issues": issues,
        }
        for issue in issues:
            if issue.get("new_api"):
                proposed_edits.append(
                    {
                        "file": issue.get("file"),
                        "line": issue.get("line"),
                        "column": issue.get("column"),
                        "old_api": issue.get("old_api"),
                        "new_api": issue.get("new_api"),
                        "reason": issue.get("reason"),
                        "suggestion": issue.get("suggestion"),
                    }
                )

    return {
        "project_root": str(root),
        "from_version": from_version,
        "to_version": to_version,
        "summary": {"issue_count": issue_count, "proposed_edit_count": len(proposed_edits)},
        "files": per_file,
        "proposed_edits": proposed_edits,
        "note": "Migration analysis recommends changes; it never rewrites files.",
    }
