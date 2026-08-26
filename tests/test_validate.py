"""Tests for quickshell_validate_qml: conservative static QML validation."""

from __future__ import annotations

import re

from conftest import load_fixture

import quickshell_docs_mcp.server as srv
from quickshell_docs_mcp import utils  # noqa: E402

QT = srv.QT_DOCS_BASE

# Synthetic type pages in the REAL quickshell.org markdown format (bullet lists
# under `## Properties` / `## Functions` / `## Signals`, scalar type on the line
# after a property bullet). See tests/fixtures/hyprland_monitor.html for the
# live shape.
_PANEL_WINDOW_PAGE = """\
# PanelWindow

## PanelWindow: [QsWindow](/docs/v0.3.1/types/Quickshell/QsWindow)

A window that docks to a panel layer.

## Properties [[?]](/docs/v0.3.1/guide/qml-language#properties)

- exclusiveZone  :
  [int](https://doc.qt.io/qt-6/qml-int.html)

  The exclusive zone in pixels.

- exclusiveMode  :
  [int](https://doc.qt.io/qt-6/qml-int.html)

- layer  :
  [string](https://doc.qt.io/qt-6/qml-string.html)

- enabled  :
  [bool](https://doc.qt.io/qt-6/qml-bool.html)

- visible  :
  [bool](https://doc.qt.io/qt-6/qml-bool.html)

## Functions [[?]](/docs/v0.3.1/guide/qml-language#functions)

- mapFromGlobal (point)  :
  [point](https://doc.qt.io/qt-6/qml-point.html)

## Signals [[?]](/docs/v0.3.1/guide/qml-language#signals)

- statusChanged (int status)

- closed ()
"""

_QS_WINDOW_PAGE = """\
# QsWindow

## QsWindow: [QtObject](https://doc.qt.io/qt-6/qml-qtqml-qtobject.html)

## Properties [[?]](/docs/v0.3.1/guide/qml-language#properties)

- width  :
  [int](https://doc.qt.io/qt-6/qml-int.html)

- height  :
  [int](https://doc.qt.io/qt-6/qml-int.html)

- color  :
  [color](https://doc.qt.io/qt-6/qml-color.html)
"""

_HYPRLAND_MONITOR_PAGE = """\
# HyprlandMonitor

## HyprlandMonitor: [QtObject](https://doc.qt.io/qt-6/qml-qtqml-qtobject.html)

Represents a Hyprland monitor.

## Properties [[?]](/docs/v0.3.1/guide/qml-language#properties)

- name  :
  [string](https://doc.qt.io/qt-6/qml-string.html)

- width  :
  [int](https://doc.qt.io/qt-6/qml-int.html)

- height  :
  [int](https://doc.qt.io/qt-6/qml-int.html)

- refreshRate  :
  [real](https://doc.qt.io/qt-6/qml-real.html)

## Signals [[?]](/docs/v0.3.1/guide/qml-language#signals)

- monitorChanged ()
"""

# Old-style heading format, kept for backwards compatibility with pages that
# predate the bullet layout.
_LEGACY_FORMAT_PAGE = """\
# LegacyThing

## LegacyThing: [QtObject](https://doc.qt.io/qt-6/qml-qtqml-qtobject.html)

## Properties

### **alpha**
int

### **beta**
string

## Signals

### **gamma**

## Functions

### **compute**
"""
_VERSION = "v0.3.1"


def _wrap_page(markdown: str) -> str:
    return f"<html><body><main>{markdown}</main></body></html>"


def _build_mapping(docs_fixture_urls: dict[str, str], version: str = _VERSION) -> dict[str, str]:
    """Docs fixture URLs plus synthetic Quickshell type pages and the Qt module
    pages the Qt index walk needs."""
    base = srv.BASE
    mapping = dict(docs_fixture_urls)
    pages = {
        "Quickshell/PanelWindow": _PANEL_WINDOW_PAGE,
        "Quickshell/QsWindow": _QS_WINDOW_PAGE,
        "Quickshell.Hyprland/HyprlandMonitor": _HYPRLAND_MONITOR_PAGE,
        "Quickshell/LegacyThing": _LEGACY_FORMAT_PAGE,
    }
    for path, page in pages.items():
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


def _codes(result: dict) -> list[tuple[str, str]]:
    return [(d["code"], d["severity"]) for d in result["diagnostics"]]


def _diagnostics_for(result: dict, code: str) -> list[dict]:
    return [d for d in result["diagnostics"] if d["code"] == code]


def test_tokenize_ignores_comments_and_strings():
    tokens = srv._tokenize('// comment { not a brace\nPanelWindow { foo: "a { b" } }')
    values = [t.value for t in tokens]
    assert values.count("{") == 1  # the comment and the string braces are skipped
    assert values.count("}") == 2
    assert "PanelWindow" in values


def test_parse_structure_records_objects_bindings_and_handlers():
    source = "PanelWindow {\n    foo: 123\n    onClosed: { bar() }\n    PopupAnchor { x: 5 }\n}"
    parsed = srv._parse_structure(srv._tokenize(source))
    assert [o.raw for o in parsed.objects] == ["PanelWindow", "PopupAnchor"]
    bindings = {b.object_type: b.name for b in parsed.bindings}
    assert bindings["PanelWindow"] == "foo"
    assert bindings["PopupAnchor"] == "x"
    assert [h.signal_name for h in parsed.handlers] == ["Closed"]


def test_parse_structure_dotted_key_records_owner_only():
    parsed = srv._parse_structure(srv._tokenize("PanelWindow { anchors.top: true }"))
    assert [(b.name, b.literal_kind) for b in parsed.bindings] == [("anchors", "bool")]


def test_parse_structure_group_block_is_a_binding():
    parsed = srv._parse_structure(srv._tokenize("PanelWindow { anchors { top: parent.top } }"))
    assert [b.name for b in parsed.bindings] == ["anchors"]


def test_parse_structure_malformed_unbalanced_brace():
    parsed = srv._parse_structure(srv._tokenize("PanelWindow { foo: 1 "))
    assert parsed.malformed is not None


def test_parse_members_both_formats():
    bullet = srv._parse_members(_PANEL_WINDOW_PAGE)
    assert bullet.properties["exclusiveZone"] == "int"
    assert bullet.properties["layer"] == "string"
    assert bullet.properties["enabled"] == "bool"
    assert "statusChanged" in bullet.signals
    assert "mapFromGlobal" in bullet.methods
    assert bullet.base == "QsWindow"

    legacy = srv._parse_members(_LEGACY_FORMAT_PAGE)
    assert legacy.properties["alpha"] == "int"
    assert "gamma" in legacy.signals
    assert "compute" in legacy.methods


def test_parse_members_ignores_description_bullets():
    markdown = "## Properties\n\n- `window` - a description bullet\n- realProp  :\n  [int](url)\n"
    members = srv._parse_members(markdown)
    assert "window" not in members.properties
    assert members.properties["realProp"] == "int"


def test_valid_code_has_no_error_or_warning(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    source = """\
import Quickshell
import Quickshell.Hyprland

PanelWindow {
    exclusiveZone: 32
    layer: "overlay"
    onClosed: {
        console.log("bye")
    }
    Hyprland.HyprlandMonitor {
        name: "DP-1"
        onMonitorChanged: { refresh() }
    }
}"""
    result = srv._validate(source, version=_VERSION)
    assert result["summary"]["errors"] == 0
    assert result["summary"]["warnings"] == 0
    assert _codes(result) == []


def test_unknown_property_warning_with_alternatives(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate("PanelWindow {\n    exclusiveZon: 123\n}", version=_VERSION)
    diags = _diagnostics_for(result, "unknown_property")
    assert len(diags) == 1
    d = diags[0]
    assert d["severity"] == "warning"
    assert d["line"] == 2
    assert d["column"] == 5
    assert d["api"] == "exclusiveZon"
    assert d["type"] == "PanelWindow"
    assert d["alternatives"], "should suggest real properties"
    assert d["source"] and d["source"]["url"].endswith("PanelWindow/")
    assert "exclusiveZone" in d["message"] or d["message"]


def test_common_qml_members_never_flagged(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate(
        "import Quickshell\nPanelWindow { anchors.top: true; width: 100; visible: true }",
        version=_VERSION,
    )
    assert _codes(result) == []


def test_unknown_bare_type_is_warning(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate("FooBar { x: 1 }", version=_VERSION)
    diags = _diagnostics_for(result, "unknown_type")
    assert len(diags) == 1
    assert diags[0]["severity"] == "warning"
    assert diags[0]["could_not_verify"] is True
    assert diags[0]["alternatives"]


def test_unknown_type_in_known_namespace_is_error(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate(
        "import Quickshell\nQuickshell.Hyprland.Nope {}",
        version=_VERSION,
    )
    diags = _diagnostics_for(result, "unknown_type")
    assert len(diags) == 1
    assert diags[0]["severity"] == "error"
    assert diags[0]["confidence"] == "high"


def test_local_component_matching_filename_is_not_flagged(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate(
        "import Quickshell\nMyWidget {\n    customProp: 1\n}",
        version=_VERSION,
        filename="MyWidget.qml",
    )
    assert _diagnostics_for(result, "unknown_type") == []
    local = _diagnostics_for(result, "local_component")
    assert len(local) == 1
    assert local[0]["severity"] == "info"


def test_string_literal_to_int_property_is_mismatch(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate(
        'import Quickshell\nPanelWindow { exclusiveZone: "high" }', version=_VERSION
    )
    diags = _diagnostics_for(result, "type_mismatch")
    assert len(diags) == 1
    assert diags[0]["severity"] == "warning"
    assert diags[0]["api"] == "exclusiveZone"


def test_expression_value_is_not_a_literal_mismatch(monkeypatch, docs_fixture_urls):
    # `1 + 2` is a JS binding, not a literal; a bool property binding is legal.
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate("import Quickshell\nPanelWindow { enabled: 1 + 2 }", version=_VERSION)
    assert _diagnostics_for(result, "type_mismatch") == []


def test_number_to_string_property_is_not_flagged(monkeypatch, docs_fixture_urls):
    # QML coerces numbers to strings; do not report it.
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate("import Quickshell\nPanelWindow { layer: 3 }", version=_VERSION)
    assert _diagnostics_for(result, "type_mismatch") == []


def test_missing_import_is_warning(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate(
        'import Quickshell\nHyprland.HyprlandMonitor { name: "a" }', version=_VERSION
    )
    diags = _diagnostics_for(result, "missing_import")
    assert len(diags) == 1
    assert diags[0]["severity"] == "warning"
    assert diags[0]["alternatives"] == ["import Quickshell.Hyprland"]


def test_import_present_suppresses_missing_import(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate(
        'import Quickshell\nimport Quickshell.Hyprland\nHyprlandMonitor { name: "a" }',
        version=_VERSION,
    )
    assert _diagnostics_for(result, "missing_import") == []


def test_unrecognized_module_is_info_not_error(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate("import org.kde.plasma\nItem {}", version=_VERSION)
    diags = _diagnostics_for(result, "unknown_module")
    assert len(diags) == 1
    assert diags[0]["severity"] == "info"


def test_version_incompatible_type(monkeypatch, docs_fixture_urls):
    # Build the v0.2.0 doc set: PanelWindow and QsWindow exist, but PopupAnchor
    # (added later) does not, so it resolves only against the newer version.
    base = srv.BASE
    mapping = _build_mapping(docs_fixture_urls, version="v0.2.0")
    mapping[f"{base}/docs/v0.2.0/guide/"] = _wrap_page(
        '<a href="/docs/v0.2.0/types/Quickshell/PanelWindow/">x</a>'
        '<a href="/docs/v0.2.0/types/Quickshell/QsWindow/">x</a>'
    )
    _install_fetch(monkeypatch, mapping)

    result = srv._validate("import Quickshell\nPopupAnchor {}", version="v0.2.0")
    diags = _diagnostics_for(result, "version_incompatible")
    assert len(diags) == 1
    assert diags[0]["severity"] == "error"
    assert "v0.2.0" in diags[0]["message"]
    assert diags[0]["source"], "should point at the newer version's page"


def test_nested_object_validates_against_its_own_type(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    source = """\
import Quickshell

PanelWindow {
    exclusiveZone: 1
    Hyprland.HyprlandMonitor {
        nope: 2
    }
}"""
    result = srv._validate(source, version=_VERSION)
    diags = _diagnostics_for(result, "unknown_property")
    # Only the nested type's bogus property is flagged, not exclusiveZone.
    assert len(diags) == 1
    assert diags[0]["type"] == "Hyprland.HyprlandMonitor"
    assert diags[0]["api"] == "nope"


def test_unknown_signal_is_warning(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate("import Quickshell\nPanelWindow { onBogus: { } }", version=_VERSION)
    diags = _diagnostics_for(result, "unknown_signal")
    assert len(diags) == 1
    assert diags[0]["severity"] == "warning"
    assert diags[0]["api"] == "Bogus"


def test_documented_signal_and_property_changed_not_flagged(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate(
        "import Quickshell\nPanelWindow { onClosed: { }; onExclusiveZoneChanged: { } }",
        version=_VERSION,
    )
    assert _diagnostics_for(result, "unknown_signal") == []


def test_attached_handler_not_validated(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate(
        "import Quickshell\nPanelWindow { Component.onCompleted: { } }", version=_VERSION
    )
    assert _codes(result) == []


def test_malformed_qml_reports_error_without_crashing(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate("PanelWindow { foo: 1 ", version=_VERSION)
    diags = _diagnostics_for(result, "malformed_qml")
    assert len(diags) == 1
    assert diags[0]["severity"] == "error"
    assert result["summary"]["errors"] == 1


def test_malformed_qml_extra_close_brace(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate("PanelWindow { } }")
    assert _diagnostics_for(result, "malformed_qml")


def test_js_handler_body_not_validated(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    source = """\
import Quickshell

PanelWindow {
    onClosed: {
        let x = { a: 1, b: 2 }
        foo.bar = 3
        helper(x)
    }
}"""
    result = srv._validate(source, version=_VERSION)
    assert _codes(result) == []


def test_states_array_objects_not_misvalidated(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    source = """\
import Quickshell

PanelWindow {
    states: [
        State {
            name: "hidden"
            PropertyChanges { target: self; opacity: 0 }
        }
    ]
    transitions: [
        Transition { from: "*"; to: "hidden" }
    ]
}"""
    result = srv._validate(source, version=_VERSION)
    # State/PropertyChanges/Transition are not in our synthetic docs, but they
    # must never produce unknown_property noise on the outer object.
    assert _diagnostics_for(result, "unknown_property") == []


def test_docs_unavailable_degrades_to_cannot_verify(monkeypatch, docs_fixture_urls):
    mapping = _build_mapping(docs_fixture_urls)
    # Deliberately omit the PanelWindow type page so the member fetch 404s
    # (the mock raises on the unexpected URL, which _resolve_members_concurrently
    # swallows the same way a network error would).
    mapping.pop(f"{srv.BASE}/docs/{_VERSION}/types/Quickshell/PanelWindow/", None)
    _install_fetch(monkeypatch, mapping)
    result = srv._validate("import Quickshell\nPanelWindow { foo: 1 }", version=_VERSION)
    # PanelWindow resolves as a type (it is in the index) but its docs are
    # missing: unknown_property must not fire, and the fetch failure is
    # reported as cannot_verify instead of a crash.
    assert _diagnostics_for(result, "unknown_property") == []
    assert _diagnostics_for(result, "cannot_verify")


def test_parse_members_on_real_hyprland_fixture():
    markdown = srv._extract_main_content(load_fixture("hyprland_monitor.html"))
    members = srv._parse_members(markdown, "https://quickshell.org/fake")
    assert members.properties["name"] == "string"
    assert members.properties["width"] == "int"
    assert members.properties["height"] == "int"
    assert members.base == "QtObject"


def test_validate_tool_records_stats(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv.quickshell_validate_qml(
        source="import Quickshell\nPanelWindow { foo: 1 }", version=_VERSION
    )
    assert "diagnostics" in result and "summary" in result and "version" in result
    assert utils._TOOL_CALLS["quickshell_validate_qml"] == 1


def test_validate_empty_source_is_info(monkeypatch, docs_fixture_urls):
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv.quickshell_validate_qml(source="// just a comment\n", version=_VERSION)
    assert _diagnostics_for(result, "cannot_verify")
    assert result["summary"]["errors"] == 0


def test_validate_warning_vs_error_separation(monkeypatch, docs_fixture_urls):
    # A version-incompatible namespace-qualified type is an error; a bare
    # unknown type and an unknown property are warnings.
    base = srv.BASE
    mapping = _build_mapping(docs_fixture_urls, version="v0.2.0")
    mapping[f"{base}/docs/v0.2.0/guide/"] = _wrap_page(
        '<a href="/docs/v0.2.0/types/Quickshell/PanelWindow/">x</a>'
        '<a href="/docs/v0.2.0/types/Quickshell/QsWindow/">x</a>'
    )
    _install_fetch(monkeypatch, mapping)
    source = """\
import Quickshell
PanelWindow { foo: 1 }
WhatEver { x: 2 }
PopupAnchor { y: 3 }"""
    result = srv._validate(source, version="v0.2.0")
    sev = {d["code"]: d["severity"] for d in result["diagnostics"]}
    assert sev["version_incompatible"] == "error"
    assert sev["unknown_property"] == "warning"
    assert sev["unknown_type"] == "warning"


def test_custom_property_declaration_known_type(monkeypatch, docs_fixture_urls):
    # Drives the `property` branch of the declaration parser and the
    # known-type `continue` path of _validate_declarations.
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate(
        "import Quickshell\nPanelWindow { property int myProp }", version=_VERSION
    )
    assert _diagnostics_for(result, "unknown_type") == []
    assert _codes(result) == []


def test_custom_property_declaration_unknown_type(monkeypatch, docs_fixture_urls):
    # Drives the unknown-type diagnostic branch of _validate_declarations.
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate(
        "import Quickshell\nPanelWindow { property NotAType bad }", version=_VERSION
    )
    diags = _diagnostics_for(result, "unknown_type")
    assert len(diags) == 1
    assert diags[0]["severity"] == "warning"
    assert diags[0]["could_not_verify"] is True
    assert diags[0]["type"] == "NotAType"
    assert diags[0]["alternatives"]


def test_readonly_and_required_property_declarations(monkeypatch, docs_fixture_urls):
    # Drives the readonly/required + property branch of the declaration parser.
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate(
        "import Quickshell\n"
        "PanelWindow {\n"
        "    readonly property int a\n"
        "    required property string b\n"
        "}",
        version=_VERSION,
    )
    assert _codes(result) == []


def test_signal_and_function_declarations(monkeypatch, docs_fixture_urls):
    # Drives the signal + function branches of the declaration parser and the
    # `function` classifier branch of _classify_open.
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate(
        "import Quickshell\n"
        "PanelWindow {\n"
        "    signal mySignal()\n"
        "    function helper() { return 1 }\n"
        "}",
        version=_VERSION,
    )
    assert _codes(result) == []


def test_import_alias(monkeypatch, docs_fixture_urls):
    # Drives the `as` alias branch of _parse_import and alias resolution.
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate(
        'import Quickshell.Hyprland as Hyp\nHyp.HyprlandMonitor { name: "DP-1" }',
        version=_VERSION,
    )
    assert _diagnostics_for(result, "missing_import") == []
    assert _diagnostics_for(result, "unknown_type") == []


def test_tokenizer_edge_literals(monkeypatch, docs_fixture_urls):
    # Drives the `#` color literal, `=>` arrow, and `/* */` block comment
    # branches of _tokenize without triggering property validation.
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    source = """\
import Quickshell

PanelWindow {
    color: #ff0000
    /* a block comment with { and } inside */
    onClosed: {
        let f = (a) => a + 1
    }
}"""
    result = srv._validate(source, version=_VERSION)
    assert _codes(result) == []


def test_property_alias_has_no_type_to_validate(monkeypatch, docs_fixture_urls):
    # Drives the `property alias` branch: an alias has no type to validate.
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate(
        "import Quickshell\nPanelWindow { property alias target: otherThing }",
        version=_VERSION,
    )
    assert _diagnostics_for(result, "unknown_type") == []
    assert _codes(result) == []


def test_import_with_explicit_version(monkeypatch, docs_fixture_urls):
    # Drives the version-number branch of _parse_import.
    _install_fetch(monkeypatch, _build_mapping(docs_fixture_urls))
    result = srv._validate(
        "import Quickshell 1.0\nPanelWindow { exclusiveZone: 1 }", version=_VERSION
    )
    assert _codes(result) == []
