"""Opt-in live smoke tests against the real quickshell.org.

Run with: QUICKSHELL_LIVE_TEST=1 pytest -m live
"""

from __future__ import annotations

import os

import pytest

import quickshell_mcp.server as srv

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("QUICKSHELL_LIVE_TEST") != "1",
        reason="set QUICKSHELL_LIVE_TEST=1 to hit the real site",
    ),
]


def test_live_list_versions():
    versions = srv.list_versions(refresh=True)
    assert versions
    assert srv._latest_version() == versions[0]


def test_live_type_page():
    md = srv._type_page("HyprlandMonitor", "Quickshell.Hyprland", "latest")
    assert "*Source:" in md
    assert "HyprlandMonitor" in md


def test_live_guide_page():
    out = srv._guide_page("qml-language", "latest")
    assert "# QML Language" in out


def test_live_changelog_sections():
    sections = srv._changelog_sections()
    assert sections
    assert sections[0]["version"] == srv._latest_version()
    assert all(s["version"] and s["text"] for s in sections)


def test_live_check_compatibility():
    result = srv._check_compatibility(api="PanelWindow.exclusiveZone", version="latest")
    assert result["compatibility"] in ("compatible", "incompatible", "uncertain")
    assert result["detected_api"]["type"] == "PanelWindow"
