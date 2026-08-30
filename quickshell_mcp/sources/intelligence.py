"""Intelligence: root-cause correlation and inspect-before-modify task plans.

Root-cause correlation (13.4) combines static explanation with live runtime
evidence and separates inferred hypotheses from observed evidence — an
inferred cause is never presented as fact. The task planner (13.5) inspects a
project before proposing the minimal tool set to accomplish a request, and
stops when verification would confirm the change.
"""

from __future__ import annotations

from typing import Any, cast

from ..versions import _resolve_version
from .assistant import _classify_intent
from .explain_error import _explain_error
from .project import _build_project_context
from .runtime_debug import _diagnose

# ---------------------------------------------------------------------------
# Root-cause correlation (13.4)
# ---------------------------------------------------------------------------


def _root_cause(
    error: str | None = None,
    code: str | None = None,
    session_id: str | None = None,
    project: str | None = None,
    version: str = "latest",
    filename: str | None = None,
) -> dict[str, Any]:
    """Correlate evidence into a root cause, separating inferred from
    observed. Never fabricates a cause when evidence is insufficient."""
    resolved = _resolve_version(version)

    # Static evidence (docs-grounded explanation of the error/code).
    static: dict[str, Any] | None = None
    if error or code:
        try:
            static = _explain_error(error or "", code=code, version=version, filename=filename)
        except ValueError as exc:
            static = {"error": str(exc)}

    # Live runtime evidence when a session is given.
    live: dict[str, Any] | None = None
    if session_id:
        try:
            live = _diagnose(session_id)
        except ValueError as exc:
            live = {"error": str(exc)}

    observed: list[str] = []
    inferred: list[str] = []
    confidence = "low"

    if live and live.get("evidence"):
        for item in live["evidence"]:
            observed.append(f"observed: {item.get('text') or item.get('category')}")
        confidence = live.get("confidence") or "low"
        if live.get("root_cause"):
            inferred.append(
                f"inferred: {live['root_cause']} (repeated pattern, confidence {confidence})"
            )

    if static and static.get("error_category"):
        inferred.append(
            f"inferred: {static['error_category']} (static doc analysis of the error/code)"
        )

    # Project context supplements live evidence when present.
    project_info: dict[str, Any] | None = None
    if project:
        try:
            ctx = _build_project_context(project)
            info = cast(
                dict[str, Any], ctx.discover({"quickshell_version", "compositor", "qml_files"})
            )
            project_info = {
                "root": str(ctx.root),
                "quickshell_version": info["quickshell_version"],
                "compositor": info["compositor"],
                "qml_files": len(info["qml_files"]),
            }
        except ValueError as exc:
            project_info = {"error": str(exc)}

    return {
        "version": resolved,
        "confidence": confidence,
        "observed": observed,
        "inferred": inferred,
        "static_analysis": static,
        "runtime_diagnosis": live,
        "project_info": project_info,
        "note": (
            "Observed evidence and inferred hypotheses are reported "
            "separately; an inference is never presented as fact."
        ),
    }


# ---------------------------------------------------------------------------
# Task planner (13.5)
# ---------------------------------------------------------------------------

# Minimal tool set per intent; every step is justified by an inspection
# performed first. Steps stop when verification would confirm the change.
_PLAN_TEMPLATES: dict[str, list[dict[str, str]]] = {
    "build": [
        {"tool": "quickshell_project_analyze", "step": "inspect the project"},
        {"tool": "quickshell_search_all", "step": "research the APIs the feature needs"},
        {"tool": "quickshell_generate_component", "step": "generate a verified component"},
        {"tool": "quickshell_validate_qml", "step": "validate the generated QML"},
    ],
    "debug": [
        {"tool": "quickshell_explain_error", "step": "explain the error from the docs"},
        {"tool": "quickshell_runtime_diagnose", "step": "correlate live runtime evidence"},
        {"tool": "quickshell_trace", "step": "trace observed vs inferred transitions"},
    ],
    "migrate": [
        {"tool": "quickshell_api_diff", "step": "summarize the API delta"},
        {"tool": "quickshell_project_migrate", "step": "run the per-file migration engine"},
    ],
    "test": [
        {"tool": "quickshell_runtime_start", "step": "start an isolated session"},
        {"tool": "quickshell_test_suite", "step": "run the machine-readable suite"},
        {"tool": "quickshell_screenshot", "step": "capture evidence on failure"},
    ],
    "optimize": [
        {"tool": "quickshell_profile", "step": "sample CPU/memory"},
        {"tool": "quickshell_performance_diagnose", "step": "correlated diagnosis"},
    ],
    "research": [
        {"tool": "quickshell_search_all", "step": "search every source"},
        {"tool": "quickshell_get_type", "step": "resolve the relevant type pages"},
    ],
}


def _task_plan(
    request: str,
    project: str | None = None,
    version: str = "latest",
) -> dict[str, Any]:
    """Produce a minimal, inspect-before-modify plan for a request.

    The plan lists the smallest tool set that accomplishes the intent, the
    reason each step runs, and a stop condition: verification. Execution is
    never implied — the plan is advisory and read-only.
    """
    intent = _classify_intent(request, code=None, error=None, from_version=None, to_version=None)
    intent_type = intent["type"]
    if intent_type == "build" and not project:
        intent_type = "research"  # without a project, building is just research

    resolved = _resolve_version(version)
    template = _PLAN_TEMPLATES.get(intent_type, _PLAN_TEMPLATES["research"])

    inspected: list[str] = []
    if project:
        try:
            ctx = _build_project_context(project)
            info = cast(
                dict[str, Any], ctx.discover({"quickshell_version", "compositor", "qml_files"})
            )
            inspected = [
                f"project has {len(info['qml_files'])} QML file(s)",
                f"Quickshell version: {info['quickshell_version'] or 'unknown'}",
                f"compositor: {info['compositor'] or 'unknown'}",
            ]
        except ValueError as exc:
            inspected = [f"project inspection failed: {exc}"]

    steps = [
        {"step": i + 1, "tool": entry["tool"], "reason": entry["step"]}
        for i, entry in enumerate(template)
    ]
    steps.append(
        {
            "step": len(steps) + 1,
            "tool": "verification",
            "reason": "stop when verification confirms the change (validate / test result)",
        }
    )

    return {
        "request": request,
        "intent": intent_type,
        "version": resolved,
        "inspected": inspected,
        "plan": steps,
        "note": (
            "Plan is inspect-before-modify and advisory: it selects the minimal "
            "tool set and stops when verification would confirm the change. "
            "Nothing is executed by planning."
        ),
    }
