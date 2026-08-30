"""Tests for visual QA tools: visual_check, visual_diff, screenshot_region,
and ui_snapshot. Screenshot-dependent tools report "unavailable" when the
required binaries are missing; offline by default.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import quickshell_mcp.server as srv
from quickshell_mcp.sources import runtime_session as rs
from quickshell_mcp.sources import runtime_visual as rv
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
# Visual check
# ---------------------------------------------------------------------------


def test_visual_check_no_screenshot(session, monkeypatch):
    monkeypatch.setattr(rv, "_screenshot", lambda sid: {"screenshot_path": None})
    result = srv.quickshell_visual_check(session.session_id)
    assert result["observations"] == []
    assert "No screenshot" in result["note"]


def test_visual_check_with_dims(session, tmp_path, monkeypatch):
    img = tmp_path / "shot.png"
    img.write_bytes(b"fake-png")
    monkeypatch.setattr(rv, "_dimensions", lambda p: (1920, 1080))
    result = srv.quickshell_visual_check(session.session_id, screenshot_path=str(img))
    assert result["observations"]
    assert any(o["kind"] == "dimensions" for o in result["observations"])


def test_visual_check_unknown_session():
    with pytest.raises(ValueError, match="Unknown runtime session"):
        srv.quickshell_visual_check("nope")


# ---------------------------------------------------------------------------
# Visual diff
# ---------------------------------------------------------------------------


def test_visual_diff_unavailable(monkeypatch):
    monkeypatch.setattr(
        rv,
        "_screenshot_diff",
        lambda *a, **k: {
            "differs": None,
            "diff_path": None,
            "metric": None,
            "note": "Screenshot diff requires ImageMagick compare; unavailable here.",
        },
    )
    result = srv.quickshell_visual_diff("a.png", "b.png")
    assert result["differs"] is None
    assert result["threshold"] == 0


def test_visual_diff_threshold(monkeypatch):
    monkeypatch.setattr(
        rv,
        "_screenshot_diff",
        lambda *a, **k: {
            "differs": True,
            "diff_path": "/tmp/d.png",
            "metric": 5.0,
            "note": None,
        },
    )
    result = srv.quickshell_visual_diff("a.png", "b.png", threshold=10)
    assert result["differs"] is False
    assert result["metric"] == 5.0
    assert result["threshold"] == 10


# ---------------------------------------------------------------------------
# Screenshot region
# ---------------------------------------------------------------------------


def test_screenshot_region_unavailable(session, monkeypatch):
    monkeypatch.setattr(rv, "_screenshot", lambda sid: {"screenshot_path": None})
    result = srv.quickshell_screenshot_region(session.session_id, object_name="bar")
    assert result["screenshot_path"] is None
    assert "grim" in result["note"]


def test_screenshot_region_unknown_session():
    with pytest.raises(ValueError, match="Unknown runtime session"):
        srv.quickshell_screenshot_region("nope")


# ---------------------------------------------------------------------------
# UI snapshot
# ---------------------------------------------------------------------------


def test_ui_snapshot_shape(session, monkeypatch):
    monkeypatch.setattr(rv, "_screenshot", lambda sid: {"screenshot_path": None})
    monkeypatch.setattr(rv, "_ui_tree", lambda sid: {"tree": None})
    result = srv.quickshell_ui_snapshot(session.session_id)
    assert result["session_id"] == session.session_id
    assert "timestamp" in result
    assert "screenshot_path" in result


def test_ui_snapshot_unknown_session():
    with pytest.raises(ValueError, match="Unknown runtime session"):
        srv.quickshell_ui_snapshot("nope")
