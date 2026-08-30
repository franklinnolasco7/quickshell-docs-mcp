"""Agent-level orchestration: high-level tools that compose the existing
per-source helpers into end-to-end operations.

Each tool runs an explicit, staged plan with per-step results and failure
isolation (``_step``). No domain logic is duplicated here — every stage
delegates to the existing sources/ helpers (generate, validate, migrate,
explain, diagnose, runtime, test, profile, refactor). Steps never cascade a
failure into the whole plan; every tool returns the full plan so callers can
see what ran, what failed, and why.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..versions import _resolve_version
from .explain_error import _explain_error
from .generate import _generate_component
from .knowledge2 import _api_diff
from .perf_profile import (
    _performance_diagnose,
    _profile,
    _profile_bindings,
    _profile_component,
    _profile_timers,
)
from .project_intel import _analyze_project
from .project_validate import _migrate_project as _project_migrate_files
from .refactor import _apply_patch
from .runtime_debug import _binding_inspect, _diagnose, _runtime_errors, _trace
from .runtime_profile import _RuntimeProfile
from .runtime_session import _start_session, _stop_session
from .runtime_test import _run_test_suite, _test_report
from .search_all import _search_everything
from .ui_runtime import _screenshot
from .validate import _validate

_MAX_STEPS = 12


def _step(
    trace: list[dict[str, Any]],
    errors: dict[str, str],
    tool: str,
    reason: str,
    fn: Callable[[], Any],
    expected_kind: str = "dict",
) -> Any:
    """Run one orchestration step; record outcome; isolate failures.

    A step that raises, or returns a shape the caller cannot consume, is
    recorded as ``error``/``malformed`` and the plan continues with ``None``.
    Steps are never retried, and the budget cap prevents a plan from
    scheduling more than ``_MAX_STEPS`` steps.
    """
    if len(trace) >= _MAX_STEPS:
        trace.append(
            {
                "step": len(trace) + 1,
                "tool": "step-budget",
                "reason": "refusing to schedule beyond the step budget",
                "status": "error",
                "detail": f"at most {_MAX_STEPS} orchestration steps per request",
            }
        )
        return None
    entry: dict[str, Any] = {"step": len(trace) + 1, "tool": tool, "reason": reason}
    try:
        value = fn()
    except Exception as exc:  # noqa: BLE001 - one failing step must not sink the plan
        errors[tool] = str(exc)
        entry["status"] = "error"
        entry["detail"] = str(exc)
        trace.append(entry)
        return None
    if expected_kind == "dict" and not isinstance(value, dict):
        entry["status"] = "malformed"
        entry["detail"] = f"expected dict, got {type(value).__name__}"
        trace.append(entry)
        return None
    if expected_kind == "any" and value is None:
        entry["status"] = "error"
        entry["detail"] = "step returned None"
        trace.append(entry)
        return None
    entry["status"] = "ok"
    trace.append(entry)
    return value


def _base_result(
    request: str,
    trace: list[dict[str, Any]],
    errors: dict[str, str],
    note: str,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "request": request,
        "plan": [{"step": e["step"], "tool": e["tool"], "reason": e["reason"]} for e in trace],
        "stages": trace,
        "errors": errors,
        "note": note,
        **extra,
    }


# ---------------------------------------------------------------------------
# Build feature
# ---------------------------------------------------------------------------


def _build_feature(
    description: str,
    project: str | None = None,
    version: str = "latest",
    compositor: str | None = None,
    style: str | None = None,
    context: str | None = None,
    filename: str | None = None,
    apply: bool = False,
    edits: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a feature end-to-end: analyze the project, research the APIs,
    generate a verified component, validate it, and optionally apply a
    permitted edit set. Read-only unless ``apply=True`` and ``edits`` given."""
    trace: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    resolved = _resolve_version(version)

    analysis = _step(
        trace,
        errors,
        "quickshell_project_analyze",
        "understand the project",
        lambda: _analyze_project(project) if project else None,
        "dict",
    )
    search = _step(
        trace,
        errors,
        "quickshell_search_all",
        "research APIs for the feature",
        lambda: _search_everything(description, resolved, include_content=True, limit_per_source=4),
        "dict",
    )
    generated = _step(
        trace,
        errors,
        "quickshell_generate_component",
        "generate the component",
        lambda: _generate_component(
            description,
            version=version,
            compositor=compositor,
            style=style,
            context=context,
            filename=filename,
            project=project,
        ),
        "dict",
    )

    validation: dict[str, Any] | None = None
    component: dict[str, Any] | None = None
    if generated and generated.get("component"):
        component = generated["component"]
        validation = _step(
            trace,
            errors,
            "quickshell_validate_qml",
            "validate the generated QML",
            lambda: _validate(
                component["qml"], version=resolved, filename=component.get("filename")
            ),
            "dict",
        )

    applied: dict[str, Any] | None = None
    if apply and edits:
        if project is None:
            errors["quickshell_apply_patch"] = "apply=True requires project="
        else:
            applied = _step(
                trace,
                errors,
                "quickshell_apply_patch",
                "apply the permitted edits",
                lambda: _apply_patch(project, edits),
                "dict",
            )

    return _base_result(
        description,
        trace,
        errors,
        "Build orchestrated read-only unless apply=True with an explicit edit set.",
        version=resolved,
        analysis=analysis,
        search=search,
        generated=generated,
        validation=validation,
        applied=applied,
    )


# ---------------------------------------------------------------------------
# Debug
# ---------------------------------------------------------------------------


def _debug(
    error: str | None = None,
    code: str | None = None,
    project: str | None = None,
    session_id: str | None = None,
    version: str = "latest",
    filename: str | None = None,
    target: str | None = None,
    property_name: str | None = None,
) -> dict[str, Any]:
    """Debug a failure: explain the error statically, then correlate live
    runtime evidence (errors, diagnosis, trace, binding) when a session id
    is given. Inferred causes are kept separate from observed evidence."""
    trace: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    resolved = _resolve_version(version)

    explained = _step(
        trace,
        errors,
        "quickshell_explain_error",
        "explain the error from docs",
        lambda: (
            _explain_error(error or "", code=code, version=version, filename=filename)
            if error or code
            else None
        ),
        "dict",
    )
    live_errors = _step(
        trace,
        errors,
        "quickshell_runtime_errors",
        "collect live runtime errors",
        lambda: _runtime_errors(session_id) if session_id else None,
        "dict",
    )
    diagnosis = _step(
        trace,
        errors,
        "quickshell_runtime_diagnose",
        "correlate evidence into a cause",
        lambda: _diagnose(session_id) if session_id else None,
        "dict",
    )
    live_trace = _step(
        trace,
        errors,
        "quickshell_trace",
        "trace observed vs inferred transitions",
        lambda: _trace(session_id, error or "debug") if session_id else None,
        "dict",
    )
    binding = _step(
        trace,
        errors,
        "quickshell_binding_inspect",
        "inspect a live binding",
        lambda: (
            _binding_inspect(session_id, target, property_name)
            if session_id and target and property_name
            else None
        ),
        "dict",
    )

    hypothesis: dict[str, Any] | None = None
    if diagnosis:
        hypothesis = {
            "root_cause": diagnosis.get("root_cause"),
            "confidence": diagnosis.get("confidence"),
            "observed_evidence": diagnosis.get("evidence"),
        }

    return _base_result(
        error or "debug request",
        trace,
        errors,
        "Inferred causes and observed evidence are reported separately.",
        version=resolved,
        explanation=explained,
        runtime_errors=live_errors,
        hypothesis=hypothesis,
        event_trace=live_trace,
        binding_inspection=binding,
    )


# ---------------------------------------------------------------------------
# Migrate project
# ---------------------------------------------------------------------------


def _migrate_project(
    project: str,
    from_version: str,
    to_version: str,
) -> dict[str, Any]:
    """Migrate a whole project: summarize the API delta, then run the
    per-file migration engine and report confirmed issues."""
    trace: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    resolved_from = _resolve_version(from_version)
    resolved_to = _resolve_version(to_version)

    delta = _step(
        trace,
        errors,
        "quickshell_api_diff",
        "summarize the API delta",
        lambda: _api_diff(resolved_from, resolved_to),
        "dict",
    )
    migrated = _step(
        trace,
        errors,
        "quickshell_project_migrate",
        "migrate every project file",
        lambda: _project_migrate_files(project, resolved_from, resolved_to),
        "dict",
    )

    issues: list[Any] = []
    breaking: list[Any] = []
    if migrated:
        issues = migrated.get("issues") or []
        breaking = [
            issue for issue in issues if issue.get("status") in ("breaking", "renamed", "removed")
        ]

    return _base_result(
        f"migrate {project} {resolved_from} -> {resolved_to}",
        trace,
        errors,
        "Only confirmed changelog- or doc-backed issues are reported as breaking.",
        from_version=resolved_from,
        to_version=resolved_to,
        api_delta=delta,
        migration=migrated,
        issue_count=len(issues),
        breaking_issues=breaking,
    )


# ---------------------------------------------------------------------------
# Test feature
# ---------------------------------------------------------------------------


def _test_feature(
    project: str,
    tests: list[dict[str, Any]],
    entrypoint: str | None = None,
    compositor: str | None = None,
    config_dir: str | None = None,
    environment: dict[str, str] | None = None,
    screenshot_on_fail: bool = True,
) -> dict[str, Any]:
    """Test a feature end-to-end: start an isolated session from a profile,
    run the machine-readable test suite, capture a screenshot on failure, and
    stop the session. Mutating (it launches and stops a session)."""
    trace: list[dict[str, Any]] = []
    errors: dict[str, str] = {}

    profile = _RuntimeProfile(
        project_root=project,
        entrypoint=entrypoint,
        config_dir=config_dir,
        compositor=compositor,
        environment=environment or {},
    )
    session = _step(
        trace,
        errors,
        "quickshell_runtime_start",
        "start an isolated session",
        lambda: _start_session(profile),
        "any",
    )
    if session is None:
        return _base_result(
            "test feature",
            trace,
            errors,
            "Session could not be started; tests were not run.",
            session_id=None,
            suite=None,
            report=None,
            screenshot=None,
            tests_requested=len(tests),
        )

    session_id = session.session_id
    try:
        suite = _step(
            trace,
            errors,
            "quickshell_test_suite",
            "run the machine-readable suite",
            lambda: _run_test_suite(session_id, tests),
            "dict",
        )
        screenshot: dict[str, Any] | None = None
        if screenshot_on_fail and suite and suite.get("failed"):
            screenshot = _step(
                trace,
                errors,
                "quickshell_screenshot",
                "capture evidence on failure",
                lambda: _screenshot(session_id),
                "dict",
            )
        report = None
        if suite:
            report = _step(
                trace,
                errors,
                "quickshell_test_report",
                "produce the structured report",
                lambda: _test_report(session_id, suite),
                "dict",
            )
        return _base_result(
            "test feature",
            trace,
            errors,
            "Session was stopped after the suite completed.",
            session_id=session_id,
            suite=suite,
            report=report,
            screenshot=screenshot,
            tests_requested=len(tests),
        )
    finally:

        def _stop_step() -> dict[str, Any]:
            _stop_session(session)
            return {"session_id": session_id, "status": "stopped"}

        _step(
            trace,
            errors,
            "quickshell_runtime_stop",
            "stop the session",
            _stop_step,
            "dict",
        )


# ---------------------------------------------------------------------------
# Optimize
# ---------------------------------------------------------------------------


def _optimize(
    project: str | None = None,
    session_id: str | None = None,
    seconds: float = 2.0,
) -> dict[str, Any]:
    """Optimize a project: profile a live session (when given) and run static
    component/binding/timer analysis plus a correlated diagnosis. Read-only."""
    trace: list[dict[str, Any]] = []
    errors: dict[str, str] = {}

    profile = _step(
        trace,
        errors,
        "quickshell_profile",
        "sample CPU/memory",
        lambda: _profile(session_id, seconds) if session_id else None,
        "dict",
    )
    components = _step(
        trace,
        errors,
        "quickshell_profile_component",
        "static component analysis",
        lambda: _profile_component(project) if project else None,
        "dict",
    )
    bindings = _step(
        trace,
        errors,
        "quickshell_profile_bindings",
        "binding re-evaluation chains",
        lambda: _profile_bindings(project) if project else None,
        "dict",
    )
    timers = _step(
        trace,
        errors,
        "quickshell_profile_timers",
        "suspicious timer config",
        lambda: _profile_timers(project) if project else None,
        "dict",
    )
    diagnosis = _step(
        trace,
        errors,
        "quickshell_performance_diagnose",
        "correlated diagnosis",
        lambda: _performance_diagnose(project) if project else None,
        "dict",
    )

    return _base_result(
        "optimize",
        trace,
        errors,
        "Diagnosis correlates evidence; cost is never attributed without evidence.",
        profile=profile,
        component_analysis=components,
        binding_analysis=bindings,
        timer_analysis=timers,
        diagnosis=diagnosis,
    )


# ---------------------------------------------------------------------------
# Engineer: full engineering-loop orchestration (16.1)
# ---------------------------------------------------------------------------


def _engineer(
    description: str,
    project: str | None = None,
    version: str = "latest",
    compositor: str | None = None,
    tests: list[dict[str, Any]] | None = None,
    seconds: float = 2.0,
) -> dict[str, Any]:
    """Full engineering-loop orchestration: compose the agent tools into a
    feedback cycle (build → test → debug → optimize → verify). Every stage
    is isolated; one failure never sinks the whole loop."""
    trace: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    resolved = _resolve_version(version)

    stages: dict[str, Any] = {}
    stage_order: list[str] = []

    def _run_stage(name: str, fn) -> Any:
        result = fn()
        stage_order.append(name)
        stages[name] = result
        # Flatten the stage's own orchestration into the outer trace so the
        # returned plan reflects the full engineering loop.
        sub_trace = (result or {}).get("stages") or []
        for entry in sub_trace:
            entry["stage"] = name
            trace.append(entry)
        sub_errors = (result or {}).get("errors") or {}
        errors.update(sub_errors)
        return result

    # 1. Build
    _run_stage(
        "build",
        lambda: _build_feature(
            description, project=project, version=version, compositor=compositor
        ),
    )

    # 2. Test (if tests provided)
    if tests and project:
        _run_stage(
            "test",
            lambda: _test_feature(project, tests, compositor=compositor, screenshot_on_fail=True),
        )

    # 3. Debug (if build had issues)
    build_errors = stages.get("build", {}).get("errors", {})
    if build_errors and project:
        _run_stage(
            "debug",
            lambda: _debug(
                error="; ".join(build_errors.values()),
                project=project,
                version=version,
            ),
        )

    # 4. Optimize
    _run_stage("optimize", lambda: _optimize(project=project, seconds=seconds))

    # 5. Verify (validate what was built)
    generated = (stages.get("build") or {}).get("generated") or {}
    component = generated.get("component") or {}
    validation: dict[str, Any] | None = None
    if component.get("qml"):
        validation = _validate(
            component["qml"], version=resolved, filename=component.get("filename")
        )
    stages["verify"] = validation
    stage_order.append("verify")

    return _base_result(
        description,
        trace,
        errors,
        "Engineering loop: build → test → debug → optimize → verify. "
        "Each stage runs independently; one failure never sinks the rest.",
        version=resolved,
        stage_order=stage_order,
        stages=stages,
    )
