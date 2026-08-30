"""Tests for the runtime testing capability: test steps, suites, assertions,
macros, recording, and reports. Uses the fake qs shim for offline runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import quickshell_mcp.server as srv
from quickshell_mcp.sources import runtime_session as rs
from quickshell_mcp.sources import runtime_test as rt
from quickshell_mcp.sources.runtime_profile import _RuntimeProfile

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_QS = FIXTURES / "fake_qs.sh"


@pytest.fixture(autouse=True)
def _clear_state():
    rs._SESSION_REGISTRY.clear()
    rt._MACRO_STORE.clear()
    yield
    rs._SESSION_REGISTRY.clear()
    rt._MACRO_STORE.clear()


@pytest.fixture
def fake_qs(monkeypatch):
    from quickshell_mcp.sources import ui_runtime as ui

    monkeypatch.setattr(rs, "_qs_binary", lambda: str(FAKE_QS))
    monkeypatch.setattr(ui, "_qs_binary", lambda: str(FAKE_QS))


@pytest.fixture
def session(fake_qs, tmp_path) -> rs._RuntimeSession:
    (tmp_path / "shell.qml").write_text("import Quickshell\nPanelWindow {}\n", encoding="utf-8")
    s = rs._start_session(_RuntimeProfile(project_root=str(tmp_path)))
    yield s
    rs._stop_session(s)


# ---------------------------------------------------------------------------
# Assertions
# ---------------------------------------------------------------------------


def test_assert_unknown_type_raises(session):
    with pytest.raises(ValueError, match="Unknown assertion"):
        rt._assert_snapshot(session.session_id, {"type": "nonsense"})


def test_assert_object_exists(session):
    result = rt._assert_snapshot(
        session.session_id, {"type": "object_exists", "target": "inspector"}
    )
    assert result["ok"] is True


def test_assert_property_equals_missing_target(session):
    result = rt._assert_snapshot(
        session.session_id,
        {
            "type": "property_equals",
            "target": "inspector",
            "property": "greeting",
            "expected": "x",
        },
    )
    assert result["ok"] is False
    assert "greeting" in result["detail"]


# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------


def test_run_test_passing(session):
    test = {"name": "noop", "steps": [{"type": "wait", "ms": 10}], "assertions": []}
    result = rt._run_test(session.session_id, test)
    assert result["passed"] is True
    assert result["steps"] and result["steps"][0]["ok"]


def test_run_test_with_invoke_and_wait(session):
    test = {
        "name": "bump",
        "steps": [
            {"type": "wait", "ms": 10},
            {"type": "invoke", "target": "inspector", "method": "bumpCounter"},
        ],
        "assertions": [{"type": "object_exists"}],
    }
    result = rt._run_test(session.session_id, test)
    assert result["passed"] is True
    kinds = {s["type"] for s in result["steps"]}
    assert kinds == {"wait", "invoke"}


def test_run_test_unsupported_step_fails(session):
    test = {"name": "bad", "steps": [{"type": "bogus"}], "assertions": []}
    result = rt._run_test(session.session_id, test)
    assert result["passed"] is False
    assert any(not s["ok"] for s in result["steps"])


def test_run_test_failing_assertion_captures_screenshot(session, monkeypatch):
    monkeypatch.setattr(rt, "_screenshot", lambda sid: {"screenshot_path": "/tmp/x.png"})
    test = {
        "name": "fail",
        "steps": [],
        "assertions": [
            {
                "type": "property_equals",
                "target": "inspector",
                "property": "greeting",
                "expected": "never",
            }
        ],
    }
    result = rt._run_test(session.session_id, test)
    assert result["passed"] is False
    assert result["screenshot_path"] == "/tmp/x.png"


# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------


def test_run_test_suite(session):
    tests = [
        {"name": "a", "steps": [{"type": "wait", "ms": 10}], "assertions": []},
        {"name": "b", "steps": [], "assertions": [{"type": "object_exists"}]},
    ]
    result = rt._run_test_suite(session.session_id, tests)
    assert result["total"] == 2
    assert result["passed"] == 2
    assert result["failed"] == 0
    assert len(result["results"]) == 2


# ---------------------------------------------------------------------------
# Macros
# ---------------------------------------------------------------------------


def test_macro_save_and_load():
    result = rt._test_macro("greet", steps=[{"type": "wait", "ms": 50}])
    assert result["status"] == "saved"
    loaded = rt._test_macro("greet")
    assert loaded["status"] == "loaded"
    assert loaded["steps"] == [{"type": "wait", "ms": 50}]


def test_macro_unknown_raises():
    with pytest.raises(ValueError, match="Unknown macro"):
        rt._test_macro("nope")


def test_run_macro_test(session):
    rt._test_macro("greet", steps=[{"type": "wait", "ms": 10}])
    result = rt._run_macro_test(session.session_id, "greet")
    assert result["passed"] is True


def test_run_macro_test_substitution(session):
    rt._test_macro(
        "log",
        steps=[
            {
                "type": "set_property",
                "property": "greeting",
                "value": "{name}",
            }
        ],
    )
    result = rt._run_macro_test(session.session_id, "log", values={"name": "world"})
    assert result["passed"] is True


# ---------------------------------------------------------------------------
# Recording
# ---------------------------------------------------------------------------


def test_record_actions(session):
    actions = [
        {"target": "inspector", "method": "bumpCounter"},
        {"wait": 100},
        {"target": "inspector", "property": "greeting", "value": "hi"},
    ]
    result = rt._test_record(session.session_id, actions)
    kinds = {s["type"] for s in result["recorded_steps"]}
    assert kinds == {"invoke", "wait", "set_property"}
    assert "stable targets" in result["note"]


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def test_test_report(session):
    suite = rt._run_test_suite(
        session.session_id,
        [
            {
                "name": "a",
                "steps": [{"type": "wait", "ms": 10}],
                "assertions": [],
            }
        ],
    )
    report = rt._test_report(session.session_id, suite)
    assert report["suite"]["total"] == 1
    assert "logs" in report
    assert "note" in report


# ---------------------------------------------------------------------------
# Tool wrappers
# ---------------------------------------------------------------------------


def test_test_tool_wrappers_require_session():
    with pytest.raises(ValueError, match="Unknown runtime session"):
        srv.quickshell_test("nope", {"name": "x", "steps": [], "assertions": []})
    with pytest.raises(ValueError, match="Unknown runtime session"):
        srv.quickshell_test_suite("nope", [])
    with pytest.raises(ValueError, match="Unknown runtime session"):
        srv.quickshell_assert("nope", {"type": "object_exists"})
    with pytest.raises(ValueError, match="Unknown runtime session"):
        srv.quickshell_test_record("nope", [])
    with pytest.raises(ValueError, match="Unknown runtime session"):
        srv.quickshell_test_report("nope", {})
