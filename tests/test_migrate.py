"""Tests for quickshell_migrate: version-to-version migration analysis.

Offline by construction: synthetic per-version guide indexes, type pages, and
a changelog mirroring the real quickshell.org markup, driven through a fake
``_fetch_raw`` (same pattern as test_compat.py).  The fixture history encodes
every migration scenario the tool must report:

- Quickshell.shellRoot renamed to shellDir in v0.2.0
- LegacyThing removed in v0.3.0, changelog directs to ModernThing
- PanelWindow.oldProp deprecated on the LegacyThing page
- PanelWindow.exclusiveLayer removed without a documented replacement
- PanelWindow.layer semantics changed in v0.3.0 (breaking-changelog)
- Quickshell.OldStuff namespace dropped after v0.2.0 (import change)
- PanelWindow.exclusiveZone introduced in v0.2.0 (multi-release migration)
"""

from __future__ import annotations

import re

import httpx
import pytest
from conftest import load_fixture

import quickshell_mcp.server as srv
import quickshell_mcp.sources.migrate as _migrate_mod
from quickshell_mcp import utils  # noqa: E402

QT = srv.QT_DOCS_BASE

_VERSIONS = ["v0.3.1", "v0.3.0", "v0.2.1", "v0.2.0", "v0.1.0"]


def _wrap_page(markdown: str) -> str:
    return f"<html><body><main>{markdown}</main></body></html>"


def _panel_window_page(version: str) -> str:
    props = ["- layer  :\n  [string](https://doc.qt.io/qt-6/qml-string.html)"]
    if version >= "v0.2.0":
        props.insert(0, "- exclusiveZone  :\n  [int](https://doc.qt.io/qt-6/qml-int.html)")
        props.insert(0, "- exclusiveMode  :\n  [int](https://doc.qt.io/qt-6/qml-int.html)")
    else:
        props.insert(0, "- exclusiveLayer  :\n  [int](https://doc.qt.io/qt-6/qml-int.html)")
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


def _legacy_page() -> str:
    return """\
# LegacyThing

## LegacyThing: [QtObject](https://doc.qt.io/qt-6/qml-qtqml-qtobject.html)

## Properties [[?]](/docs/v0.1.0/guide/qml-language#properties)

- oldProp  :
  [string](https://doc.qt.io/qt-6/qml-string.html)

  Note: oldProp is deprecated. Use newProp instead.

## Signals [[?]](/docs/v0.1.0/guide/qml-language#signals)

- gamma ()
"""


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
"""


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
- Changed PanelWindow.layer semantics: it now takes a WindowLayer enum instead of a string.

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

## Breaking Changes

- Removed the Quickshell.OldStuff namespace and its OldWidget type.

## v0.1.0

## [Documentation](/docs/v0.1.0/guide)

---

Initial release
"""


def _type_index_for_version(version: str) -> dict[str, list[str]]:
    if version in ("v0.1.0", "v0.2.0"):
        return {
            "Quickshell": (
                ["PanelWindow", "QsWindow", "Quickshell", "LegacyThing"]
                if version == "v0.1.0"
                else ["PanelWindow", "QsWindow", "Quickshell"]
            ),
            "Quickshell.OldStuff": ["OldWidget"],
            "Quickshell.Hyprland": ["HyprlandMonitor"],
        }
    return {
        "Quickshell": ["PanelWindow", "QsWindow", "Quickshell", "ModernThing"],
        "Quickshell.Hyprland": ["HyprlandMonitor"],
    }


def _guide_index_html(version: str, types_by_ns: dict[str, list[str]]) -> str:
    links = []
    for ns, names in types_by_ns.items():
        for name in names:
            links.append(f'<a href="/docs/{version}/types/{ns}/{name}/">{name}</a>')
    return "<html><body><main>" + "".join(links) + "</main></body></html>"


def _type_pages(version: str) -> dict[str, str]:
    pages: dict[str, str] = {
        "Quickshell/PanelWindow": _panel_window_page(version),
        "Quickshell.Hyprland/HyprlandMonitor": _hyprland_monitor_page(),
    }
    if version == "v0.1.0":
        pages["Quickshell/LegacyThing"] = _legacy_page()
        pages["Quickshell/Quickshell"] = _quickshell_old_page()
    else:
        pages["Quickshell/Quickshell"] = _quickshell_page()
    return pages


def _build_mapping(docs_fixture_urls: dict[str, str]) -> dict[str, str]:
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
        if url not in mapping:
            raise AssertionError(f"unexpected fetch: {url}")
        return mapping[url]

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)


def _migrate(mapping: dict[str, str], monkeypatch, **kwargs) -> dict:
    _install_fetch(monkeypatch, mapping)
    return srv._migrate(**kwargs)


def _issue_for(report: dict, status: str) -> list[dict]:
    return [issue for issue in report["issues"] if issue["status"] == status]


def test_collect_api_refs_objects_bindings_handlers():
    source = (
        "PanelWindow {\n    exclusiveZone: 1\n    onClosed: { }\n"
        '    Hyprland.HyprlandMonitor { name: "a" }\n}'
    )
    parsed = srv._parse_structure(srv._tokenize(source))
    refs = srv._collect_api_refs(parsed)
    by_label = {}
    for ref in refs:
        key = f"{ref['type_name']}.{ref['member']}" if ref["member"] else ref["type_name"]
        by_label[key] = ref
    assert by_label["PanelWindow"]["member"] is None
    assert by_label["PanelWindow.exclusiveZone"]["line"] == 2
    assert by_label["PanelWindow.closed"]["line"] == 3  # onClosed -> closed
    assert by_label["HyprlandMonitor"]["namespace_hint"] == "Hyprland"


def test_rename_with_location(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    report = _migrate(
        mapping,
        monkeypatch,
        code='import Quickshell\nQuickshell {\n    shellRoot: "/etc"\n}',
        from_version="v0.1.0",
        to_version="v0.3.1",
    )
    assert report["summary"]["verdict"] == "changes_required"
    issues = _issue_for(report, "renamed")
    assert len(issues) == 1
    issue = issues[0]
    assert issue["old_api"] == "Quickshell.shellRoot"
    assert issue["new_api"] == "Quickshell.shellDir"
    assert issue["classification"] == "definite"
    assert issue["severity"] == "error"
    assert issue["confidence"] == "high"
    assert issue["changed_in_version"] == "v0.2.0"
    assert issue["location"] == {"line": 3, "column": 5}
    assert issue["source"] and "changelog" in issue["source"]["text"]
    assert report["migration_plan"][0] == (
        "Rename Quickshell.shellRoot to Quickshell.shellDir (renamed in v0.2.0). [definite]"
    )


def test_removed_api_with_documented_replacement(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    report = _migrate(
        mapping,
        monkeypatch,
        code="import Quickshell\nLegacyThing {}",
        from_version="v0.1.0",
        to_version="v0.3.1",
    )
    issues = _issue_for(report, "removed")
    assert len(issues) == 1  # the member finding is subsumed by the type
    issue = issues[0]
    assert issue["old_api"] == "LegacyThing"
    assert issue["new_api"] == "ModernThing"
    assert issue["classification"] == "definite"
    assert issue["severity"] == "error"
    assert issue["changed_in_version"] == "v0.3.0"
    assert "ModernThing" in issue["suggestion"]


def test_removed_api_without_replacement_is_manual_review(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    report = _migrate(
        mapping,
        monkeypatch,
        code="import Quickshell\nPanelWindow {\n    exclusiveLayer: 1\n}",
        from_version="v0.1.0",
        to_version="v0.3.1",
    )
    issues = _issue_for(report, "removed")
    assert len(issues) == 1
    issue = issues[0]
    assert issue["old_api"] == "PanelWindow.exclusiveLayer"
    assert issue["classification"] == "manual_review"
    assert issue["severity"] == "warning"
    assert issue["confidence"] == "medium"


def test_deprecation_with_replacement(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    report = _migrate(
        mapping,
        monkeypatch,
        code="import Quickshell\nLegacyThing {\n    oldProp: 1\n}",
        from_version="v0.1.0",
        to_version="v0.1.0",
    )
    issues = _issue_for(report, "deprecated")
    assert len(issues) == 1
    issue = issues[0]
    assert issue["old_api"] == "LegacyThing.oldProp"
    assert issue["new_api"] == "newProp"
    assert issue["classification"] == "likely"
    assert issue["severity"] == "warning"


def test_changed_property_semantics_from_changelog(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    report = _migrate(
        mapping,
        monkeypatch,
        code='import Quickshell\nPanelWindow {\n    layer: "top"\n}',
        from_version="v0.2.0",
        to_version="v0.3.1",
    )
    issues = _issue_for(report, "behavior")
    assert len(issues) == 1
    issue = issues[0]
    assert issue["classification"] == "manual_review"
    assert issue["severity"] == "warning"
    assert issue["changed_in_version"] == "v0.3.0"
    assert "PanelWindow.layer" in issue["old_api"]
    assert report["summary"]["verdict"] == "changes_required"


def test_behavioral_scan_respects_range(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    # The layer breaking change is in v0.3.0; a migration from v0.3.0 excludes it.
    report = _migrate(
        mapping,
        monkeypatch,
        code='import Quickshell\nPanelWindow {\n    layer: "top"\n}',
        from_version="v0.3.0",
        to_version="v0.3.1",
    )
    assert report["issues"] == []
    assert report["summary"]["verdict"] == "compatible"


def test_changed_import(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    report = _migrate(
        mapping,
        monkeypatch,
        code="import Quickshell\nimport Quickshell.OldStuff\nItem {}",
        from_version="v0.2.0",
        to_version="v0.3.1",
    )
    issues = _issue_for(report, "import_removed")
    assert len(issues) == 1
    issue = issues[0]
    assert issue["old_api"] == "import Quickshell.OldStuff"
    assert issue["classification"] == "manual_review"
    assert issue["severity"] == "warning"
    assert issue["location"] == {"line": 2, "column": 8}


def test_multi_version_migration_plan_ordered(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    source = (
        "import Quickshell\n"
        'Quickshell {\n    shellRoot: "/etc"\n}\n'
        "PanelWindow {\n    exclusiveZone: 1\n}"
    )
    report = _migrate(
        mapping,
        monkeypatch,
        code=source,
        from_version="v0.1.0",
        to_version="v0.3.1",
    )
    assert len(_issue_for(report, "renamed")) == 1
    introduced = _issue_for(report, "introduced")
    assert len(introduced) == 1
    assert introduced[0]["old_api"] == "PanelWindow.exclusiveZone"
    assert introduced[0]["changed_in_version"] == "v0.2.0"
    assert introduced[0]["severity"] == "info"
    # The rename (definite, v0.2.0) sorts before the advisory note.
    assert report["migration_plan"][0].startswith("Rename Quickshell.shellRoot")


def test_already_compatible_code(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    report = _migrate(
        mapping,
        monkeypatch,
        code="import Quickshell\nPanelWindow {\n    exclusiveZone: 1\n}",
        from_version="v0.2.0",
        to_version="v0.3.1",
    )
    assert report["issues"] == []
    assert report["summary"]["verdict"] == "compatible"
    assert report["summary"]["counts"]["definite"] == 0
    assert report["migration_plan"] == ["No API migration is required to go from v0.2.0 to v0.3.1."]


def test_unknown_api_is_uncertain(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    report = _migrate(
        mapping,
        monkeypatch,
        code="TotallyMadeUpThing {\n    x: 1\n}",
        from_version="v0.1.0",
        to_version="v0.3.1",
    )
    assert report["summary"]["verdict"] == "uncertain"
    issues = _issue_for(report, "not_found")
    assert len(issues) == 1  # the member is subsumed by the unknown type
    assert issues[0]["old_api"] == "TotallyMadeUpThing"
    assert issues[0]["classification"] == "manual_review"
    assert issues[0]["confidence"] == "low"


def test_qt_type_is_not_false_positive(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    report = _migrate(
        mapping,
        monkeypatch,
        code='import QtQuick\nRectangle {\n    color: "red"\n}',
        from_version="v0.1.0",
        to_version="v0.3.1",
    )
    assert report["issues"] == []
    assert report["summary"]["verdict"] == "compatible"


def test_malformed_qml_reports_error_without_crashing(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    report = _migrate(
        mapping,
        monkeypatch,
        code="PanelWindow { foo: 1 ",
        from_version="v0.1.0",
        to_version="v0.3.1",
    )
    assert report["summary"]["verdict"] == "uncertain"
    issues = _issue_for(report, "malformed")
    assert len(issues) == 1
    assert issues[0]["severity"] == "error"


def test_local_component_matching_filename_is_skipped(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    report = _migrate(
        mapping,
        monkeypatch,
        code="MyWidget {\n    customProp: 1\n}",
        from_version="v0.2.0",
        to_version="v0.3.1",
        filename="MyWidget.qml",
    )
    assert report["issues"] == []
    assert report["summary"]["verdict"] == "compatible"


def test_api_input_has_no_location(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    report = _migrate(
        mapping,
        monkeypatch,
        api="Quickshell.shellRoot",
        from_version="v0.1.0",
        to_version="v0.3.1",
    )
    issue = _issue_for(report, "renamed")[0]
    assert issue["location"] is None
    assert issue["new_api"] == "Quickshell.shellDir"


def test_type_input(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    report = _migrate(
        mapping,
        monkeypatch,
        type="LegacyThing",
        from_version="v0.1.0",
        to_version="v0.3.1",
    )
    issue = _issue_for(report, "removed")[0]
    assert issue["new_api"] == "ModernThing"


def test_requires_versions(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    with pytest.raises(TypeError):
        _migrate(mapping, monkeypatch, code="PanelWindow {}", to_version="v0.3.1")
    with pytest.raises(TypeError):
        _migrate(mapping, monkeypatch, code="PanelWindow {}", from_version="v0.1.0")


def test_requires_exactly_one_input(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    with pytest.raises(ValueError, match="Exactly one of code, api, or type"):
        _migrate(mapping, monkeypatch, from_version="v0.1.0", to_version="v0.3.1")
    with pytest.raises(ValueError, match="Exactly one of code, api, or type"):
        _migrate(
            mapping,
            monkeypatch,
            code="PanelWindow {}",
            api="PanelWindow.exclusiveZone",
            from_version="v0.1.0",
            to_version="v0.3.1",
        )


def test_reversed_range_raises(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    with pytest.raises(ValueError, match="newer than to_version"):
        _migrate(
            mapping,
            monkeypatch,
            code="PanelWindow {}",
            from_version="v0.3.1",
            to_version="v0.2.0",
        )


def test_unknown_version_raises(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    with pytest.raises(ValueError, match="Unknown version"):
        _migrate(
            mapping,
            monkeypatch,
            code="PanelWindow {}",
            from_version="v0.1.0",
            to_version="v9.9.9",
        )


def test_import_diff_index_error_returns_cannot_verify(monkeypatch, docs_fixture_urls):
    parsed = srv._parse_structure(srv._tokenize("import Quickshell"))
    monkeypatch.setattr(
        _migrate_mod,
        "_build_index",
        lambda v: (_ for _ in ()).throw(RuntimeError("index unavailable")),
    )
    issues = srv._import_diff(parsed, "v0.1.0", "v0.3.1")
    assert len(issues) == 1
    assert issues[0]["status"] == "cannot_verify"
    assert issues[0]["classification"] == "manual_review"
    assert issues[0]["confidence"] == "low"


def test_import_diff_non_404_http_error_returns_cannot_verify(monkeypatch, docs_fixture_urls):
    parsed = srv._parse_structure(srv._tokenize("import Quickshell"))
    guide_url = f"{srv.BASE}/docs/v0.1.0/guide/"
    request = httpx.Request("GET", guide_url)
    response = httpx.Response(500, request=request)
    error = httpx.HTTPStatusError("Internal Server Error", request=request, response=response)

    def raising_fetch(url: str) -> str:
        raise error

    monkeypatch.setattr(utils, "_fetch_raw", raising_fetch)
    issues = srv._import_diff(parsed, "v0.1.0", "v0.3.1")
    assert len(issues) == 1
    assert issues[0]["status"] == "cannot_verify"


def test_stats_recorded_through_tool(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    srv.quickshell_migrate(api="Quickshell.shellRoot", from_version="v0.1.0", to_version="v0.3.1")
    assert utils._TOOL_CALLS.get("quickshell_migrate", 0) == 1
