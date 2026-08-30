"""Tests for the agent tools: build_feature, debug, migrate_project,
test_feature, optimize.

The agent tools are orchestrators over the existing per-source helpers, so
these tests monkeypatch those helpers and verify the orchestration: staged
plans, per-step results, error isolation (one failing step never sinks the
plan), and shape of the assembled result. No network or processes involved.
"""

from __future__ import annotations

import pytest

import quickshell_mcp.server as srv
from quickshell_mcp.sources import agent_tools as at


@pytest.fixture(autouse=True)
def _offline_resolve(monkeypatch):
    """Keep version resolution offline: agent tools resolve versions before
    orchestrating, and those helpers are monkeypatched per test anyway."""
    monkeypatch.setattr(at, "_resolve_version", lambda v: v or "latest")


@pytest.fixture(autouse=True)
def _clear_sessions():
    from quickshell_mcp.sources import runtime_session as rs

    rs._SESSION_REGISTRY.clear()
    yield
    rs._SESSION_REGISTRY.clear()


def _fake_session():
    class _Fake:
        session_id = "fake-session-1"

        def to_dict(self):
            return {"session_id": self.session_id, "status": "running"}

    return _Fake()


# ---------------------------------------------------------------------------
# Step helper
# ---------------------------------------------------------------------------


def test_step_ok():
    trace, errors = [], {}
    value = at._step(trace, errors, "t1", "why", lambda: {"a": 1})
    assert value == {"a": 1}
    assert trace[-1]["status"] == "ok"
    assert errors == {}


def test_step_error_isolated():
    trace, errors = [], {}

    def boom():
        raise ValueError("kaboom")

    value = at._step(trace, errors, "t1", "why", boom)
    assert value is None
    assert errors == {"t1": "kaboom"}
    assert trace[-1]["status"] == "error"
    assert trace[-1]["detail"] == "kaboom"


def test_step_malformed_shape():
    trace, errors = [], {}
    value = at._step(trace, errors, "t1", "why", lambda: "not-a-dict")
    assert value is None
    assert trace[-1]["status"] == "malformed"


def test_step_budget_capped():
    trace, errors = [], {}
    for _ in range(at._MAX_STEPS):
        at._step(trace, errors, "t", "r", lambda: {"a": 1})
    at._step(trace, errors, "overflow", "r", lambda: {"a": 1})
    assert trace[-1]["tool"] == "step-budget"
    assert trace[-1]["status"] == "error"


# ---------------------------------------------------------------------------
# Build feature
# ---------------------------------------------------------------------------


def test_build_feature_orchestrates(monkeypatch):
    generated = {
        "component": {"qml": "PanelWindow {}", "filename": "Main.qml", "verified": True},
        "verified_surface": [],
        "verification": {"verdict": "verified"},
    }
    monkeypatch.setattr(at, "_analyze_project", lambda p: {"qml_files": ["a.qml"]})
    monkeypatch.setattr(
        at, "_search_everything", lambda *a, **k: {"results": {}, "section_order": []}
    )
    monkeypatch.setattr(at, "_generate_component", lambda *a, **k: generated)
    monkeypatch.setattr(at, "_validate", lambda *a, **k: {"diagnostics": []})

    result = at._build_feature("a status bar", project="/tmp/x", version="v0.3.1")
    assert result["generated"] is generated
    assert result["validation"] == {"diagnostics": []}
    assert result["analysis"] is not None
    assert result["applied"] is None
    tools = [e["tool"] for e in result["stages"]]
    assert "quickshell_project_analyze" in tools
    assert "quickshell_generate_component" in tools
    assert "quickshell_validate_qml" in tools


def test_build_feature_applies_edits(monkeypatch):
    generated = {"component": {"qml": "X {}", "filename": "M.qml", "verified": True}}
    monkeypatch.setattr(at, "_analyze_project", lambda p: None)
    monkeypatch.setattr(
        at, "_search_everything", lambda *a, **k: {"results": {}, "section_order": []}
    )
    monkeypatch.setattr(at, "_generate_component", lambda *a, **k: generated)
    monkeypatch.setattr(at, "_validate", lambda *a, **k: {"diagnostics": []})
    monkeypatch.setattr(at, "_apply_patch", lambda *a, **k: {"changed": ["M.qml"]})

    result = at._build_feature(
        "add bar", project="/tmp/x", version="v0.3.1", apply=True, edits=[{"file": "M.qml"}]
    )
    assert result["applied"] == {"changed": ["M.qml"]}


def test_build_feature_apply_without_project_reports_error(monkeypatch):
    monkeypatch.setattr(at, "_generate_component", lambda *a, **k: {"component": {"qml": "X"}})
    monkeypatch.setattr(at, "_validate", lambda *a, **k: {"diagnostics": []})
    result = at._build_feature("add bar", version="v0.3.1", apply=True, edits=[{"file": "M.qml"}])
    assert result["applied"] is None
    assert "quickshell_apply_patch" in result["errors"]


def test_build_feature_generate_failure_isolated(monkeypatch):
    def _boom(*a, **k):
        raise ValueError("no")

    monkeypatch.setattr(at, "_generate_component", _boom)

    result = at._build_feature("bar", version="v0.3.1")
    assert result["generated"] is None
    assert "quickshell_generate_component" in result["errors"]
    # The plan still returns cleanly.
    assert result["request"] == "bar"


# ---------------------------------------------------------------------------
# Debug
# ---------------------------------------------------------------------------


def test_debug_static_only(monkeypatch):
    monkeypatch.setattr(
        at, "_explain_error", lambda *a, **k: {"category": "property", "suggestions": []}
    )
    result = at._debug(error="Cannot assign", code="X {}", version="v0.3.1")
    assert result["explanation"] == {"category": "property", "suggestions": []}
    assert result["hypothesis"] is None
    assert result["runtime_errors"] is None


def test_debug_with_session_correlates(monkeypatch):
    diagnosis = {
        "session_id": "s1",
        "root_cause": "property-error",
        "confidence": "high",
        "evidence": [{"category": "property-error", "text": "line 1"}],
    }
    monkeypatch.setattr(at, "_explain_error", lambda *a, **k: {"category": "property"})
    monkeypatch.setattr(at, "_runtime_errors", lambda sid, limit=50: {"errors": []})
    monkeypatch.setattr(at, "_diagnose", lambda sid: diagnosis)
    monkeypatch.setattr(at, "_trace", lambda *a, **k: {"events": []})
    monkeypatch.setattr(at, "_binding_inspect", lambda *a, **k: {"value": "1"})

    result = at._debug(
        error="err", session_id="s1", target="obj", property_name="w", version="v0.3.1"
    )
    assert result["hypothesis"]["root_cause"] == "property-error"
    assert result["hypothesis"]["confidence"] == "high"
    assert result["binding_inspection"] == {"value": "1"}
    assert result["event_trace"] == {"events": []}


def test_debug_no_error_but_code(monkeypatch):
    monkeypatch.setattr(at, "_explain_error", lambda *a, **k: {"category": "syntax"})
    result = at._debug(error=None, code="import Quickshell", version="v0.3.1")
    assert result["explanation"]["category"] == "syntax"


# ---------------------------------------------------------------------------
# Migrate project
# ---------------------------------------------------------------------------


def test_migrate_project(monkeypatch):
    issues = [
        {"old_api": "Quickshell.shellRoot", "new_api": "Quickshell.shellDir", "status": "renamed"}
    ]
    monkeypatch.setattr(at, "_api_diff", lambda *a, **k: {"added": [], "removed": []})
    monkeypatch.setattr(
        at, "_project_migrate_files", lambda *a, **k: {"issues": issues, "summary": {}}
    )

    result = at._migrate_project("/tmp/x", "v0.2.0", "v0.3.1")
    assert result["issue_count"] == 1
    assert result["breaking_issues"] == issues
    assert result["api_delta"] == {"added": [], "removed": []}


def test_migrate_project_failure_isolated(monkeypatch):
    monkeypatch.setattr(at, "_api_diff", lambda *a, **k: {"added": [], "removed": []})
    monkeypatch.setattr(
        at, "_project_migrate_files", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad"))
    )
    result = at._migrate_project("/tmp/x", "v0.2.0", "v0.3.1")
    assert result["migration"] is None
    assert "quickshell_project_migrate" in result["errors"]


# ---------------------------------------------------------------------------
# Test feature
# ---------------------------------------------------------------------------


def test_test_feature_runs_suite(monkeypatch):
    fake = _fake_session()
    monkeypatch.setattr(at, "_start_session", lambda profile: fake)
    monkeypatch.setattr(
        at,
        "_run_test_suite",
        lambda sid, tests: {"session_id": sid, "total": 1, "passed": 1, "failed": 0, "results": []},
    )
    monkeypatch.setattr(at, "_test_report", lambda sid, suite: {"passed": 1})
    stopped = []
    monkeypatch.setattr(at, "_stop_session", lambda session: stopped.append(session))

    result = at._test_feature("/tmp/x", [{"name": "t", "steps": [], "assertions": []}])
    assert result["suite"]["passed"] == 1
    assert result["report"] == {"passed": 1}
    assert result["screenshot"] is None
    assert stopped == [fake]  # session stopped


def test_test_feature_screenshot_on_failure(monkeypatch):
    fake = _fake_session()
    monkeypatch.setattr(at, "_start_session", lambda profile: fake)
    monkeypatch.setattr(
        at,
        "_run_test_suite",
        lambda sid, tests: {"session_id": sid, "total": 1, "passed": 0, "failed": 1, "results": []},
    )
    monkeypatch.setattr(at, "_test_report", lambda sid, suite: {"passed": 0})
    monkeypatch.setattr(at, "_screenshot", lambda sid: {"screenshot_path": "/tmp/x.png"})
    monkeypatch.setattr(at, "_stop_session", lambda session: None)

    result = at._test_feature("/tmp/x", [{"name": "t"}], screenshot_on_fail=True)
    assert result["screenshot"] == {"screenshot_path": "/tmp/x.png"}


def test_test_feature_start_failure_no_suite(monkeypatch):
    monkeypatch.setattr(
        at, "_start_session", lambda profile: (_ for _ in ()).throw(ValueError("no qs"))
    )
    result = at._test_feature("/tmp/x", [{"name": "t"}])
    assert result["suite"] is None
    assert result["session_id"] is None
    assert "quickshell_runtime_start" in result["errors"]


# ---------------------------------------------------------------------------
# Optimize
# ---------------------------------------------------------------------------


def test_optimize_static_only(monkeypatch):
    monkeypatch.setattr(at, "_profile_component", lambda p: {"components": []})
    monkeypatch.setattr(at, "_profile_bindings", lambda p: {"chains": []})
    monkeypatch.setattr(at, "_profile_timers", lambda p: {"timers": []})
    monkeypatch.setattr(at, "_performance_diagnose", lambda p: {"diagnosis": []})

    result = at._optimize(project="/tmp/x")
    assert result["profile"] is None
    assert result["component_analysis"] == {"components": []}
    assert result["diagnosis"] == {"diagnosis": []}


def test_optimize_with_session_profiles(monkeypatch):
    monkeypatch.setattr(at, "_profile", lambda sid, seconds=2.0: {"cpu": 1.0})
    monkeypatch.setattr(at, "_profile_component", lambda p: {"components": []})
    monkeypatch.setattr(at, "_profile_bindings", lambda p: {"chains": []})
    monkeypatch.setattr(at, "_profile_timers", lambda p: {"timers": []})
    monkeypatch.setattr(at, "_performance_diagnose", lambda p: {"diagnosis": []})

    result = at._optimize(project="/tmp/x", session_id="s1", seconds=1.0)
    assert result["profile"] == {"cpu": 1.0}


def test_optimize_no_args_returns_empty_plan():
    result = at._optimize()
    assert result["profile"] is None
    assert result["component_analysis"] is None
    assert result["diagnosis"] is None


# ---------------------------------------------------------------------------
# Tool wrappers record stats
# ---------------------------------------------------------------------------


def test_agent_tool_wrappers_record_stats(monkeypatch):
    monkeypatch.setattr(srv, "_build_feature", lambda *a, **k: {"request": a[0]})
    monkeypatch.setattr(srv, "_debug", lambda *a, **k: {})
    monkeypatch.setattr(srv, "_migrate_project", lambda *a, **k: {})
    monkeypatch.setattr(srv, "_test_feature", lambda *a, **k: {})
    monkeypatch.setattr(srv, "_optimize", lambda *a, **k: {})

    before = dict(srv._TOOL_CALLS)
    srv.quickshell_build_feature("bar")
    srv.quickshell_debug(error="x")
    srv.quickshell_migrate_project("/tmp/x", "v0.2.0", "v0.3.1")
    srv.quickshell_test_feature("/tmp/x", [])
    srv.quickshell_optimize(project="/tmp/x")
    for tool in (
        "quickshell_build_feature",
        "quickshell_debug",
        "quickshell_migrate_project",
        "quickshell_test_feature",
        "quickshell_optimize",
    ):
        assert srv._TOOL_CALLS[tool] == before.get(tool, 0) + 1
