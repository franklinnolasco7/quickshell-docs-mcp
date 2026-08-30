"""Tests for the UI inspection tools: windows, screenshots, screenshot diff,
UI tree, find, property get/set, invoke, and eval.

Screenshot and diff tools are gated on external binaries (grim / ImageMagick
compare); when missing they return "unavailable" notes rather than failing.
UI tools require a managed session; without one they raise ValueError.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import quickshell_mcp.server as srv
from quickshell_mcp.sources import runtime_session as rs
from quickshell_mcp.sources import ui_runtime as ui
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
    monkeypatch.setattr(ui, "_qs_binary", lambda: str(FAKE_QS))


def _write_shell(tmp_path: Path) -> Path:
    main = tmp_path / "shell.qml"
    main.write_text("import Quickshell\nPanelWindow { width: 100 }\n", encoding="utf-8")
    return main


def _session(tmp_path, fake_qs) -> rs._RuntimeSession:
    _write_shell(tmp_path)
    session = rs._start_session(_RuntimeProfile(project_root=str(tmp_path)))
    return session


# ---------------------------------------------------------------------------
# Session gating
# ---------------------------------------------------------------------------


def test_ui_tools_require_session():
    for fn, args in [
        (srv.quickshell_windows, ("nope",)),
        (srv.quickshell_screenshot, ("nope",)),
        (srv.quickshell_ui_tree, ("nope",)),
        (srv.quickshell_ui_find, ("nope", "x")),
        (srv.quickshell_ui_get_property, ("nope", "inspector", "greeting")),
        (srv.quickshell_ui_set_property, ("nope", "inspector", "greeting", "hi")),
        (srv.quickshell_ui_invoke, ("nope", "inspector", "bumpCounter")),
        (srv.quickshell_ui_eval, ("nope", "1+1")),
    ]:
        with pytest.raises(ValueError, match="Unknown runtime session"):
            fn(*args)


# ---------------------------------------------------------------------------
# Screenshot / diff gating
# ---------------------------------------------------------------------------


def test_screenshot_unavailable_without_grim(fake_qs, tmp_path, monkeypatch):
    session = _session(tmp_path, fake_qs)
    monkeypatch.setattr(ui, "_grim_available", lambda: False)
    result = srv.quickshell_screenshot(session.session_id)
    assert result["screenshot_path"] is None
    assert "grim" in result["note"]
    rs._stop_session(session)


def test_rectangle_to_geometry():
    assert ui._rectangle_to_geometry({"x": 0, "y": 0, "width": 100, "height": 50}) == "100x50+0+0"
    assert ui._rectangle_to_geometry({"x": 5, "y": 3, "width": 40, "height": 20}) == "40x20+5+3"
    assert ui._rectangle_to_geometry(None) is None
    assert ui._rectangle_to_geometry({"x": 0, "y": 0}) is None  # missing w/h


def test_screenshot_blocked_without_geometry(fake_qs, tmp_path, monkeypatch):
    """Full-desktop capture is deny-by-default even when grim is available."""
    session = _session(tmp_path, fake_qs)
    monkeypatch.setattr(ui, "_grim_available", lambda: True)
    monkeypatch.setattr(ui, "_fullscreen_allowed", lambda: False)
    result = srv.quickshell_screenshot(session.session_id)
    assert result["screenshot_path"] is None
    assert "disabled by default" in result["note"]
    assert "QUICKSHELL_DOCS_MCP_ALLOW_FULLSCREEN_CAPTURE" in result["note"]
    rs._stop_session(session)


def test_capture_screenshot_requires_geometry_by_default(monkeypatch, tmp_path):
    """_capture_screenshot refuses full-desktop without the env opt-in."""
    monkeypatch.setattr(ui, "_grim_available", lambda: True)
    monkeypatch.setattr(ui, "_fullscreen_allowed", lambda: False)
    path = tmp_path / "out.png"
    result_path, note = ui._capture_screenshot(str(path), None)
    assert result_path is None
    assert "disabled by default" in note


def test_capture_screenshot_fullscreen_with_opt_in(monkeypatch, tmp_path):
    monkeypatch.setattr(ui, "_grim_available", lambda: True)
    monkeypatch.setattr(ui, "_fullscreen_allowed", lambda: True)
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        raise subprocess.TimeoutExpired("grim", 10)

    monkeypatch.setattr(ui.subprocess, "run", fake_run)
    path = tmp_path / "out.png"
    result_path, note = ui._capture_screenshot(str(path), None)
    # Full-screen capture is attempted without -g geometry.
    assert calls.get("cmd") == ["grim", str(path)]
    assert result_path is None  # capture failed after attempt
    assert note and "failed" in note


def test_capture_screenshot_bounded_geometry(monkeypatch, tmp_path):
    monkeypatch.setattr(ui, "_grim_available", lambda: True)
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        raise subprocess.TimeoutExpired("grim", 10)

    monkeypatch.setattr(ui.subprocess, "run", fake_run)
    path = tmp_path / "out.png"
    result_path, note = ui._capture_screenshot(str(path), "100x50+0+0")
    assert calls.get("cmd") == ["grim", "-g", "100x50+0+0", str(path)]
    assert result_path is None  # capture failed after attempt
    assert note and "failed" in note


def test_screenshot_object_name_unavailable(fake_qs, tmp_path, monkeypatch):
    session = _session(tmp_path, fake_qs)
    monkeypatch.setattr(ui, "_grim_available", lambda: True)
    result = srv.quickshell_screenshot(session.session_id, object_name="someRect")
    assert result["screenshot_path"] is None
    assert "compositor adapter" in result["note"]
    rs._stop_session(session)


def test_screenshot_diff_unavailable_without_compare(monkeypatch):
    monkeypatch.setattr(ui, "_compare_available", lambda: False)
    result = srv.quickshell_screenshot_diff("a.png", "b.png")
    assert result["differs"] is None
    assert "compare" in result["note"]


def test_windows_returns_empty_with_note(fake_qs, tmp_path):
    session = _session(tmp_path, fake_qs)
    result = srv.quickshell_windows(session.session_id)
    assert result["windows"] == []
    assert result["note"]
    rs._stop_session(session)


# ---------------------------------------------------------------------------
# UI tree / find
# ---------------------------------------------------------------------------


def test_ui_tree_unavailable_without_inspector(fake_qs, tmp_path):
    session = _session(tmp_path, fake_qs)
    result = srv.quickshell_ui_tree(session.session_id)
    assert result["tree"] is None
    assert "inspector" in result["note"]
    rs._stop_session(session)


def test_ui_find_unavailable_without_inspector(fake_qs, tmp_path):
    session = _session(tmp_path, fake_qs)
    result = srv.quickshell_ui_find(session.session_id, "greeting")
    assert result["results"] == []
    assert "inspector" in result["note"]
    rs._stop_session(session)


# ---------------------------------------------------------------------------
# Property get/set, invoke, eval
# ---------------------------------------------------------------------------


def test_ui_get_property_missing_binary(fake_qs, tmp_path):
    session = _session(tmp_path, fake_qs)
    # With the fake qs the ipc call fails gracefully; value is None.
    result = srv.quickshell_ui_get_property(session.session_id, "inspector", "greeting")
    assert result["target"] == "inspector"
    assert result["property"] == "greeting"
    rs._stop_session(session)


def test_ui_set_property_shape(fake_qs, tmp_path):
    session = _session(tmp_path, fake_qs)
    result = srv.quickshell_ui_set_property(session.session_id, "inspector", "greeting", "bonjour")
    assert result["property"] == "greeting"
    assert result["new_value"] == "bonjour"
    rs._stop_session(session)


def test_ui_invoke_shape(fake_qs, tmp_path):
    session = _session(tmp_path, fake_qs)
    result = srv.quickshell_ui_invoke(session.session_id, "inspector", "bumpCounter")
    assert result["method"] == "bumpCounter"
    assert result["arguments"] == []
    rs._stop_session(session)


def test_ui_eval_high_risk_note(fake_qs, tmp_path):
    session = _session(tmp_path, fake_qs)
    result = srv.quickshell_ui_eval(session.session_id, "1 + 1")
    assert result["code"] == "1 + 1"
    assert "High-risk" in result["note"]
    rs._stop_session(session)


# ---------------------------------------------------------------------------
# Screenshot with real grim (skip if unavailable)
# ---------------------------------------------------------------------------


def test_screenshot_with_grim_available(fake_qs, tmp_path, monkeypatch):
    if not ui._grim_available():
        pytest.skip("grim not installed")
    session = _session(tmp_path, fake_qs)
    result = srv.quickshell_screenshot(session.session_id)
    rs._stop_session(session)
    # grim may still fail in a headless test env; just ensure a path or a note.
    assert "screenshot_path" in result
