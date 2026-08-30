"""Tests for ProjectContext: ``_build_project_context`` / ``_ProjectContext``.

These are local-filesystem tests: they build temporary project trees with
``tmp_path`` and exercise lazy discovery. No network is involved, so no
``mock_fetch`` fixture is needed (the conftest autouse cache reset keeps the
shared 30-minute project-scan cache from leaking between tests).
"""

from __future__ import annotations

from pathlib import Path

import pytest

import quickshell_mcp.server as srv
from quickshell_mcp.sources.project import _build_project_context, _ProjectContext


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _minimal_shell(root: Path) -> Path:
    """A single entrypoint importing Quickshell + Hyprland + QtQuick."""
    _write(
        root / "main.qml",
        "import Quickshell\n"
        "import Quickshell.Hyprland\n"
        "import QtQuick 2.15\n"
        "PanelWindow {\n"
        "    width: 100\n"
        "    color: '#111'\n"
        "    Text { text: 'hi' }\n"
        "}\n",
    )
    return root


def test_empty_project_is_all_unknown(tmp_path):
    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover(
        {
            "qml_files",
            "js_files",
            "entrypoints",
            "imports",
            "quickshell_modules",
            "quickshell_version",
            "qt_version",
            "compositor",
            "config_paths",
            "dependencies",
            "conventions",
        }
    )
    assert info["qml_files"] == []
    assert info["js_files"] == []
    assert info["entrypoints"] == []
    assert info["imports"] == []
    assert info["quickshell_modules"] == []
    assert info["config_paths"] == []
    assert info["dependencies"] == []
    assert info["compositor"] == []
    assert info["quickshell_version"] is None
    assert info["qt_version"] is None
    assert ctx.detection_status("qml_files") == "detected"
    assert ctx.detection_status("compositor") == "unknown"
    assert ctx.detection_status("quickshell_version") == "unknown"


def test_minimal_qml_project_detects_files_imports_entrypoint(tmp_path):
    _minimal_shell(tmp_path)
    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover(
        {"qml_files", "entrypoints", "imports", "quickshell_modules", "dependencies"}
    )
    assert info["qml_files"] == [str(tmp_path / "main.qml")]
    assert info["entrypoints"] == [str(tmp_path / "main.qml")]
    assert [imp["module"] for imp in info["imports"]] == [
        "Quickshell",
        "Quickshell.Hyprland",
        "QtQuick",
    ]
    assert info["quickshell_modules"] == ["Quickshell", "Quickshell.Hyprland"]
    assert info["dependencies"] == ["QtQuick", "Quickshell", "Quickshell.Hyprland"]
    assert ctx.detection_status("qml_files") == "detected"
    assert ctx.detection_status("entrypoints") == "detected"


def test_minimal_qml_project_infers_compositor(tmp_path):
    _minimal_shell(tmp_path)
    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover({"compositor"})
    assert info["compositor"] == ["Hyprland"]
    assert ctx.detection_status("compositor") == "inferred"


def test_minimal_qml_project_infers_qt_version(tmp_path):
    _minimal_shell(tmp_path)
    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover({"qt_version"})
    assert info["qt_version"] == "2.15"
    assert ctx.detection_status("qt_version") == "inferred"


def test_multi_file_project_aggregates(tmp_path):
    _minimal_shell(tmp_path)
    _write(
        tmp_path / "widgets" / "VolumeWidget.qml",
        "import Quickshell.Services.Pipewire\nItem {}\n",
    )
    _write(tmp_path / "widgets" / "BatteryWidget.qml", "import Quickshell.UPower\nItem {}\n")
    _write(tmp_path / "util.js", "function f() { return 1; }\n")
    _write(tmp_path / "config.json", '{"name": "shell"}\n')

    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover(
        {"qml_files", "js_files", "entrypoints", "imports", "config_paths", "conventions"}
    )

    assert len(info["qml_files"]) == 3
    assert set(info["js_files"]) == {str(tmp_path / "util.js")}
    assert info["entrypoints"] == [str(tmp_path / "main.qml")]
    assert info["config_paths"] == [str(tmp_path / "config.json")]
    modules = {imp["module"] for imp in info["imports"]}
    assert modules == {
        "Quickshell",
        "Quickshell.Hyprland",
        "QtQuick",
        "Quickshell.Services.Pipewire",
        "Quickshell.UPower",
    }
    assert info["conventions"]["directory_layout"] == "nested"
    assert "widgets" in info["conventions"].get("component_dirs", [])
    assert info["conventions"]["entrypoint_naming"] == "main.qml"


def test_missing_version_metadata_is_unknown(tmp_path):
    _minimal_shell(tmp_path)
    # Drop the versioned QtQuick import; nothing left carries a version.
    (tmp_path / "main.qml").write_text(
        "import Quickshell\nimport Quickshell.Hyprland\nPanelWindow { width: 100 }\n",
        encoding="utf-8",
    )
    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover({"quickshell_version", "qt_version"})
    assert info["quickshell_version"] is None
    assert info["qt_version"] is None
    assert ctx.detection_status("quickshell_version") == "unknown"
    assert ctx.detection_status("qt_version") == "unknown"


def test_version_declared_on_quickshell_import(tmp_path):
    _write(
        tmp_path / "main.qml",
        "import Quickshell 0.3\nPanelWindow { width: 100 }\n",
    )
    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover({"quickshell_version"})
    assert info["quickshell_version"] == "0.3"
    assert ctx.detection_status("quickshell_version") == "inferred"


# ---------------------------------------------------------------------------
# Components
# ---------------------------------------------------------------------------


def test_components_detected_under_components_and_widgets(tmp_path):
    _minimal_shell(tmp_path)
    _write(tmp_path / "components" / "VolumeWidget.qml", "import QtQuick\nItem {}\n")
    _write(tmp_path / "widgets" / "ClockWidget.qml", "import QtQuick\nItem {}\n")
    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover({"components"})
    names = {c["name"] for c in info["components"]}
    assert names == {"VolumeWidget", "ClockWidget"}
    assert ctx.detection_status("components") == "detected"


def test_components_empty_when_no_component_dirs(tmp_path):
    _minimal_shell(tmp_path)
    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover({"components"})
    assert info["components"] == []
    assert ctx.detection_status("components") == "unknown"


# ---------------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------------


def test_services_detected_from_imports_and_objects(tmp_path):
    _write(
        tmp_path / "main.qml",
        "import Quickshell\n"
        "import Quickshell.Services.Pipewire\n"
        "import QtQuick\n"
        "PanelWindow {\n"
        "    VolumeService {}\n"
        "}\n",
    )
    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover({"services"})
    assert "Quickshell.Services.Pipewire" in info["services"]["modules"]
    assert "VolumeService" in info["services"]["objects"]
    assert ctx.detection_status("services") == "detected"


def test_services_unknown_when_no_evidence(tmp_path):
    _minimal_shell(tmp_path)
    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover({"services"})
    assert info["services"] == {"modules": [], "objects": []}
    assert ctx.detection_status("services") == "unknown"


# ---------------------------------------------------------------------------
# Runtime dependencies
# ---------------------------------------------------------------------------


def test_runtime_dependencies_detected_from_qml_types(tmp_path):
    _write(
        tmp_path / "main.qml",
        "import Quickshell\n"
        "import QtQuick\n"
        "PanelWindow {\n"
        "    Process {}\n"
        "    IpcHandler { target: 'test' }\n"
        "}\n",
    )
    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover({"runtime_dependencies"})
    assert "Process" in info["runtime_dependencies"]["qml_types"]
    assert "IpcHandler" in info["runtime_dependencies"]["qml_types"]
    assert ctx.detection_status("runtime_dependencies") == "detected"


def test_runtime_dependencies_unknown_when_no_evidence(tmp_path):
    _minimal_shell(tmp_path)
    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover({"runtime_dependencies"})
    assert info["runtime_dependencies"] == {"qml_types": [], "config": []}
    assert ctx.detection_status("runtime_dependencies") == "unknown"


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def test_environment_inferred_from_process_env(tmp_path):
    _write(
        tmp_path / "main.qml",
        "import Quickshell\n"
        "PanelWindow {\n"
        "    property string home: process.env.HOME\n"
        '    property string runtime: process.env["XDG_RUNTIME_DIR"]\n'
        "}\n",
    )
    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover({"environment"})
    assert "HOME" in info["environment"]
    assert "XDG_RUNTIME_DIR" in info["environment"]
    assert ctx.detection_status("environment") == "inferred"


def test_environment_unknown_when_no_env_refs(tmp_path):
    _minimal_shell(tmp_path)
    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover({"environment"})
    assert info["environment"] == []
    assert ctx.detection_status("environment") == "unknown"


def test_missing_entrypoint_is_empty(tmp_path):
    _write(tmp_path / "Comp.qml", "import Quickshell\nItem {}\n")
    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover({"entrypoints", "qml_files"})
    assert info["qml_files"] == [str(tmp_path / "Comp.qml")]
    assert info["entrypoints"] == []
    assert ctx.detection_status("entrypoints") == "detected"


def test_unknown_compositor_when_only_core_namespaces(tmp_path):
    _write(
        tmp_path / "main.qml",
        "import Quickshell\nimport Quickshell.Io\nimport QtQuick\nPanelWindow { width: 100 }\n",
    )
    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover({"compositor", "quickshell_modules"})
    assert info["compositor"] == []
    assert ctx.detection_status("compositor") == "unknown"
    assert "Quickshell.Io" in info["quickshell_modules"]


def test_multiple_compositor_modules_all_reported(tmp_path):
    _write(
        tmp_path / "main.qml",
        "import Quickshell\n"
        "import Quickshell.Hyprland\n"
        "import Quickshell.Niri\n"
        "PanelWindow { width: 100 }\n",
    )
    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover({"compositor"})
    assert info["compositor"] == ["Hyprland", "Niri"]
    assert ctx.detection_status("compositor") == "inferred"


def test_repeated_discover_uses_instance_cache(tmp_path):
    _minimal_shell(tmp_path)
    ctx = _build_project_context(str(tmp_path))
    first = ctx.discover({"qml_files", "imports", "compositor"})
    second = ctx.discover({"qml_files", "imports", "compositor"})
    assert first == second
    # Values are cached: same objects, no re-scan.
    assert ctx._values["qml_files"] is first["qml_files"]
    assert ctx._values["imports"] is first["imports"]
    # Statuses stable across accesses.
    assert ctx.detection_status("compositor") == "inferred"


def test_discover_requesting_subset_only_computes_it(tmp_path):
    _minimal_shell(tmp_path)
    ctx = _build_project_context(str(tmp_path))
    ctx.discover({"compositor"})
    # Only compositor was computed (its dependencies are raw scan data).
    assert "compositor" in ctx._values
    assert "qml_files" not in ctx._values


def test_shared_cache_serves_second_context(tmp_path):
    _minimal_shell(tmp_path)
    first = _build_project_context(str(tmp_path))
    first.discover({"qml_files"})
    # A fresh context for the same root reuses the shared scan cache.
    second = _build_project_context(str(tmp_path))
    info = second.discover({"qml_files"})
    assert info["qml_files"] == [str(tmp_path / "main.qml")]


def test_nonexistent_path_raises(tmp_path):
    missing = tmp_path / "does-not-exist"
    with pytest.raises(ValueError, match="does not exist"):
        _build_project_context(str(missing))


def test_file_path_raises(tmp_path):
    file_path = _write(tmp_path / "file.qml", "Item {}\n")
    with pytest.raises(ValueError, match="not a directory"):
        _build_project_context(str(file_path))


def test_unknown_discover_field_raises(tmp_path):
    ctx = _build_project_context(str(tmp_path))
    with pytest.raises(ValueError, match="Unknown context field"):
        ctx.discover({"qml_files", "not_a_field"})


def test_unreadable_qml_skipped_not_fatal(tmp_path, monkeypatch):
    _minimal_shell(tmp_path)
    # A second QML file that cannot be decoded must be skipped, not fatal.
    broken = _write(tmp_path / "broken.qml", "\xff\xfe\x00\x00 binary garbage")

    def failing_read(path, encoding):
        raise UnicodeDecodeError("utf-8", b"", 0, 1, "broken")

    ctx = _build_project_context(str(tmp_path))
    info = ctx.discover({"qml_files", "imports", "entrypoints"})
    assert info["qml_files"] == [str(tmp_path / "main.qml"), str(broken)]
    # Imports/entrypoints from the readable file survive.
    assert [imp["module"] for imp in info["imports"]] == [
        "Quickshell",
        "Quickshell.Hyprland",
        "QtQuick",
    ]
    assert info["entrypoints"] == [str(tmp_path / "main.qml")]


def test_build_project_context_resolves_relative_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _minimal_shell(tmp_path)
    ctx = _build_project_context(".")
    assert ctx.root == tmp_path.resolve()


def test_root_is_always_a_path():
    ctx = _build_project_context(str(Path.cwd()))
    assert isinstance(ctx, _ProjectContext)
    assert isinstance(ctx.root, Path)


def test_assistant_project_info_section(monkeypatch, tmp_path, docs_fixture_urls, mock_fetch):
    _minimal_shell(tmp_path)
    mock_fetch(docs_fixture_urls)

    from test_assistant import _install

    _install(monkeypatch, docs_fixture_urls)

    out = srv._coding_assistant("What is PanelWindow?", project=str(tmp_path))
    assert out["project"]["root"] == str(tmp_path.resolve())
    assert out["project"]["qml_files"] == [str(tmp_path / "main.qml")]
    assert out["project"]["compositor"] == ["Hyprland"]
    assert out["project"]["compositor_status"] == "inferred"
    # The project's inferred compositor feeds the pipeline.
    assert out["intent"]["compositor"] == "hyprland"
    # The research pipeline ran normally.
    assert out["understanding"]
    assert any("Compositor detected" in line for line in out["understanding"])


def test_assistant_project_bad_path_is_surfaced(monkeypatch, docs_fixture_urls, mock_fetch):
    mock_fetch(docs_fixture_urls)

    from test_assistant import _install

    _install(monkeypatch, docs_fixture_urls)

    out = srv._coding_assistant("What is PanelWindow?", project="/nonexistent")
    assert out["project"]["error"]
    assert "does not exist" in out["project"]["error"]
    assert out["understanding"]
