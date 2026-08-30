"""Tests for runtime debugging: diagnose, errors, trace, binding_inspect,
and reload. Uses the fake qs shim for offline runs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import quickshell_mcp.server as srv
from quickshell_mcp.sources import runtime_debug as dbg
from quickshell_mcp.sources import runtime_session as rs
from quickshell_mcp.sources.runtime_profile import _RuntimeProfile

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_QS = FIXTURES / "fake_qs.sh"


@pytest.fixture(autouse=True)
def _clear_sessions():
    rs._SESSION_REGISTRY.clear()
    yield
    rs._SESSION_REGISTRY.clear()


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
# Error normalization
# ---------------------------------------------------------------------------


def test_normalize_error_recognizes_common():
    err = dbg._normalize_error("Cannot assign to non-existent property 'foo'")
    assert err["category"] == "undefined_property"
    assert dbg._normalize_error("module 'Foo' not found")["category"] == "import_failure"
    assert dbg._normalize_error("foo is not defined")["category"] == "js_exception"
    assert dbg._normalize_error("plain log line") is None


def test_runtime_errors_empty(session):
    result = dbg._runtime_errors(session.session_id)
    assert result["count"] == 0
    assert result["errors"] == []


def test_runtime_errors_captures_stderr(session):
    session.append_log("stderr", "foo: ReferenceError: bar is not defined")
    result = dbg._runtime_errors(session.session_id)
    assert result["count"] >= 1
    assert result["errors"][0]["original"] == "foo: ReferenceError: bar is not defined"


def test_runtime_errors_unknown_session():
    with pytest.raises(ValueError, match="Unknown runtime session"):
        dbg._runtime_errors("nope")


# ---------------------------------------------------------------------------
# Binding inspect
# ---------------------------------------------------------------------------


def test_binding_inspect_shape(session, tmp_path):
    (tmp_path / "shell.qml").write_text(
        'import Quickshell\nPanelWindow {\n    property string greeting: "hi"\n}\n',
        encoding="utf-8",
    )
    result = dbg._binding_inspect(session.session_id, "inspector", "greeting")
    assert result["property"] == "greeting"
    assert "value" in result
    assert "source_expression" in result


def test_binding_inspect_unknown_session():
    with pytest.raises(ValueError, match="Unknown runtime session"):
        dbg._binding_inspect("nope", "inspector", "greeting")


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------


def test_trace_shape(session):
    session.append_log("stdout", "clicked bumpCounter")
    result = dbg._trace(session.session_id, "bumpCounter")
    assert result["action"] == "bumpCounter"
    assert result["observed_events"]
    assert result["inferred_transitions"] == []


def test_trace_unknown_session():
    with pytest.raises(ValueError, match="Unknown runtime session"):
        dbg._trace("nope", "click")


# ---------------------------------------------------------------------------
# Diagnose
# ---------------------------------------------------------------------------


def test_diagnose_no_errors(session):
    result = dbg._diagnose(session.session_id)
    assert result["root_cause"] is None
    assert result["confidence"] == "low"
    assert result["evidence"] == []


def test_diagnose_with_errors(session):
    session.append_log("stderr", "foo: Cannot assign to non-existent property 'x'")
    session.append_log("stderr", "bar: Cannot assign to non-existent property 'y'")
    result = dbg._diagnose(session.session_id)
    assert result["root_cause"] == "undefined_property"
    assert result["confidence"] == "high"
    assert result["evidence"]


def test_diagnose_unknown_session():
    with pytest.raises(ValueError, match="Unknown runtime session"):
        dbg._diagnose("nope")


# ---------------------------------------------------------------------------
# Reload
# ---------------------------------------------------------------------------


def test_reload_preserves_profile(session):
    old_id = session.session_id
    result = dbg._reload(session.session_id)
    assert result["session_id"] != old_id
    assert result["session_id"] in rs._SESSION_REGISTRY
    assert old_id not in rs._SESSION_REGISTRY


def test_reload_unknown_session():
    with pytest.raises(ValueError, match="Unknown runtime session"):
        dbg._reload("nope")


# ---------------------------------------------------------------------------
# Tool wrappers
# ---------------------------------------------------------------------------


def test_debug_tool_wrappers_require_session():
    with pytest.raises(ValueError, match="Unknown runtime session"):
        srv.quickshell_runtime_diagnose("nope")
    with pytest.raises(ValueError, match="Unknown runtime session"):
        srv.quickshell_runtime_errors("nope")
    with pytest.raises(ValueError, match="Unknown runtime session"):
        srv.quickshell_trace("nope", "click")
    with pytest.raises(ValueError, match="Unknown runtime session"):
        srv.quickshell_binding_inspect("nope", "inspector", "greeting")
    with pytest.raises(ValueError, match="Unknown runtime session"):
        srv.quickshell_reload("nope")
