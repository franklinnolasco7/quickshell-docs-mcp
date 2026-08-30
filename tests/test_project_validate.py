"""Tests for project-wide validation tools: validate, lint, compatibility,
and migrate. These reuse the existing engines per file and are offline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import quickshell_mcp.server as srv
from quickshell_mcp.sources.project_validate import (
    _lint_project,
    _migrate_project,
    _project_compatibility,
    _validate_project,
)

FIXTURES = Path(__file__).parent / "fixtures" / "projects"
SMALL = FIXTURES / "small"
MEDIUM = FIXTURES / "medium"


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# quickshell_project_validate
# ---------------------------------------------------------------------------


def test_validate_project_small(monkeypatch, docs_fixture_urls):
    from test_migrate import _build_mapping, _install_fetch

    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = _validate_project(str(SMALL))
    assert result["project_root"] == str(SMALL.resolve())
    assert set(result["summary"]) == {"errors", "warnings", "infos"}
    assert set(result["files"]) == {"main.qml", "widgets/VolumeWidget.qml"}
    assert result["unreadable"] == []
    assert result["note"]


def test_validate_project_invalid_path():
    with pytest.raises(ValueError, match="does not exist"):
        _validate_project("/nonexistent/12345")


def test_validate_project_unreadable_is_isolated(tmp_path, monkeypatch, docs_fixture_urls):
    from test_migrate import _build_mapping, _install_fetch

    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    good = _write(tmp_path / "good.qml", "import QtQuick\nItem {}\n")
    (tmp_path / "bad.qml").write_bytes(b"\xff\xfe\x00\x00 broken")
    result = _validate_project(str(tmp_path))
    assert str(good.relative_to(tmp_path)) in result["files"]
    assert result["unreadable"], "expected the unreadable file to be reported, not fatal"


# ---------------------------------------------------------------------------
# quickshell_project_lint
# ---------------------------------------------------------------------------


def test_lint_duplicate_import(tmp_path):
    _write(
        tmp_path / "dup.qml",
        "import QtQuick\nimport QtQuick\nItem {}\n",
    )
    result = _lint_project(str(tmp_path))
    findings = result["findings"].get("dup.qml", [])
    assert any(f["code"] == "duplicate_import" for f in findings)


def test_lint_duplicate_object_id(tmp_path):
    _write(
        tmp_path / "dup.qml",
        'import QtQuick\nItem { id: "x" }\nItem { id: "x" }\n',
    )
    result = _lint_project(str(tmp_path))
    findings = result["findings"].get("dup.qml", [])
    assert any(f["code"] == "duplicate_object_id" for f in findings)


def test_lint_suspicious_timer(tmp_path):
    _write(
        tmp_path / "t.qml",
        "import QtQuick\nTimer { interval: 0; repeat: true }\n",
    )
    result = _lint_project(str(tmp_path))
    findings = result["findings"].get("t.qml", [])
    assert any(f["code"] == "suspicious_timer" for f in findings)


def test_lint_clean_project(tmp_path):
    _write(tmp_path / "clean.qml", "import QtQuick\nItem {}\n")
    result = _lint_project(str(tmp_path))
    assert result["findings"] == {}


def test_lint_invalid_path():
    with pytest.raises(ValueError, match="does not exist"):
        _lint_project("/nonexistent/12345")


# ---------------------------------------------------------------------------
# quickshell_project_compatibility
# ---------------------------------------------------------------------------


def test_project_compatibility_small(monkeypatch, docs_fixture_urls):
    from test_migrate import _build_mapping, _install_fetch

    mapping = _build_mapping(docs_fixture_urls)
    _install_fetch(monkeypatch, mapping)
    result = _project_compatibility(str(SMALL), version="v0.3.1")
    assert result["project_root"] == str(SMALL.resolve())
    assert set(result["summary"]) == {"compatible", "incompatible", "uncertain"}
    assert result["affected_files"]
    assert result["note"]


def test_project_compatibility_invalid_path():
    with pytest.raises(ValueError, match="does not exist"):
        _project_compatibility("/nonexistent/12345", version="v0.3.1")


# ---------------------------------------------------------------------------
# quickshell_project_migrate
# ---------------------------------------------------------------------------


def test_migrate_project_proposes_edits(monkeypatch, docs_fixture_urls):
    from test_migrate import _build_mapping

    mapping = _build_mapping(docs_fixture_urls)
    mapping = dict(mapping)

    def fake_fetch(url):
        if url not in mapping:
            raise AssertionError(f"unexpected fetch: {url}")
        return mapping[url]

    monkeypatch.setattr(srv.utils, "_fetch_raw", fake_fetch)

    tmp = FIXTURES.parent.parent  # tests/
    project = tmp / "fixtures" / "projects" / "small"
    result = _migrate_project(str(project), from_version="v0.1.0", to_version="v0.3.1")
    assert result["from_version"] == "v0.1.0"
    assert result["to_version"] == "v0.3.1"
    assert set(result["summary"]) == {"issue_count", "proposed_edit_count"}
    assert result["files"]
    assert result["note"]


def test_migrate_project_invalid_path():
    with pytest.raises(ValueError, match="does not exist"):
        _migrate_project("/nonexistent/12345", from_version="v0.1.0", to_version="v0.3.1")
