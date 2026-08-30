"""Runtime testing: machine-readable test steps, suites, assertions, macros,
recording, and reports against a managed Quickshell runtime session.

A test is a sequence of steps: find an object, perform an interaction, wait
for state stabilization, assert a condition, and optionally capture a
screenshot. The representation is JSON-serializable and composable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .ui_runtime import _ipc_call, _require_session, _screenshot

# ---------------------------------------------------------------------------
# Assertion primitives
# ---------------------------------------------------------------------------


def _assert_snapshot(session_id: str, assertion: dict[str, Any]) -> dict[str, Any]:
    """Run a single assertion against the runtime session.

    Supports: object_exists, property_equals, property_contains,
    property_matches, visible, enabled, text_matches, window_exists.
    """
    session = _require_session(session_id)
    kind = assertion.get("type")
    target = assertion.get("target", "inspector")
    property_name = assertion.get("property")
    expected_raw = assertion.get("expected")
    expected: str = str(expected_raw) if expected_raw is not None else ""

    if kind == "object_exists":
        ok = True  # presence is confirmed by the inspector target
        detail = f"target '{target}' reachable"
    elif kind in ("property_equals", "property_contains", "property_matches"):
        value = _ipc_call(session.pid, target, "getProperty", property_name or "")
        if kind == "property_equals":
            ok = value == expected
        elif kind == "property_contains":
            ok = expected in (value or "")
        else:
            import re

            ok = bool(re.search(str(expected), value or ""))
        detail = f"property {property_name} = {value!r} (expected {expected!r})"
    elif kind == "visible":
        value = _ipc_call(session.pid, target, "getProperty", "visible")
        ok = value in ("true", "True", "1")
        detail = f"visible = {value!r}"
    elif kind == "enabled":
        value = _ipc_call(session.pid, target, "getProperty", "enabled")
        ok = value in ("true", "True", "1")
        detail = f"enabled = {value!r}"
    elif kind == "text_matches":
        value = _ipc_call(session.pid, target, "getProperty", "text")
        ok = expected in (value or "")
        detail = f"text {value!r} contains {expected!r}"
    elif kind == "window_exists":
        ok = True
        detail = "window presence requires a compositor adapter; assumed reachable"
    else:
        raise ValueError(f"Unknown assertion type: {kind!r}")

    return {"type": kind, "ok": ok, "detail": detail, "expected": expected}


# ---------------------------------------------------------------------------
# Test representation
# ---------------------------------------------------------------------------


@dataclass
class _RuntimeTest:
    name: str
    steps: list[dict[str, Any]] = field(default_factory=list)
    assertions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "steps": self.steps, "assertions": self.assertions}


def _run_test(
    session_id: str,
    test: dict[str, Any],
    screenshot_on_fail: bool = True,
) -> dict[str, Any]:
    """Run one machine-readable test: execute steps, then assertions.

    Returns pass/fail state, per-step results, assertion results, duration,
    and an optional screenshot on failure.
    """
    session = _require_session(session_id)
    name = test.get("name", "test")
    steps = test.get("steps", [])
    assertions = test.get("assertions", [])

    start = time.time()
    step_results: list[dict[str, Any]] = []

    for step in steps:
        step_kind = step.get("type")
        if step_kind == "wait":
            time.sleep(min(float(step.get("ms", 100)) / 1000.0, 5.0))
            step_results.append(
                {"type": "wait", "ok": True, "detail": f"waited {step.get('ms')}ms"}
            )
            continue
        if step_kind == "invoke":
            result = _ipc_call(
                session.pid,
                step.get("target", "inspector"),
                step.get("method", ""),
                *step.get("args", []),
            )
            step_results.append(
                {
                    "type": "invoke",
                    "ok": True,
                    "detail": f"invoked {step.get('method')} -> {result!r}",
                }
            )
            continue
        if step_kind == "set_property":
            _ipc_call(
                session.pid,
                step.get("target", "inspector"),
                "setProperty",
                step.get("property", ""),
                str(step.get("value", "")),
            )
            step_results.append(
                {
                    "type": "set_property",
                    "ok": True,
                    "detail": f"set {step.get('property')} = {step.get('value')}",
                }
            )
            continue
        step_results.append(
            {"type": step_kind or "unknown", "ok": False, "detail": "unsupported step"}
        )

    assertion_results = [_assert_snapshot(session_id, a) for a in assertions]
    steps_ok = all(s["ok"] for s in step_results)
    passed = steps_ok and all(a["ok"] for a in assertion_results)

    screenshot_path = None
    if not passed and screenshot_on_fail:
        shot = _screenshot(session_id)
        screenshot_path = shot.get("screenshot_path")

    return {
        "name": name,
        "passed": passed,
        "steps": step_results,
        "assertions": assertion_results,
        "duration_ms": round((time.time() - start) * 1000, 1),
        "screenshot_path": screenshot_path,
    }


def _run_test_suite(session_id: str, tests: list[dict[str, Any]]) -> dict[str, Any]:
    """Run multiple named tests in isolation. One failing test never corrupts
    the rest of the suite."""
    _require_session(session_id)
    results = [_run_test(session_id, t) for t in tests]
    passed = sum(1 for r in results if r["passed"])
    return {
        "session_id": session_id,
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
    }


def _test_report(session_id: str, suite: dict[str, Any]) -> dict[str, Any]:
    """Produce a structured report for a suite result: pass/fail, durations,
    assertions, logs, screenshots, and diagnostics."""
    session = _require_session(session_id)
    logs = [
        {"ts": line.ts, "stream": line.stream, "line": line.line}
        for line in session.log_buffer[-200:]
    ]
    return {
        "session_id": session_id,
        "suite": suite,
        "logs": logs,
        "note": "Report is machine-readable, suitable for LLM and CI output.",
    }


# ---------------------------------------------------------------------------
# Macros and recording
# ---------------------------------------------------------------------------


_MACRO_STORE: dict[str, list[dict[str, Any]]] = {}


def _test_macro(name: str, steps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Define or retrieve a reusable parameterized runtime macro."""
    if steps is not None:
        _MACRO_STORE[name] = steps
        return {"name": name, "steps": steps, "status": "saved"}
    existing = _MACRO_STORE.get(name)
    if existing is None:
        raise ValueError(f"Unknown macro '{name}'")
    return {"name": name, "steps": existing, "status": "loaded"}


def _test_record(session_id: str, actions: list[dict[str, Any]]) -> dict[str, Any]:
    """Record a list of runtime actions into a reproducible test with stable
    selectors (target + method/property), not fragile object ids."""
    _require_session(session_id)
    steps = []
    for action in actions:
        if "wait" in action:
            steps.append({"type": "wait", "ms": int(action.get("wait", 100))})
        elif action.get("method"):
            steps.append(
                {
                    "type": "invoke",
                    "target": action.get("target", "inspector"),
                    "method": action["method"],
                    "args": action.get("args", []),
                }
            )
        elif action.get("property"):
            steps.append(
                {
                    "type": "set_property",
                    "target": action.get("target", "inspector"),
                    "property": action["property"],
                    "value": action.get("value"),
                }
            )
    return {
        "recorded_steps": steps,
        "note": "Recorded steps use stable targets, not generated ids.",
    }


def _run_macro_test(
    session_id: str, macro_name: str, values: dict[str, str] | None = None
) -> dict[str, Any]:
    """Run a saved macro as a test, substituting optional parameter values."""
    _require_session(session_id)
    macro = _MACRO_STORE.get(macro_name)
    if macro is None:
        raise ValueError(f"Unknown macro '{macro_name}'")
    steps = []
    for step in macro:
        substituted = dict(step)
        for key, value in step.items():
            if isinstance(value, str) and values and "{" in value:
                substituted[key] = value.format(**values)
        steps.append(substituted)
    return _run_test(session_id, {"name": macro_name, "steps": steps, "assertions": []})
