"""Tests for project intelligence tools: analyze, map, find, dependencies,
config. These are local-filesystem tests using fixture project trees.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from quickshell_mcp.sources.project_intel import (
    _analyze_project,
    _config_conventions,
    _find_cycles,
    _map_project,
    _project_dependencies,
    _search_project,
)

FIXTURES = Path(__file__).parent / "fixtures" / "projects"
SMALL = FIXTURES / "small"
MEDIUM = FIXTURES / "medium"


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# _analyze_project
# ---------------------------------------------------------------------------


def test_analyze_small_project():
    result = _analyze_project(str(SMALL))
    assert result["project_root"] == str(SMALL.resolve())
    overview = result["overview"]
    assert overview["qml_files"]["status"] == "detected"
    assert overview["qml_files"]["value"]["count"] == 2
    assert overview["js_files"]["value"]["count"] == 1
    assert overview["entrypoints"]["value"] == ["main.qml"]
    assert overview["quickshell_modules"]["status"] == "detected"
    assert "Quickshell" in overview["quickshell_modules"]["value"]
    assert "Quickshell.Hyprland" in overview["quickshell_modules"]["value"]
    assert overview["compositor"]["status"] == "inferred"
    assert overview["compositor"]["value"] == ["Hyprland"]
    assert overview["qt_version"]["status"] == "inferred"
    assert overview["qt_version"]["value"] == "2.15"
    assert overview["config_paths"]["status"] == "detected"
    assert overview["conventions"]["status"] == "inferred"
    assert overview["components"]["status"] == "detected"
    assert overview["services"]["status"] == "unknown"
    assert result["note"]


def test_analyze_empty_project(tmp_path):
    result = _analyze_project(str(tmp_path))
    assert result["project_root"] == str(tmp_path.resolve())
    overview = result["overview"]
    assert overview["qml_files"]["status"] == "detected"
    assert overview["qml_files"]["value"]["count"] == 0
    assert overview["quickshell_version"]["status"] == "unknown"
    assert overview["compositor"]["status"] == "unknown"


def test_analyze_invalid_path():
    with pytest.raises(ValueError, match="does not exist"):
        _analyze_project("/nonexistent/12345")


# ---------------------------------------------------------------------------
# _map_project
# ---------------------------------------------------------------------------


def test_map_small_has_edges():
    result = _map_project(str(SMALL))
    assert result["project_root"] == str(SMALL.resolve())
    assert len(result["nodes"]) >= 3
    assert result["edges"]
    kinds = {e["kind"] for e in result["edges"]}
    assert "import" in kinds
    assert "entrypoint" in kinds


def test_map_medium_detects_cycle():
    result = _map_project(str(MEDIUM))
    cyc = result["cycles"]
    assert cyc, "expected a cycle between VolumeWidget and ClockWidget"


def test_map_empty_project(tmp_path):
    result = _map_project(str(tmp_path))
    assert result["nodes"] == []
    assert result["edges"] == []
    assert result["cycles"] == []


def test_map_invalid_path():
    with pytest.raises(ValueError, match="does not exist"):
        _map_project("/nonexistent/12345")


# ---------------------------------------------------------------------------
# _find_cycles helper
# ---------------------------------------------------------------------------


def test_find_cycles_detects_simple_cycle():
    edges = [("a", "b"), ("b", "c"), ("c", "a")]
    cycles = _find_cycles(edges)
    assert len(cycles) == 1
    assert set(cycles[0]) == {"a", "b", "c"}


def test_find_cycles_no_cycle():
    edges = [("a", "b"), ("b", "c")]
    assert _find_cycles(edges) == []


def test_find_cycles_self_loop():
    edges = [("a", "a")]
    cycles = _find_cycles(edges)
    assert len(cycles) == 1
    assert cycles[0] == ["a", "a"]


# ---------------------------------------------------------------------------
# _search_project
# ---------------------------------------------------------------------------


def test_search_project_finds_exact_match():
    result = _search_project(str(MEDIUM), "PanelWindow")
    assert result["results"]
    exact = [r for r in result["results"] if r["kind"] == "exact_text"]
    assert exact, f"expected exact text match for PanelWindow, got {result['results']}"


def test_search_project_no_match(tmp_path):
    result = _search_project(str(tmp_path), "nonexistent")
    assert result["results"] == []


def test_search_project_semantic_match():
    result = _search_project(str(MEDIUM), "volume")
    kinds = {r["kind"] for r in result["results"]}
    assert "semantic" in kinds, f"expected semantic match for volume, got {result['results']}"


# ---------------------------------------------------------------------------
# _project_dependencies
# ---------------------------------------------------------------------------


def test_dependencies_small_project():
    result = _project_dependencies(str(SMALL))
    buckets = result["dependencies"]
    assert "Quickshell" in buckets["required"]
    assert "Quickshell.Hyprland" in buckets["required"]
    assert "QtQuick" in buckets["required"]
    assert result["note"]


def test_dependencies_empty_project(tmp_path):
    result = _project_dependencies(str(tmp_path))
    for bucket in result["dependencies"].values():
        assert isinstance(bucket, list)
    assert result["dependencies"]["required"] == []


def test_dependencies_invalid_path():
    with pytest.raises(ValueError, match="does not exist"):
        _project_dependencies("/nonexistent/12345")


# ---------------------------------------------------------------------------
# _config_conventions
# ---------------------------------------------------------------------------


def test_config_small_project():
    result = _config_conventions(str(SMALL))
    assert result["entrypoints"]["status"] == "detected"
    assert result["conventions"]["file_naming"]["status"] == "detected"
    assert result["conventions"]["entrypoint_naming"]["status"] == "detected"
    assert result["environment"]["status"] == "unknown"


def test_config_empty_project(tmp_path):
    result = _config_conventions(str(tmp_path))
    assert result["entrypoints"]["status"] == "unknown"
    assert result["conventions"]["file_naming"]["status"] == "unknown"
    assert result["environment"]["status"] == "unknown"


def test_config_invalid_path():
    with pytest.raises(ValueError, match="does not exist"):
        _config_conventions("/nonexistent/12345")
