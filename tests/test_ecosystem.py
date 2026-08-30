"""Tests for the ecosystem capability: Nix-aware diagnostics, safe runtime
dependency detection, and the named/versioned runtime profile registry.

Nix diagnostics and runtime deps are file/subprocess-based; tests use
``tmp_path`` projects and ``shutil.which`` patches. The profile registry is
an in-memory dict cleared between tests (same pattern as
``_SESSION_REGISTRY`` in test_runtime.py).
"""

from __future__ import annotations

import shutil

import pytest

import quickshell_mcp.server as srv
from quickshell_mcp.sources import ecosystem as eco


@pytest.fixture(autouse=True)
def _clear_profile_registry():
    eco._PROFILE_REGISTRY.clear()
    yield
    eco._PROFILE_REGISTRY.clear()


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# Nix diagnostics
# ---------------------------------------------------------------------------

FLAKE = """\
{
  description = "my shell";
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    nixpkgs-wayland.url = "github:nix-community/nixpkgs-wayland";
  };
  outputs = { self, nixpkgs, ... }: {
    devShells.x86_64-linux.default = nixpkgs.mkShell { };
    devShells.aarch64-linux.default = nixpkgs.mkShell { };
  };
}
"""


def test_nix_diagnostics_no_nix(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda cmd: None)
    result = eco._nix_diagnostics(str(tmp_path))
    assert result["nix_available"] is False
    assert result["flake"]["present"] is False
    assert result["fallback"] is None


def test_nix_diagnostics_with_flake(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}")
    _write(tmp_path / "flake.nix", FLAKE)
    _write(tmp_path / "flake.lock", "{}")
    result = eco._nix_diagnostics(str(tmp_path))
    assert result["flake"]["present"] is True
    assert result["flake"]["devShells"] == ["aarch64-linux.default", "x86_64-linux.default"]
    assert "nixpkgs" in result["flake"]["nixpkgs_inputs"]
    assert result["flake"]["locked"] is True


def test_nix_diagnostics_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(
        shutil, "which", lambda cmd: f"/usr/bin/{cmd}" if cmd in ("dpkg", "nix") else None
    )
    # No flake.nix present -> package-manager fallback.
    result = eco._nix_diagnostics(str(tmp_path))
    assert result["flake"]["present"] is False
    assert result["fallback"] is not None
    assert result["fallback"]["package_manager"] == "apt"


def test_nix_diagnostics_tool_records_stats(tmp_path):
    before = dict(srv._TOOL_CALLS)
    srv.quickshell_nix_diagnostics(str(tmp_path))
    assert (
        srv._TOOL_CALLS["quickshell_nix_diagnostics"]
        == before.get("quickshell_nix_diagnostics", 0) + 1
    )


# ---------------------------------------------------------------------------
# Runtime dependency detection
# ---------------------------------------------------------------------------


def _minimal_shell(root) -> None:
    _write(
        root / "main.qml",
        "import Quickshell\nimport Quickshell.Hyprland\n\n"
        'Quickshell {\n  Process { command: "true" }\n  IpcHandler { }\n}\n',
    )


def test_runtime_dependencies_detects_qml_types(tmp_path):
    _minimal_shell(tmp_path)
    result = eco._runtime_dependencies(str(tmp_path))
    assert "Process" in result["runtime_qml_types"]
    assert "IpcHandler" in result["runtime_qml_types"]
    assert "Quickshell.Hyprland" in result["imports"]
    assert result["compositor"] is not None
    assert isinstance(result["system_binaries"], dict)
    assert result["note"]


def test_runtime_dependencies_empty_project(tmp_path):
    result = eco._runtime_dependencies(str(tmp_path))
    assert result["runtime_qml_types"] == []
    assert result["imports"] == []


def test_runtime_dependencies_tool_records_stats(tmp_path):
    before = dict(srv._TOOL_CALLS)
    srv.quickshell_runtime_dependencies(str(tmp_path))
    assert (
        srv._TOOL_CALLS["quickshell_runtime_dependencies"]
        == before.get("quickshell_runtime_dependencies", 0) + 1
    )


# ---------------------------------------------------------------------------
# Profile registry
# ---------------------------------------------------------------------------


def test_profile_save_list_get(tmp_path):
    srv.quickshell_profile_save("dev", str(tmp_path), compositor="Hyprland")
    listed = srv.quickshell_profile_list()
    assert listed["count"] == 1
    assert listed["profiles"][0]["name"] == "dev"
    assert listed["profiles"][0]["compositor"] == "Hyprland"

    got = srv.quickshell_profile_get("dev")
    assert got["schema_version"] == eco._PROFILE_SCHEMA_VERSION
    assert got["profile"]["project_root"] == str(tmp_path.resolve())


def test_profile_get_missing_raises():
    with pytest.raises(ValueError, match="not found"):
        srv.quickshell_profile_get("nope")


def test_profile_delete(tmp_path):
    srv.quickshell_profile_save("dev", str(tmp_path))
    result = srv.quickshell_profile_delete("dev")
    assert result["deleted"] == "dev"
    assert result["remaining"] == 0
    with pytest.raises(ValueError, match="not found"):
        srv.quickshell_profile_delete("dev")


def test_profile_export_import_roundtrip(tmp_path):
    entrypoint = str(tmp_path / "main.qml")
    srv.quickshell_profile_save(
        "dev", str(tmp_path), entrypoint=entrypoint, compositor="Hyprland", arguments=["-d"]
    )
    exported = srv.quickshell_profile_export("dev")
    assert exported["schema_version"] == 1

    srv.quickshell_profile_delete("dev")
    imported = srv.quickshell_profile_import("dev", exported["profile"])
    assert imported["profile"]["entrypoint"] == entrypoint
    assert imported["profile"]["compositor"] == "Hyprland"
    assert imported["profile"]["arguments"] == ["-d"]


def test_profile_import_newer_schema_refused():
    payload = {
        "project_root": "/tmp/x",
        "schema_version": 999,
    }
    with pytest.raises(ValueError, match="newer"):
        srv.quickshell_profile_import("fut", payload)


def test_profile_import_old_schema_defaults(tmp_path):
    payload = {"project_root": str(tmp_path)}
    result = srv.quickshell_profile_import("legacy", payload)
    assert result["schema_version"] == 1
    assert result["profile"]["arguments"] == []


def test_profile_tool_wrappers_record_stats(tmp_path):
    before = dict(srv._TOOL_CALLS)
    srv.quickshell_profile_save("dev", str(tmp_path))
    srv.quickshell_profile_list()
    srv.quickshell_profile_get("dev")
    assert (
        srv._TOOL_CALLS["quickshell_profile_save"] == before.get("quickshell_profile_save", 0) + 1
    )
    assert (
        srv._TOOL_CALLS["quickshell_profile_list"] == before.get("quickshell_profile_list", 0) + 1
    )
    assert srv._TOOL_CALLS["quickshell_profile_get"] == before.get("quickshell_profile_get", 0) + 1
