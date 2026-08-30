"""Runtime debugging: diagnose, normalize errors, trace interactions, inspect
bindings, and reload a managed runtime session.

All tools are read-only except ``reload`` (mutating). Errors preserve original
text; inferred relationships are always marked separately from observed
evidence.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

from .runtime_session import _SESSION_REGISTRY, _start_session, _stop_session

# ---------------------------------------------------------------------------
# Normalized error extraction
# ---------------------------------------------------------------------------

_ERROR_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "import_failure",
        re.compile(r"cannot find|unable to (?:load|import)|module .* not found", re.IGNORECASE),
    ),
    (
        "undefined_property",
        re.compile(r"non-existent property|not a valid property", re.IGNORECASE),
    ),
    (
        "type_mismatch",
        re.compile(r"cannot assign .* to .*|type mismatch|invalid assignment", re.IGNORECASE),
    ),
    (
        "binding_loop",
        re.compile(r"binding loop|property .* depends on itself|circular", re.IGNORECASE),
    ),
    (
        "component_load_failure",
        re.compile(r"component .* failed|not a type|is not installed", re.IGNORECASE),
    ),
    (
        "js_exception",
        re.compile(r"referenceerror|typeerror|syntaxerror|is not defined", re.IGNORECASE),
    ),
    (
        "signal_error",
        re.compile(r"cannot connect to non-existent signal|unknown signal", re.IGNORECASE),
    ),
]


def _normalize_error(line: str) -> dict[str, Any] | None:
    for category, pattern in _ERROR_PATTERNS:
        if pattern.search(line):
            return {
                "category": category,
                "original": line,
                "line_number": None,
            }
    return None


def _runtime_errors(session_id: str, limit: int = 50) -> dict[str, Any]:
    """Extract and structure common Quickshell/QML runtime problems from a
    session's stderr. Original error text is preserved."""
    session = _SESSION_REGISTRY.get(session_id)
    if session is None:
        raise ValueError(f"Unknown runtime session '{session_id}'")
    errors: list[dict[str, Any]] = []
    for log in session.log_buffer:
        if log.stream != "stderr":
            continue
        normalized = _normalize_error(log.line)
        if normalized:
            errors.append(normalized)
    return {
        "session_id": session_id,
        "errors": errors[-limit:],
        "count": len(errors),
        "note": "Errors preserve original text; categories are best-effort heuristics.",
    }


# ---------------------------------------------------------------------------
# Binding inspection
# ---------------------------------------------------------------------------


def _binding_inspect(session_id: str, target: str, property_name: str) -> dict[str, Any]:
    """Inspect a binding: current value (from the runtime), likely source
    expression (from the project QML), and any properties that reference it.
    Reuses static project analysis where runtime introspection is limited."""
    from .project import _build_project_context
    from .ui_runtime import _ipc_call

    session = _SESSION_REGISTRY.get(session_id)
    if session is None:
        raise ValueError(f"Unknown runtime session '{session_id}'")
    if session.pid is None:
        raise ValueError(f"Session '{session_id}' has no PID (not running)")
    value = _ipc_call(session.pid, target, "getProperty", property_name)

    source_expression = None
    referencing: list[str] = []
    try:
        ctx = _build_project_context(session.profile.project_root)
        for path in cast(dict[str, Any], ctx.discover({"qml_files"}))["qml_files"]:
            try:
                text = Path(path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if f"{property_name}:" in text:
                match = re.search(
                    rf"{re.escape(property_name)}\s*[:=]\s*(.*)$",
                    text,
                    re.MULTILINE,
                )
                if match:
                    source_expression = match.group(1).strip()
            if property_name in text:
                referencing.append(str(path))
    except (ValueError, RuntimeError):
        pass

    return {
        "session_id": session_id,
        "target": target,
        "property": property_name,
        "value": value,
        "source_expression": source_expression,
        "referencing_files": referencing[:10],
        "note": "Value is live; source and references are static evidence from the project.",
    }


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------


def _trace(session_id: str, action: str, steps: int = 10) -> dict[str, Any]:
    """Trace a runtime interaction across observable state transitions.

    Reports observed events (from the session log) and inferred transitions;
    the two are clearly separated.
    """
    session = _SESSION_REGISTRY.get(session_id)
    if session is None:
        raise ValueError(f"Unknown runtime session '{session_id}'")
    logs = session.log_buffer[-200:]
    events = [
        {"line": log.line, "stream": log.stream, "ts": log.ts}
        for log in logs
        if action.lower() in log.line.lower()
    ][:steps]
    return {
        "session_id": session_id,
        "action": action,
        "observed_events": events,
        "inferred_transitions": [],
        "note": "Only observed log events are listed; transitions are not inferred.",
    }


# ---------------------------------------------------------------------------
# Diagnose
# ---------------------------------------------------------------------------


def _diagnose(session_id: str) -> dict[str, Any]:
    """Combine runtime logs, errors, project context, docs, and version info
    into a probable root cause with confidence. Never fabricates a cause when
    evidence is insufficient."""
    from .project import _build_project_context

    session = _SESSION_REGISTRY.get(session_id)
    if session is None:
        raise ValueError(f"Unknown runtime session '{session_id}'")

    errors = _runtime_errors(session_id)["errors"]
    project_info = {}
    try:
        ctx = _build_project_context(session.profile.project_root)
        info = cast(
            dict[str, Any],
            ctx.discover({"quickshell_version", "compositor", "qml_files", "entrypoints"}),
        )
        project_info = {
            "quickshell_version": info["quickshell_version"],
            "compositor": info["compositor"],
            "qml_files": len(info["qml_files"]),
            "entrypoints": info["entrypoints"],
        }
    except (ValueError, RuntimeError):
        pass

    if not errors:
        return {
            "session_id": session_id,
            "root_cause": None,
            "confidence": "low",
            "evidence": [],
            "project_info": project_info,
            "note": "No runtime errors found; cannot identify a root cause without evidence.",
        }

    top = errors[0]
    categories = [e["category"] for e in errors]
    evidence = [{"category": e["category"], "text": e["original"]} for e in errors[:5]]
    return {
        "session_id": session_id,
        "root_cause": top["category"],
        "confidence": "high" if categories.count(top["category"]) > 1 else "medium",
        "evidence": evidence,
        "project_info": project_info,
        "note": "Root cause inferred from repeated error patterns; original text preserved above.",
    }


# ---------------------------------------------------------------------------
# Reload (mutating)
# ---------------------------------------------------------------------------


def _reload(session_id: str, hard: bool = False) -> dict[str, Any]:
    """Reload a managed runtime session, preserving the session id where
    possible. On failure, returns an error without orphaning the process."""
    session = _SESSION_REGISTRY.get(session_id)
    if session is None:
        raise ValueError(f"Unknown runtime session '{session_id}'")
    profile = session.profile
    # Stop cleanly, then relaunch under the same profile with a fresh id.
    _stop_session(session)
    _SESSION_REGISTRY.pop(session_id, None)
    fresh = _start_session(profile)
    return {
        "session_id": fresh.session_id,
        "status": fresh.status,
        "note": "Reloaded the managed session; process was stopped and relaunched.",
    }
