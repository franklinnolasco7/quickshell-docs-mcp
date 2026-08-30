"""Tests for the performance profiling tools: bounded /proc sampling and
static component/binding/timer/object-tree/diagnose analyses. Offline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import quickshell_mcp.server as srv
from quickshell_mcp.sources import perf_profile as pp
from quickshell_mcp.sources import runtime_session as rs
from quickshell_mcp.sources.runtime_profile import _RuntimeProfile

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_QS = FIXTURES / "fake_qs.sh"


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _clear_sessions():
    rs._SESSION_REGISTRY.clear()
    yield
    rs._SESSION_REGISTRY.clear()


@pytest.fixture
def fake_qs(monkeypatch):
    monkeypatch.setattr(rs, "_qs_binary", lambda: str(FAKE_QS))


@pytest.fixture
def session(fake_qs, tmp_path) -> rs._RuntimeSession:
    (tmp_path / "shell.qml").write_text("import Quickshell\nPanelWindow {}\n", encoding="utf-8")
    s = rs._start_session(_RuntimeProfile(project_root=str(tmp_path)))
    yield s
    rs._stop_session(s)


# ---------------------------------------------------------------------------
# Runtime profile (bounded sampling)
# ---------------------------------------------------------------------------


def test_profile_running_session(session):
    result = pp._profile(session.session_id, seconds=0.5)
    assert result["session_id"] == session.session_id
    assert "cpu_percent" in result
    assert "avg_rss_kb" in result
    assert "methodology" in result
    assert "limitations" in result


def test_profile_unknown_session():
    with pytest.raises(ValueError, match="Unknown runtime session"):
        pp._profile("nope")


def test_profile_proc_unreadable(session, monkeypatch):
    monkeypatch.setattr(pp, "_proc_stat", lambda pid: None)
    result = pp._profile(session.session_id, seconds=0.1)
    assert "/proc" in result["note"]


# ---------------------------------------------------------------------------
# Static analyses
# ---------------------------------------------------------------------------


def test_profile_component(tmp_path):
    _write(
        tmp_path / "main.qml",
        "import QtQuick\nItem {\n  Timer { interval: 30 }\n  NumberAnimation {}\n"
        "  width: parent.width\n}\n",
    )
    result = pp._profile_component(str(tmp_path))
    obs = result["observations"]
    assert obs["timer_objects"] >= 1
    assert obs["animation_objects"] >= 1
    assert obs["layout_bindings"] >= 1


def test_profile_bindings(tmp_path):
    _write(
        tmp_path / "main.qml",
        "import QtQuick\nItem {\n  width: parent.width\n  height: parent.height\n}\n",
    )
    result = pp._profile_bindings(str(tmp_path))
    assert result["chain_count"] >= 1
    assert result["binding_chains"]


def test_profile_timers_suspicious(tmp_path):
    _write(
        tmp_path / "main.qml",
        "import QtQuick\n"
        "Timer { interval: 20 }\n"
        "Timer { repeat: false }\n"
        "Timer { interval: 5000 }\n",
    )
    result = pp._profile_timers(str(tmp_path))
    assert result["suspicious_timers"]
    assert result["suspicious_timers"][0]["why"]


def test_profile_object_tree(tmp_path):
    _write(
        tmp_path / "main.qml",
        "import QtQuick\nItem {\n  RowLayout {\n    Text {}\n    Text {}\n  }\n}\n",
    )
    result = pp._profile_object_tree(str(tmp_path))
    assert result["object_count"] >= 1
    assert "repeated_patterns" in result


def test_performance_diagnose_empty_project(tmp_path):
    result = pp._performance_diagnose(str(tmp_path))
    assert result["hypotheses"] == []
    assert result["note"]


# ---------------------------------------------------------------------------
# Tool wrappers
# ---------------------------------------------------------------------------


def test_profile_tool_requires_session():
    with pytest.raises(ValueError, match="Unknown runtime session"):
        srv.quickshell_profile("nope")


def test_profile_static_tools_invalid_path():
    with pytest.raises(ValueError, match="does not exist"):
        srv.quickshell_profile_component("/nonexistent/12345")
    with pytest.raises(ValueError, match="does not exist"):
        srv.quickshell_profile_bindings("/nonexistent/12345")
    with pytest.raises(ValueError, match="does not exist"):
        srv.quickshell_profile_timers("/nonexistent/12345")
    with pytest.raises(ValueError, match="does not exist"):
        srv.quickshell_profile_object_tree("/nonexistent/12345")
    with pytest.raises(ValueError, match="does not exist"):
        srv.quickshell_performance_diagnose("/nonexistent/12345")
