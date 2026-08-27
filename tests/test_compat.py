"""Tests for quickshell_check_compatibility: version-aware API checking.

Offline by construction: synthetic per-version guide indexes, type pages, and
a changelog mirroring the real quickshell.org markup, driven through a fake
``_fetch_raw`` (same pattern as test_validate.py).
"""

from __future__ import annotations

import re

import pytest
from conftest import load_fixture

import quickshell_mcp.server as srv
from quickshell_mcp import utils  # noqa: E402

QT = srv.QT_DOCS_BASE

_VERSIONS = ["v0.3.1", "v0.3.0", "v0.2.1", "v0.2.0", "v0.1.0"]


def _wrap_page(markdown: str) -> str:
    return f"<html><body><main>{markdown}</main></body></html>"


# Synthetic type pages in the real quickshell.org markdown format (bullet
# lists under `## Properties` / `## Functions` / `## Signals`).  The page is
# version-aware: exclusiveZone was added in v0.2.0.
def _panel_window_page(version: str) -> str:
    props = ["- layer  :\n  [string](https://doc.qt.io/qt-6/qml-string.html)"]
    if version >= "v0.2.0":
        props.insert(0, "- exclusiveZone  :\n  [int](https://doc.qt.io/qt-6/qml-int.html)")
        props.insert(0, "- exclusiveMode  :\n  [int](https://doc.qt.io/qt-6/qml-int.html)")
    return f"""\
# PanelWindow

## PanelWindow: [QsWindow](/docs/{version}/types/Quickshell/QsWindow)

## Properties [[?]](/docs/{version}/guide/qml-language#properties)

{chr(10).join(props)}

## Functions [[?]](/docs/{version}/guide/qml-language#functions)

- mapFromGlobal (point)  :
  [point](https://doc.qt.io/qt-6/qml-point.html)

## Signals [[?]](/docs/{version}/guide/qml-language#signals)

- statusChanged (int status)

- closed ()
"""


# A type with a deprecated property, documented via a note in the page body.
def _deprecated_page(version: str) -> str:
    return f"""\
# LegacyThing

## LegacyThing: [QtObject](https://doc.qt.io/qt-6/qml-qtqml-qtobject.html)

## Properties [[?]](/docs/{version}/guide/qml-language#properties)

- oldProp  :
  [string](https://doc.qt.io/qt-6/qml-string.html)

  Note: oldProp is deprecated. Use newProp instead.

## Signals [[?]](/docs/{version}/guide/qml-language#signals)

- gamma ()

## Functions [[?]](/docs/{version}/guide/qml-language#functions)

- compute ()
"""


# The Quickshell type page hosts both shellRoot (removed) and shellDir
# (current), letting us test rename detection via the changelog.
def _quickshell_page() -> str:
    return """\
# Quickshell

## Quickshell: [QtObject](https://doc.qt.io/qt-6/qml-qtqml-qtobject.html)

## Properties [[?]](/docs/v0.3.1/guide/qml-language#properties)

- shellDir  :
  [string](https://doc.qt.io/qt-6/qml-string.html)

- cacheDir  :
  [string](https://doc.qt.io/qt-6/qml-string.html)
"""


# v0.1.0 only documents shellRoot; the rename happened in v0.2.0.
def _quickshell_old_page() -> str:
    return """\
# Quickshell

## Quickshell: [QtObject](https://doc.qt.io/qt-6/qml-qtqml-qtobject.html)

## Properties [[?]](/docs/v0.1.0/guide/qml-language#properties)

- shellRoot  :
  [string](https://doc.qt.io/qt-6/qml-string.html)
"""


def _hyprland_monitor_page() -> str:
    return """\
# HyprlandMonitor

## HyprlandMonitor: [QtObject](https://doc.qt.io/qt-6/qml-qtqml-qtobject.html)

## Properties [[?]](/docs/v0.3.1/guide/qml-language#properties)

- name  :
  [string](https://doc.qt.io/qt-6/qml-string.html)

- width  :
  [int](https://doc.qt.io/qt-6/qml-int.html)

## Signals [[?]](/docs/v0.3.1/guide/qml-language#signals)

- monitorChanged ()
"""


# Synthetic changelog in the real `## vX.Y.Z` heading structure.
def _changelog_markdown() -> str:
    return """\
# Changelog

## v0.3.1

## [Documentation](/docs/v0.3.1/guide)

---

## Bug Fixes

- Fixed hiding the last PanelWindow on screen causing a crash under X11.

## v0.3.0

## [Documentation](/docs/v0.3.0/guide)

---

## Breaking Changes

- Removed LegacyThing. Use ModernThing instead.

## New Features

- Added minimized, maximized, and fullscreen properties to FloatingWindow.

## v0.2.1

## [Documentation](/docs/v0.2.1/guide)

---

## New Features

- Added support for Qt 6.10

## v0.2.0

## [Documentation](/docs/v0.2.0/guide)

---

## Other Changes

- Quickshell.shellRoot has been renamed to Quickshell.shellDir.

## v0.1.0

## [Documentation](/docs/v0.1.0/guide)

---

Initial release
"""


def _guide_index_html(version: str, types_by_ns: dict[str, list[str]]) -> str:
    links = []
    for ns, names in types_by_ns.items():
        for name in names:
            links.append(f'<a href="/docs/{version}/types/{ns}/{name}/">{name}</a>')
    return "<html><body><main>" + "".join(links) + "</main></body></html>"


def _type_index_for_version(version: str) -> dict[str, list[str]]:
    """Which types exist in each published version, mirroring the real API
    history used across the tests."""
    if version == "v0.1.0":
        return {
            "Quickshell": ["PanelWindow", "QsWindow", "Quickshell", "LegacyThing"],
            "Quickshell.Hyprland": ["HyprlandMonitor"],
        }
    if version == "v0.2.0":
        return {
            "Quickshell": ["PanelWindow", "QsWindow", "Quickshell"],
            "Quickshell.Hyprland": ["HyprlandMonitor"],
        }
    if version in ("v0.2.1", "v0.3.0", "v0.3.1"):
        return {
            "Quickshell": ["PanelWindow", "QsWindow", "Quickshell", "ModernThing"],
            "Quickshell.Hyprland": ["HyprlandMonitor"],
        }
    raise ValueError(f"unexpected version {version}")


def _type_pages(version: str) -> dict[str, str]:
    """Type page markdown served for the given version."""
    pages = {
        "Quickshell/PanelWindow": _panel_window_page(version),
        "Quickshell.Hyprland/HyprlandMonitor": _hyprland_monitor_page(),
        "Quickshell/LegacyThing": _deprecated_page(version),
    }
    if version == "v0.1.0":
        pages["Quickshell/Quickshell"] = _quickshell_old_page()
    else:
        pages["Quickshell/Quickshell"] = _quickshell_page()
    return pages


def _build_mapping(docs_fixture_urls: dict[str, str]) -> dict[str, str]:
    """Docs fixture URLs plus per-version synthetic indexes, type pages, and
    the changelog."""
    base = srv.BASE
    mapping = dict(docs_fixture_urls)
    mapping[f"{base}/changelog/"] = _wrap_page(_changelog_markdown())

    for version in _VERSIONS:
        mapping[f"{base}/docs/{version}/guide/"] = _guide_index_html(
            version, _type_index_for_version(version)
        )
        for path, page in _type_pages(version).items():
            mapping[f"{base}/docs/{version}/types/{path}/"] = _wrap_page(page)

    qt_htmls = [
        load_fixture("qt_qtquick_qmlmodule.html"),
        load_fixture("qt_qtquick_controls_qmlmodule.html"),
    ]
    mapping[f"{QT}/qtquick-qmlmodule.html"] = qt_htmls[0]
    mapping[f"{QT}/qtquick-controls-qmlmodule.html"] = qt_htmls[1]
    for html in qt_htmls:
        for stem in re.findall(r'href="([a-z0-9-]+-qmlmodule)\.html"', html):
            mapping.setdefault(f"{QT}/{stem}.html", "")
    return mapping


def _install_fetch(monkeypatch, mapping: dict[str, str]) -> None:
    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

def test_parse_api_ref_member():
    ref = srv._parse_api_ref("PanelWindow.exclusiveZone")
    assert ref == {"namespace_hint": None, "type_name": "PanelWindow", "member": "exclusiveZone"}


def test_parse_api_ref_type_only():
    ref = srv._parse_api_ref("PanelWindow")
    assert ref == {"namespace_hint": None, "type_name": "PanelWindow", "member": None}


def test_parse_api_ref_namespace_and_member():
    ref = srv._parse_api_ref("Quickshell.Hyprland.HyprlandMonitor.name")
    assert ref["namespace_hint"] == "Quickshell.Hyprland"
    assert ref["type_name"] == "HyprlandMonitor"
    assert ref["member"] == "name"


def test_parse_api_ref_namespace_without_member():
    ref = srv._parse_api_ref("Quickshell.Hyprland.HyprlandMonitor")
    assert ref["namespace_hint"] == "Quickshell.Hyprland"
    assert ref["type_name"] == "HyprlandMonitor"
    assert ref["member"] is None


def test_parse_api_ref_method_syntax():
    ref = srv._parse_api_ref("HyprlandWorkspace.activate()")
    assert ref["type_name"] == "HyprlandWorkspace"
    assert ref["member"] == "activate()"


def test_parse_api_ref_requires_a_type():
    with pytest.raises(ValueError):
        srv._parse_api_ref("exclusiveZone")


def test_check_compatibility_requires_exactly_one_input():
    with pytest.raises(ValueError, match="Exactly one of api, type, or code"):
        srv._check_compatibility(api="PanelWindow.exclusiveZone", type="PanelWindow")
    with pytest.raises(ValueError, match="Exactly one of api, type, or code"):
        srv._check_compatibility()

def test_changelog_sections_split_by_version(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    sections = srv._changelog_sections()
    assert [s["version"] for s in sections] == _VERSIONS
    assert any("shellRoot" in s["text"] for s in sections)


def test_changelog_hits_rename(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    hits = srv._changelog_hits(["shellRoot"])
    assert hits
    assert hits[0]["version"] == "v0.2.0"
    assert "renamed to" in hits[0]["text"]


def test_changelog_hits_empty(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    assert srv._changelog_hits(["NoSuchApiEver"]) == []

def test_api_exists_in_requested_version(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._check_compatibility(api="PanelWindow.exclusiveZone", version="v0.3.1")
    assert result["compatibility"] == "compatible"
    assert result["target_version"] == "v0.3.1"
    assert result["detected_api"]["type"] == "PanelWindow"
    assert result["detected_api"]["member"] == "exclusiveZone"
    assert result["detected_api"]["origin"] == "quickshell"
    assert result["confidence"] == "high"
    assert result["change_info"] is None
    assert result["documentation"], "should cite the version-specific type page"


def test_api_introduced_after_requested_version(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    # exclusiveZone does not exist in v0.1.0.
    result = srv._check_compatibility(api="PanelWindow.exclusiveZone", version="v0.1.0")
    assert result["compatibility"] == "incompatible"
    assert result["change_info"]["status"] == "introduced"
    assert result["change_info"]["target_version"] == "v0.2.0"
    assert result["earliest_known_version"] == "v0.2.0"
    assert "introduced" in result["explanation"]


def test_type_introduced_after_requested_version(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    # ModernThing only exists from v0.2.1 onward.
    result = srv._check_compatibility(type="ModernThing", version="v0.2.0")
    assert result["compatibility"] == "incompatible"
    assert result["change_info"]["status"] == "introduced"
    assert result["change_info"]["target_version"] == "v0.2.1"


def test_removed_api(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    # LegacyThing existed in v0.1.0 only; removed after that.
    result = srv._check_compatibility(type="LegacyThing", version="v0.3.1")
    assert result["compatibility"] == "incompatible"
    assert result["change_info"]["status"] == "removed"
    assert result["earliest_known_version"] == "v0.1.0"
    assert result["latest_known_version"] == "v0.1.0"
    assert result["changelog_entry"]["version"] == "v0.3.0"  # breaking change


def test_renamed_api(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    # shellRoot was renamed to shellDir in v0.2.0.
    result = srv._check_compatibility(api="Quickshell.shellRoot", version="v0.3.1")
    assert result["compatibility"] == "incompatible"
    assert result["change_info"]["status"] == "renamed"
    assert result["change_info"]["likely_replacement"] == "Quickshell.shellDir"
    assert result["changelog_entry"]["version"] == "v0.2.0"


def test_renamed_api_old_version_is_compatible(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._check_compatibility(api="Quickshell.shellRoot", version="v0.1.0")
    assert result["compatibility"] == "compatible"
    assert result["detected_api"]["member"] == "shellRoot"


def test_version_specific_documentation(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._check_compatibility(api="PanelWindow.exclusiveZone", version="v0.3.1")
    doc = [d for d in result["documentation"] if d["kind"] == "type_page"]
    assert doc
    assert doc[0]["version"] == "v0.3.1"
    assert "/docs/v0.3.1/types/Quickshell/PanelWindow/" in doc[0]["url"]


def test_latest_version_default(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._check_compatibility(api="PanelWindow.exclusiveZone")
    assert result["target_version"] == "v0.3.1"  # latest resolves at runtime
    assert result["compatibility"] == "compatible"


def test_unknown_api_is_uncertain(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._check_compatibility(type="TotallyMadeUpType", version="v0.3.1")
    assert result["compatibility"] == "uncertain"
    assert result["confidence"] == "low"
    assert result["change_info"]["status"] == "not_found"


def test_insufficient_evidence_is_uncertain(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    # The type exists but has no member docs; an unknown member is reported
    # as incompatible-not-found, while a fully unknown API stays uncertain.
    result = srv._check_compatibility(api="QsWindow", version="v0.3.1")
    assert result["compatibility"] == "compatible"


def test_member_absent_on_existing_type(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    # HyprlandMonitor exists but has no 'name2' property in any version.
    result = srv._check_compatibility(api="HyprlandMonitor.name2", version="v0.3.1")
    assert result["compatibility"] == "incompatible"
    assert result["change_info"]["status"] == "not_found"
    assert result["change_info"]["likely_replacement"] == "name"


def test_qt_api_vs_quickshell_api(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._check_compatibility(type="Rectangle", version="v0.3.1")
    assert result["compatibility"] == "compatible"
    assert result["detected_api"]["origin"] == "qt"
    assert "Qt" in result["explanation"]


def test_qt_property_on_qt_type(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    # 'color' is a common QtQuick property on a Qt type; not verifiable via
    # Quickshell docs, so it stays compatible with medium confidence.
    result = srv._check_compatibility(api="Rectangle.color", version="v0.3.1")
    assert result["compatibility"] == "compatible"
    assert result["confidence"] == "medium"


def test_code_snippet_with_incompatible_api(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    source = """\
import Quickshell

PanelWindow {
    exclusiveZone: 1
}
"""
    result = srv._check_compatibility(code=source, version="v0.1.0")
    assert result["compatibility"] == "incompatible"
    assert result["detected_api"]["kind"] == "code"
    findings = result["findings"]
    assert any(f["detected_api"]["type"] == "PanelWindow" for f in findings)
    assert any(f["detected_api"]["member"] == "exclusiveZone" for f in findings)


def test_code_snippet_all_compatible(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    source = """\
import Quickshell

PanelWindow {
    exclusiveZone: 1
}
"""
    result = srv._check_compatibility(code=source, version="v0.3.1")
    assert result["compatibility"] == "compatible"


def test_code_snippet_with_signal_handler(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    source = """\
import Quickshell

PanelWindow {
    onClosed: { }
}
"""
    # onClosed maps to the 'closed' signal; auto-generated onXChanged
    # handlers are also accepted for real properties.
    result = srv._check_compatibility(code=source, version="v0.3.1")
    assert result["compatibility"] == "compatible"


def test_code_snippet_uncertain(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    source = """\
PanelWindow {
    TotallyUnknownThing { width: 100 }
}
"""
    # The unknown type cannot be resolved against any docs -> uncertain.
    result = srv._check_compatibility(code=source, version="v0.3.1")
    assert result["compatibility"] == "uncertain"


def test_deprecated_api(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._check_compatibility(api="LegacyThing.oldProp", version="v0.1.0")
    assert result["compatibility"] == "compatible"
    assert result["change_info"]["status"] == "deprecated"


def test_range_from_to_compatible(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._check_compatibility(
        api="PanelWindow.exclusiveZone", from_version="v0.2.0", to_version="v0.3.0"
    )
    assert result["compatibility"] == "compatible"
    assert result["target_version"] == "v0.3.0"
    assert result["from_version"] == "v0.2.0"


def test_range_from_to_introduced(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._check_compatibility(
        api="PanelWindow.exclusiveZone", from_version="v0.1.0", to_version="v0.3.0"
    )
    assert result["compatibility"] == "incompatible"
    assert "introduced" in result["explanation"]


def test_unknown_version_raises(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    with pytest.raises(ValueError, match="Unknown version"):
        srv._check_compatibility(type="PanelWindow", version="v9.9.9")


def test_stats_recorded_through_tool(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    srv.quickshell_check_compatibility(api="PanelWindow.exclusiveZone", version="v0.3.1")
    assert srv._TOOL_CALLS.get("quickshell_check_compatibility", 0) == 1
