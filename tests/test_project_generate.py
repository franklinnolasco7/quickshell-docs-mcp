"""Tests for B3 tools: project-aware generation, service/panel generation,
refactor, apply_patch, and style_match.

Network-backed generation tests reuse the generate fixtures; refactor,
apply_patch, and style_match are pure-local filesystem tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import quickshell_mcp.server as srv
from quickshell_mcp.sources.refactor import _apply_patch, _refactor
from quickshell_mcp.sources.style_match import _style_match

FIXTURES = Path(__file__).parent / "fixtures" / "projects"
SMALL = FIXTURES / "small"


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Project-aware generate_component
# ---------------------------------------------------------------------------


def test_generate_component_project_aware(monkeypatch, docs_fixture_urls, tmp_path):
    from test_generate import _install_generate_fixtures

    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    _write(
        tmp_path / "main.qml",
        "import Quickshell 0.3\nimport Quickshell.Hyprland\nPanelWindow {}\n",
    )
    out = srv._generate_component("Create a volume OSD", project=str(tmp_path))
    assert out["component"]
    assert any("Project conventions applied" in a for a in out["assumptions"])


def test_generate_component_project_aware_no_project(monkeypatch, docs_fixture_urls):
    from test_generate import _install_generate_fixtures

    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._generate_component("Create a volume OSD")
    assert not any("Project conventions applied" in a for a in out["assumptions"])


def test_generate_component_project_aware_bad_path(monkeypatch, docs_fixture_urls):
    from test_generate import _install_generate_fixtures

    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._generate_component("Create a volume OSD", project="/nonexistent")
    # A bad project path must not sink generation.
    assert out["component"]


# ---------------------------------------------------------------------------
# Generate service
# ---------------------------------------------------------------------------


def test_generate_service(monkeypatch, docs_fixture_urls):
    from test_generate import _install_generate_fixtures

    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._generate_service("volume")
    assert out["component"]["filename"].endswith(".qml")
    assert out["service_name"].endswith("Service")
    assert "import Quickshell" in out["component"]["qml"]
    assert out["dependencies"]["imports"] == ["Quickshell"]
    assert out["verification"]["verdict"] == "verified"
    assert out["validation"]["summary"]["errors"] == 0


# ---------------------------------------------------------------------------
# Generate panel
# ---------------------------------------------------------------------------


def test_generate_panel(monkeypatch, docs_fixture_urls):
    from test_generate import _install_generate_fixtures

    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._generate_panel("Create a top bar")
    assert out["component"]
    assert out["component"]["verified"] is True


# ---------------------------------------------------------------------------
# Refactor (read-only)
# ---------------------------------------------------------------------------


def test_refactor_proposes_edits(tmp_path):
    _write(tmp_path / "main.qml", "import QtQuick\nItem { id: oldName }\nText { text: oldName }\n")
    result = _refactor(str(tmp_path), "oldName", "newName")
    assert result["old"] == "oldName"
    assert result["new"] == "newName"
    assert len(result["edits"]) == 2
    assert "newName" in result["diff"]
    # Nothing written.
    assert "newName" not in (tmp_path / "main.qml").read_text()


def test_refactor_no_match(tmp_path):
    _write(tmp_path / "main.qml", "import QtQuick\nItem {}\n")
    result = _refactor(str(tmp_path), "missing", "present")
    assert result["edits"] == []
    assert result["diff"] == ""


def test_refactor_invalid_path():
    with pytest.raises(ValueError, match="does not exist"):
        _refactor("/nonexistent/12345", "a", "b")


# ---------------------------------------------------------------------------
# Apply patch (mutating)
# ---------------------------------------------------------------------------


def test_apply_patch_single_edit(tmp_path):
    _write(tmp_path / "main.qml", "import QtQuick\nItem { id: oldName }\n")
    edits = [{"file": "main.qml", "line": 2, "old": "oldName", "new": "newName"}]
    result = _apply_patch(str(tmp_path), edits)
    assert result["applied"] == 1
    assert result["changed_files"][0]["file"] == "main.qml"
    assert "newName" in (tmp_path / "main.qml").read_text()


def test_apply_patch_rejects_ambiguous_edit(tmp_path):
    _write(tmp_path / "main.qml", "Item { id: x }\nItem { id: x }\n")
    edits = [{"file": "main.qml", "old": "x", "new": "y"}]
    with pytest.raises(ValueError, match="refusing"):
        _apply_patch(str(tmp_path), edits)


def test_apply_patch_rejects_path_escape(tmp_path):
    _write(tmp_path / "main.qml", "Item {}\n")
    edits = [{"file": "../outside.qml", "old": "a", "new": "b"}]
    with pytest.raises(ValueError, match="escapes the project root"):
        _apply_patch(str(tmp_path), edits)


def test_apply_patch_rejects_missing_target(tmp_path):
    edits = [{"file": "nope.qml", "old": "a", "new": "b"}]
    with pytest.raises(ValueError, match="does not exist"):
        _apply_patch(str(tmp_path), edits)


def test_apply_patch_stale_hash_rejected(tmp_path):
    _write(tmp_path / "main.qml", "Item { id: oldName }\n")
    edits = [{"file": "main.qml", "old": "oldName", "new": "newName"}]
    with pytest.raises(ValueError, match="stale"):
        _apply_patch(str(tmp_path), edits, expected_base_hashes={"main.qml": "f" * 64})


def test_apply_patch_empty_edits(tmp_path):
    with pytest.raises(ValueError, match="No edits"):
        _apply_patch(str(tmp_path), [])


# ---------------------------------------------------------------------------
# Style match
# ---------------------------------------------------------------------------


def test_style_match_detects_colors(tmp_path):
    _write(
        tmp_path / "main.qml",
        'import QtQuick\nItem {\n    color: "#1e1e2e"\n    Rectangle { radius: 8 }\n'
        "    Text { font.pixelSize: 14 }\n    Column { spacing: 6 }\n"
        "    Behavior { NumberAnimation { duration: 150 } }\n}\n",
    )
    result = _style_match(str(tmp_path))
    findings = result["findings"]
    assert any(c["value"] == "#1e1e2e" for c in findings["colors"])
    assert any(r["value"] == "8" for r in findings["corner_radius"])
    assert any(f["value"] == "14" for f in findings["font_sizes"])
    assert any(s["value"] == "6" for s in findings["spacing"])
    assert any(d["value"] == "150" for d in findings["animation_duration_ms"])
    assert findings["animation_usage"]["files_using_animations"] >= 1


def test_style_match_empty_project(tmp_path):
    result = _style_match(str(tmp_path))
    assert result["findings"]["colors"] == []
    assert result["findings"]["animation_usage"]["status"] == "unknown"


def test_style_match_invalid_path():
    with pytest.raises(ValueError, match="does not exist"):
        _style_match("/nonexistent/12345")
