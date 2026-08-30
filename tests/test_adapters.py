"""Tests for the desktop adapters: Hyprland, Wayland layers, PipeWire,
D-Bus, and system diagnostics. Adapters use subprocess fixtures offline.
"""

from __future__ import annotations

import json

import pytest

import quickshell_mcp.server as srv
from quickshell_mcp.sources.adapters import _ADAPTERS, _detect_adapter
from quickshell_mcp.sources.adapters import pipewire as pw

# Sample `pw-cli ls Node` output for offline parsing tests.
PW_SAMPLE = """id 42, type PipeWire:Interface:Node/3
\tmedia.class = "Audio/Sink"
\tnode.name = "alsa_output.pci-0000_00_1f.3.analog-stereo"
\tnode.description = "Built-in Audio Analog Stereo"
\tstate = "idle"
id 7, type PipeWire:Interface:Node/3
\tmedia.class = "Audio/Source"
\tnode.name = "alsa_input.pci-0000_00_1f.3.analog-stereo"
\tnode.description = "Built-in Audio Analog Stereo"
\tstate = "running"
"""

# Sample `busctl --user list` output.
BUSCTL_SAMPLE = (
    "NAME                                     PID PROCESS         USER "
    "CONNECTION    UNIT\n"
    "org.freedesktop.portal.Desktop            123 portal          u    "
    ":1.2          dbus.service\n"
    "org.freedesktop.Notifications              456 notificationd  u    "
    ":1.5          dbus.service\n"
)


# ---------------------------------------------------------------------------
# Adapter registry
# ---------------------------------------------------------------------------


def test_adapters_registered():
    names = [a.name for a in _ADAPTERS]
    assert "Hyprland" in names
    assert "PipeWire" in names
    assert "D-Bus" in names
    assert "Wayland layers" in names
    assert "System diagnostics" in names


def test_detect_all_adapters():
    result = _detect_adapter("all")
    assert "adapters" in result
    assert len(result["adapters"]) == len(_ADAPTERS)
    for entry in result["adapters"]:
        assert "adapter" in entry
        assert "available" in entry


def test_detect_unknown_adapter_raises():
    with pytest.raises(ValueError, match="Unknown adapter"):
        _detect_adapter("nope")


# ---------------------------------------------------------------------------
# Hyprland (via subprocess fixture)
# ---------------------------------------------------------------------------


def test_hyprland_unavailable(monkeypatch):
    import shutil

    monkeypatch.setattr(shutil, "which", lambda b: None)
    result = srv.quickshell_hyprland_info()
    assert result["available"] is False
    assert "not found" in result["note"]


def _force_binary(monkeypatch) -> None:
    """Pretend the adapter's binary exists so ``available()`` is True
    regardless of the host environment (CI lacks hyprctl/pw-cli)."""
    import shutil

    monkeypatch.setattr(shutil, "which", lambda cmd: f"/usr/bin/{cmd}")


def test_hyprland_detect(monkeypatch):
    from quickshell_mcp.sources.adapters import hyprland

    payload = (
        '[{"name":"DP-1","model":"VM","make":"","width":1920,"height":1080,'
        '"focused":true,"activeWorkspace":{"id":1}}]'
    )
    monkeypatch.setattr(
        hyprland,
        "_hyprctl_json",
        lambda args: json.loads(payload) if args == ["monitors"] else [],
    )
    _force_binary(monkeypatch)
    result = _detect_adapter("Hyprland")
    assert result["available"] is True
    assert result["monitors"][0]["name"] == "DP-1"
    assert result["monitors"][0]["width"] == 1920


def test_hyprland_detect_returns_lists(monkeypatch):
    from quickshell_mcp.sources.adapters import hyprland

    monkeypatch.setattr(hyprland, "_hyprctl_json", lambda args: [])
    _force_binary(monkeypatch)
    result = _detect_adapter("Hyprland")
    assert result["monitors"] == []
    assert result["workspaces"] == []
    assert result["clients"] == []
    assert result["active_workspace"] is None


# ---------------------------------------------------------------------------
# PipeWire
# ---------------------------------------------------------------------------


def test_parse_nodes():
    nodes = pw._parse_nodes(PW_SAMPLE)
    assert len(nodes) == 2
    sinks = [n for n in nodes if n.get("media.class") == "Audio/Sink"]
    sources = [n for n in nodes if n.get("media.class") == "Audio/Source"]
    assert len(sinks) == 1
    assert sinks[0]["node.name"].startswith("alsa_output")
    assert len(sources) == 1


def test_pipewire_unavailable(monkeypatch):
    monkeypatch.setattr(pw, "_pw_nodes", lambda: "")
    _force_binary(monkeypatch)
    result = _detect_adapter("PipeWire")
    assert result["available"] is True
    assert result["sinks"] == []
    assert result["sources"] == []


# ---------------------------------------------------------------------------
# D-Bus
# ---------------------------------------------------------------------------


def test_dbus_services(monkeypatch):
    monkeypatch.setattr("quickshell_mcp.sources.adapters.dbus._busctl_list", lambda: BUSCTL_SAMPLE)
    _force_binary(monkeypatch)
    result = srv.quickshell_dbus_services()
    assert "org.freedesktop.portal.Desktop" in result["services"]
    assert "org.freedesktop.Notifications" in result["services"]


def test_dbus_empty(monkeypatch):
    monkeypatch.setattr("quickshell_mcp.sources.adapters.dbus._busctl_list", lambda: "")
    _force_binary(monkeypatch)
    result = srv.quickshell_dbus_services()
    assert result["services"] == []


# ---------------------------------------------------------------------------
# System diagnostics
# ---------------------------------------------------------------------------


def test_system_diagnostics_reports_missing(monkeypatch):
    monkeypatch.setattr("quickshell_mcp.sources.adapters.system.shutil.which", lambda cmd: None)
    result = srv.quickshell_system_diagnostics()
    assert result["available"] is True
    assert "qs" in result["missing_commands"]
    assert result["present_commands"] == []


# ---------------------------------------------------------------------------
# Tool wrappers
# ---------------------------------------------------------------------------


def test_adapter_tool_wrappers_record_stats():
    before = dict(srv._TOOL_CALLS)
    srv.quickshell_hyprland_info()
    assert srv._TOOL_CALLS["quickshell_hyprland_info"] == (
        before.get("quickshell_hyprland_info", 0) + 1
    )
