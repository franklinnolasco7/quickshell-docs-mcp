"""Tests for the runtime session manager: profiles, session lifecycle, status,
logs, and ping. Uses a fake ``qs`` shim so no real Quickshell process is
launched; the tests exercise the manager logic offline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import quickshell_mcp.server as srv
from quickshell_mcp.sources import runtime_session as rs
from quickshell_mcp.sources.runtime_profile import _RuntimeProfile

FIXTURES = Path(__file__).parent / "fixtures"
FAKE_QS = FIXTURES / "fake_qs.sh"
RUNTIME_SHELL = FIXTURES / "runtime-shell"


@pytest.fixture(autouse=True)
def _clear_sessions():
    rs._SESSION_REGISTRY.clear()
    yield
    rs._SESSION_REGISTRY.clear()


@pytest.fixture
def fake_qs(monkeypatch):
    monkeypatch.setattr(rs, "_qs_binary", lambda: str(FAKE_QS))


def _profile(tmp_path) -> _RuntimeProfile:
    shell = _write_shell(tmp_path)
    return _RuntimeProfile(project_root=str(tmp_path), entrypoint=str(shell))


def _write_shell(tmp_path: Path) -> Path:
    main = tmp_path / "shell.qml"
    main.write_text("import Quickshell\nPanelWindow { width: 100 }\n", encoding="utf-8")
    return main


# ---------------------------------------------------------------------------
# RuntimeProfile
# ---------------------------------------------------------------------------


def test_profile_resolves_entrypoint(tmp_path):
    shell = _write_shell(tmp_path)
    profile = _RuntimeProfile(project_root=str(tmp_path))
    assert profile.resolved_entrypoint() == str(shell.resolve())


def test_profile_entrypoint_explicit(tmp_path):
    shell = _write_shell(tmp_path)
    profile = _RuntimeProfile(project_root=str(tmp_path), entrypoint=str(shell))
    assert profile.resolved_entrypoint() == str(shell.resolve())


def test_profile_missing_entrypoint_raises(tmp_path):
    profile = _RuntimeProfile(project_root=str(tmp_path))
    with pytest.raises(ValueError, match="No entrypoint"):
        profile.resolved_entrypoint()


def test_profile_isolated_environment_sets_xdg(tmp_path):
    _write_shell(tmp_path)
    profile = _RuntimeProfile(project_root=str(tmp_path), environment={"FOO": "bar"})
    env = profile.isolated_environment("abc123")
    assert env["FOO"] == "bar"
    assert "qs-mcp-abc123" in env["XDG_CONFIG_HOME"]
    assert env["QUICKSHELL_INSTANCE_ID"] == "abc123"


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


def test_start_session_running(fake_qs, tmp_path):
    session = rs._start_session(_profile(tmp_path))
    assert session.status == rs.STATUS_RUNNING
    assert session.pid is not None
    assert session.session_id
    assert session.session_id in rs._SESSION_REGISTRY
    # Clean up so we don't leak a process.
    rs._stop_session(session)


def test_start_session_missing_binary(tmp_path, monkeypatch):
    monkeypatch.setattr(rs, "_qs_binary", lambda: _raise_missing())
    session = rs._start_session(_profile(tmp_path))
    assert session.status == rs.STATUS_ERROR


def _raise_missing() -> str:
    raise FileNotFoundError("no qs")


def test_start_session_invalid_entrypoint(fake_qs, tmp_path):
    profile = _RuntimeProfile(project_root=str(tmp_path))
    session = rs._start_session(profile)
    assert session.status == rs.STATUS_ERROR


def test_stop_session_marks_exited(fake_qs, tmp_path):
    session = rs._start_session(_profile(tmp_path))
    assert session.status == rs.STATUS_RUNNING
    rs._stop_session(session)
    assert session.status in (rs.STATUS_EXITED, rs.STATUS_KILLED)


def test_stop_session_already_exited(fake_qs, tmp_path):
    session = rs._start_session(_profile(tmp_path))
    rs._stop_session(session)
    first = session.status
    rs._stop_session(session)  # idempotent
    assert session.status == first


def test_reset_session_allocates_new_id(fake_qs, tmp_path):
    session = rs._start_session(_profile(tmp_path))
    old_id = session.session_id
    fresh = rs._reset_session(session)
    assert fresh.session_id != old_id
    assert fresh.session_id in rs._SESSION_REGISTRY
    assert old_id not in rs._SESSION_REGISTRY
    rs._stop_session(fresh)


# ---------------------------------------------------------------------------
# Status / logs / ping
# ---------------------------------------------------------------------------


def test_status_shape(fake_qs, tmp_path):
    session = rs._start_session(_profile(tmp_path))
    status = rs._status_session(session)
    assert status["session_id"] == session.session_id
    assert "pid" in status
    assert "status" in status
    assert status["profile"]["project_root"] == str(tmp_path)
    rs._stop_session(session)


def test_logs_append_and_filter(fake_qs, tmp_path):
    session = rs._start_session(_profile(tmp_path))
    session.append_log("stdout", "hello world")
    session.append_log("stderr", "some error")
    lines = rs._logs(session)
    assert len(lines) >= 2
    filtered = rs._logs(session, stream="stderr")
    assert all(entry["stream"] == "stderr" for entry in filtered)
    text_filtered = rs._logs(session, text="error")
    assert all("error" in entry["line"] for entry in text_filtered)
    bounded = rs._logs(session, limit=1)
    assert len(bounded) == 1
    rs._stop_session(session)


def test_ping_running(fake_qs, tmp_path):
    session = rs._start_session(_profile(tmp_path))
    result = rs._ping(session)
    assert result["status"] in ("process_running", "exited")
    rs._stop_session(session)


def test_ping_error_session(fake_qs, tmp_path, monkeypatch):
    session = rs._start_session(_profile(tmp_path))
    session.status = rs.STATUS_ERROR
    result = rs._ping(session)
    assert result["status"] == "unhealthy"


# ---------------------------------------------------------------------------
# Tool wrappers
# ---------------------------------------------------------------------------


def test_runtime_tool_wrappers_require_session():
    with pytest.raises(ValueError, match="Unknown runtime session"):
        srv.quickshell_runtime_stop("nope")
    with pytest.raises(ValueError, match="Unknown runtime session"):
        srv.quickshell_runtime_status("nope")
    with pytest.raises(ValueError, match="Unknown runtime session"):
        srv.quickshell_runtime_logs("nope")
    with pytest.raises(ValueError, match="Unknown runtime session"):
        srv.quickshell_runtime_ping("nope")


def test_runtime_start_tool_records_stats(fake_qs, tmp_path):
    _write_shell(tmp_path)
    before = dict(srv._TOOL_CALLS)
    out = srv.quickshell_runtime_start(project=str(tmp_path))
    assert out["session_id"]
    assert out["status"] == rs.STATUS_RUNNING
    assert srv._TOOL_CALLS["quickshell_runtime_start"] == (
        before.get("quickshell_runtime_start", 0) + 1
    )
    srv.quickshell_runtime_stop(out["session_id"])
