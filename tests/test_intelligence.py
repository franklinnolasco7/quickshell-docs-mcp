"""Tests for the intelligence capability: project memory, architecture
recommendations, regression detection, root-cause correlation, and task
planning.

Memory and architecture are file/registry based (tmp_path projects, the
in-memory memory registry). Root-cause and task-plan delegate to the
existing helpers, so tests monkeypatch them. No network or processes.
"""

from __future__ import annotations

import pytest

import quickshell_mcp.server as srv
from quickshell_mcp.sources import intelligence as ig
from quickshell_mcp.sources import project_memory as pm


@pytest.fixture(autouse=True)
def _offline_resolve(monkeypatch):
    monkeypatch.setattr(pm, "_resolve_version", lambda v: v or "latest")
    monkeypatch.setattr(ig, "_resolve_version", lambda v: v or "latest")


@pytest.fixture(autouse=True)
def _clear_memories():
    pm._PROJECT_MEMORIES.clear()
    yield
    pm._PROJECT_MEMORIES.clear()


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _shell(tmp_path) -> None:
    _write(tmp_path / "main.qml", "import Quickshell\nPanelWindow { width: 100 }\n")


# ---------------------------------------------------------------------------
# Project memory (13.1)
# ---------------------------------------------------------------------------


def test_memory_save_list_get(tmp_path):
    srv.quickshell_project_memory(
        str(tmp_path),
        action="save",
        key="compositor",
        content="uses Hyprland",
        evidence=["import Quickshell.Hyprland"],
        scope="env",
    )
    listed = srv.quickshell_project_memory(str(tmp_path), action="list")
    assert listed["count"] == 1
    assert listed["memories"][0]["key"] == "compositor"
    assert listed["memories"][0]["evidence_count"] == 1
    assert listed["memories"][0]["scope"] == "env"

    got = srv.quickshell_project_memory(str(tmp_path), action="get", key="compositor")
    assert got["memory"]["content"] == "uses Hyprland"
    assert got["memory"]["schema_version"] == 1


def test_memory_get_missing_raises(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        srv.quickshell_project_memory(str(tmp_path), action="get", key="nope")


def test_memory_clear(tmp_path):
    srv.quickshell_project_memory(str(tmp_path), action="save", key="a", content="1")
    result = srv.quickshell_project_memory(str(tmp_path), action="clear", key="a")
    assert result["cleared"] == "a"
    assert result["remaining"] == 0
    with pytest.raises(ValueError, match="not found"):
        srv.quickshell_project_memory(str(tmp_path), action="clear", key="a")


def test_memory_reset(tmp_path):
    srv.quickshell_project_memory(str(tmp_path), action="save", key="a", content="1")
    srv.quickshell_project_memory(str(tmp_path), action="save", key="b", content="2")
    result = srv.quickshell_project_memory(str(tmp_path), action="reset")
    assert result["cleared"] == 2
    assert srv.quickshell_project_memory(str(tmp_path), action="list")["count"] == 0


def test_memory_requires_content_for_save(tmp_path):
    with pytest.raises(ValueError, match="key"):
        srv.quickshell_project_memory(str(tmp_path), action="save", content="x")


def test_memory_scoped_by_project(tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    srv.quickshell_project_memory(str(tmp_path), action="save", key="k", content="a")
    assert srv.quickshell_project_memory(str(other), action="list")["count"] == 0


# ---------------------------------------------------------------------------
# Architecture recommendations (13.2)
# ---------------------------------------------------------------------------


def test_architecture_recommendations_shape(tmp_path):
    _shell(tmp_path)
    result = pm._architecture(str(tmp_path))
    assert result["project"]
    assert isinstance(result["recommendations"], list)
    assert isinstance(result["evidence"], list)
    assert result["note"]


def test_architecture_detects_cycle(monkeypatch, tmp_path):
    def _graph(project):
        return {
            "project_root": project,
            "nodes": ["a.qml", "b.qml"],
            "edges": [],
            "cycles": [{"files": ["a.qml", "b.qml"], "status": "confirmed"}],
            "unresolved": [],
            "note": "",
        }

    monkeypatch.setattr(pm, "_map_project", _graph)
    result = pm._architecture(str(tmp_path))
    assert any(r["concern"] == "cyclic component usage" for r in result["recommendations"])


def test_architecture_detects_unresolved(monkeypatch, tmp_path):
    def _graph(project):
        return {
            "project_root": project,
            "nodes": ["a.qml"],
            "edges": [],
            "cycles": [],
            "unresolved": [{"type": "MissingThing", "file": "a.qml"}],
            "note": "",
        }

    monkeypatch.setattr(pm, "_map_project", _graph)
    result = pm._architecture(str(tmp_path))
    assert any(r["concern"] == "unresolved references" for r in result["recommendations"])


# ---------------------------------------------------------------------------
# Regression detection (13.3)
# ---------------------------------------------------------------------------


def test_regression_validates_qml(monkeypatch, tmp_path):
    def _validate(source, version="latest", filename=None):
        return {"diagnostics": [{"severity": "error", "message": "unknown prop", "line": 2}]}

    monkeypatch.setattr(pm, "_validate", _validate)
    _write(tmp_path / "bad.qml", "import Quickshell\nPanelWindow { unknownProp: 1 }\n")
    result = pm._regression(str(tmp_path))
    assert result["regression"] is True
    assert any(i["kind"] == "validation_error" for i in result["issues"])
    assert result["validation"]["files"] == 1


def test_regression_clean_project_no_regression(monkeypatch, tmp_path):
    monkeypatch.setattr(pm, "_validate", lambda *a, **k: {"diagnostics": []})
    _shell(tmp_path)
    result = pm._regression(str(tmp_path))
    assert result["regression"] is False
    assert result["issues"] == []


def test_regression_screenshot_diff(monkeypatch, tmp_path):
    monkeypatch.setattr(pm, "_validate", lambda *a, **k: {"diagnostics": []})
    monkeypatch.setattr(
        pm, "_screenshot_diff", lambda b, a, **k: {"differs": True, "metric": 5, "note": None}
    )
    _shell(tmp_path)
    result = pm._regression(str(tmp_path), baseline_screenshot="/b.png", actual_screenshot="/a.png")
    assert any(i["kind"] == "visual_regression" for i in result["issues"])


def test_regression_missing_baseline(monkeypatch, tmp_path):
    monkeypatch.setattr(pm, "_validate", lambda *a, **k: {"diagnostics": []})
    _shell(tmp_path)
    result = pm._regression(str(tmp_path), baseline_screenshot="/b.png", actual_screenshot=None)
    assert any(i["kind"] == "missing_baseline" for i in result["issues"])


# ---------------------------------------------------------------------------
# Root-cause correlation (13.4)
# ---------------------------------------------------------------------------


def test_root_cause_static_only(monkeypatch):
    monkeypatch.setattr(
        ig, "_explain_error", lambda *a, **k: {"error_category": "property", "fix": "fix it"}
    )
    result = ig._root_cause(error="Cannot assign", version="v0.3.1")
    assert any("property" in i for i in result["inferred"])
    assert result["observed"] == []
    assert result["runtime_diagnosis"] is None


def test_root_cause_separates_inferred_observed(monkeypatch):
    live = {
        "root_cause": "property-error",
        "confidence": "high",
        "evidence": [{"category": "property-error", "text": "line 3"}],
    }
    monkeypatch.setattr(ig, "_diagnose", lambda sid: live)
    monkeypatch.setattr(ig, "_explain_error", lambda *a, **k: {"error_category": "syntax"})
    result = ig._root_cause(error="err", session_id="s1", version="v0.3.1")
    assert result["observed"] and all(o.startswith("observed:") for o in result["observed"])
    assert result["inferred"] and all(i.startswith("inferred:") for i in result["inferred"])
    assert result["confidence"] == "high"


def test_root_cause_no_evidence_low_confidence(monkeypatch):
    def _no_errors(sid):
        return {"evidence": [], "root_cause": None, "confidence": "low", "note": ""}

    monkeypatch.setattr(ig, "_diagnose", _no_errors)
    monkeypatch.setattr(ig, "_explain_error", lambda *a, **k: {})
    result = ig._root_cause(error=None, session_id="s1", version="v0.3.1")
    assert result["confidence"] == "low"


def test_root_cause_includes_project_info(tmp_path):
    _shell(tmp_path)
    result = ig._root_cause(error="err", project=str(tmp_path), version="v0.3.1")
    assert result["project_info"]["qml_files"] == 1


# ---------------------------------------------------------------------------
# Task planner (13.5)
# ---------------------------------------------------------------------------


def test_task_plan_build(tmp_path):
    _shell(tmp_path)
    result = ig._task_plan("Build a status bar", project=str(tmp_path))
    assert result["intent"] == "build"
    tools = [s["tool"] for s in result["plan"]]
    assert "quickshell_generate_component" in tools
    assert tools[-1] == "verification"
    assert result["inspected"]


def test_task_plan_never_executes():
    result = ig._task_plan("Fix this QML error")
    assert result["intent"] == "debug"
    assert "verification" in [s["tool"] for s in result["plan"]]
    assert "advisory" in result["note"]


def test_task_plan_research_without_project():
    result = ig._task_plan("What is PanelWindow?")
    assert result["intent"] == "research"


# ---------------------------------------------------------------------------
# Tool wrappers record stats
# ---------------------------------------------------------------------------


def test_intelligence_tool_wrappers_record_stats(monkeypatch, tmp_path):
    monkeypatch.setattr(srv, "_memory_save", lambda *a, **k: {})
    monkeypatch.setattr(srv, "_memory_list", lambda *a, **k: {})
    monkeypatch.setattr(srv, "_architecture", lambda *a, **k: {})
    monkeypatch.setattr(srv, "_regression", lambda *a, **k: {})
    monkeypatch.setattr(srv, "_root_cause", lambda *a, **k: {})
    monkeypatch.setattr(srv, "_task_plan", lambda *a, **k: {})

    before = dict(srv._TOOL_CALLS)
    srv.quickshell_project_memory(str(tmp_path), action="list")
    srv.quickshell_project_architecture(str(tmp_path))
    srv.quickshell_regression_detect(str(tmp_path))
    srv.quickshell_root_cause(error="x")
    srv.quickshell_task_plan("Build a bar")
    for tool in (
        "quickshell_project_memory",
        "quickshell_project_architecture",
        "quickshell_regression_detect",
        "quickshell_root_cause",
        "quickshell_task_plan",
    ):
        assert srv._TOOL_CALLS[tool] == before.get(tool, 0) + 1
