"""Tests for quickshell_explain_error: error diagnosis grounded in docs."""

from __future__ import annotations

import re

from conftest import load_fixture

import quickshell_mcp.server as srv
from quickshell_mcp import utils  # noqa: E402

QT = srv.QT_DOCS_BASE

# Synthetic type page markdown with known properties, signals, and methods.
# Used to verify that the tool correctly checks API existence.
_PANEL_WINDOW_PAGE = """\
# PanelWindow

A window that docks to a panel layer.

## Properties

### **exclusiveZone**
int

The exclusive zone in pixels.

### **exclusionMode**
ExclusionMode

Controls how the panel reserves screen space.

### **implicitHeight**
int

The implicit height.

### **layer**
WlrLayer

The Wayland layer shell layer.

## Signals

### **statusChanged**
Emitted when the panel status changes.

## Methods

### **setVisible**
void setVisible(bool visible)
Show or hide the panel.
"""

_HYPRLAND_MONITOR_PAGE = """\
# HyprlandMonitor

Represents a Hyprland monitor.

## Properties

### **name**
string

The monitor name as reported by Hyprland.

### **width**
int

The monitor width in pixels.

### **height**
int

The monitor height in pixels.

### **refreshRate**
real

The monitor refresh rate.

## Signals

### **monitorChanged**
Emitted when monitor configuration changes.
"""


def _build_type_page_mapping(docs_fixture_urls: dict[str, str]) -> dict[str, str]:
    """Extend the docs fixture URLs with synthetic type pages."""
    base = srv.BASE
    v = "v0.3.1"
    mapping = dict(docs_fixture_urls)
    mapping[f"{base}/docs/{v}/types/Quickshell/PanelWindow/"] = (
        f"<html><body><main>{_PANEL_WINDOW_PAGE}</main></body></html>"
    )
    mapping[f"{base}/docs/{v}/types/Quickshell.Hyprland/HyprlandMonitor/"] = (
        f"<html><body><main>{_HYPRLAND_MONITOR_PAGE}</main></body></html>"
    )
    # Guide pages for related-doc search
    for slug in ("qml-language", "introduction", "install-setup", "advanced", "size-position"):
        guide_url = f"{base}/docs/{v}/guide/{slug}/"
        body = f"<html><body><main><h1>{slug}</h1>"
        body += f"<p>Guide content about {slug}</p></main></body></html>"
        mapping[guide_url] = body
    # Qt module pages for Qt type fallback
    qt_htmls = [
        load_fixture("qt_qtquick_qmlmodule.html"),
        load_fixture("qt_qtquick_controls_qmlmodule.html"),
    ]
    mapping[f"{QT}/qtquick-qmlmodule.html"] = qt_htmls[0]
    mapping[f"{QT}/qtquick-controls-qmlmodule.html"] = qt_htmls[1]
    # Sibling module pages linked by the snapshots
    for html in qt_htmls:
        for stem in re.findall(r'href="([a-z0-9-]+-qmlmodule)\.html"', html):
            mapping.setdefault(f"{QT}/{stem}.html", "")
    return mapping


# ---------------------------------------------------------------------------
# Error categorization
# ---------------------------------------------------------------------------


def test_categorize_non_existent_property():
    category, entities = srv._categorize_error("Cannot assign to non-existent property 'foo'")
    assert category == "non_existent_property"
    assert entities["property"] == "foo"


def test_categorize_unknown_type():
    category, entities = srv._categorize_error("Type 'FooBar' is not accessible")
    assert category == "unknown_type"
    assert entities["type"] == "FooBar"


def test_categorize_missing_import():
    category, entities = srv._categorize_error("module 'Quickshell.Foo' is not installed")
    assert category == "missing_import"
    assert entities["module"] == "Quickshell.Foo"


def test_categorize_unknown_signal():
    category, entities = srv._categorize_error("Cannot connect to non-existent signal 'bar'")
    assert category == "unknown_signal"
    assert entities["signal"] == "bar"


def test_categorize_unknown_method():
    category, entities = srv._categorize_error("destroyAll is not a function")
    assert category == "unknown_method"
    assert entities["method"] == "destroyAll"


def test_categorize_type_mismatch():
    category, entities = srv._categorize_error("Invalid assignment: Cannot assign string to int")
    assert category == "type_mismatch"
    assert "expected" in entities


def test_categorize_component_not_found():
    category, entities = srv._categorize_error("Could not find or load the component MyWidget")
    assert category == "component_not_found"
    assert entities["type"] == "MyWidget"


def test_categorize_binding_error():
    category, entities = srv._categorize_error("Cannot apply binding to value property 'width'")
    assert category == "binding_error"
    assert entities["property"] == "width"


def test_categorize_unknown_error():
    category, entities = srv._categorize_error("Something went terribly wrong for no reason")
    assert category == "unknown"
    assert entities == {}


# ---------------------------------------------------------------------------
# Code context extraction
# ---------------------------------------------------------------------------


def test_extract_type_from_code():
    assert srv._extract_type_from_code("PanelWindow { foo: 123 }") == "PanelWindow"


def test_extract_type_from_indented_code():
    code = """\
Rectangle {
    PanelWindow {
        foo: 123
    }
}"""
    assert srv._extract_type_from_code(code) == "Rectangle"


def test_extract_type_returns_none_for_no_type():
    assert srv._extract_type_from_code("// just a comment") is None


# ---------------------------------------------------------------------------
# Non-existent property diagnosis
# ---------------------------------------------------------------------------


def test_non_existent_property_on_known_type(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    result = srv._explain_error(
        error="Cannot assign to non-existent property 'foo'",
        code="PanelWindow {\n    foo: 123\n}",
        version="v0.3.1",
    )

    assert result["error_category"] == "non_existent_property"
    assert result["api_exists"] is False
    assert result["relevant_type"]["type_name"] == "PanelWindow"
    assert result["relevant_type"]["namespace"] == "Quickshell"
    assert result["confidence"] == "high"
    assert "'foo'" in result["fix"]
    assert result["documentation"], "should have related docs"


def test_non_existent_property_suggests_alternative(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    # "exclusionMode" is close to "exclusionMod" (typo)
    result = srv._explain_error(
        error="Cannot assign to non-existent property 'exclusionMod'",
        code="PanelWindow {\n    exclusionMod: 123\n}",
        version="v0.3.1",
    )

    assert result["error_category"] == "non_existent_property"
    assert result["api_exists"] is False
    assert result["correct_api"] is not None
    assert "exclusionMode" in result["fix"]


# ---------------------------------------------------------------------------
# Unknown type diagnosis
# ---------------------------------------------------------------------------


def test_unknown_type_suggests_similar(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    result = srv._explain_error(
        error="Type 'PanelWindov' is not accessible",
        version="v0.3.1",
    )

    assert result["error_category"] == "unknown_type"
    assert result["relevant_type"] is None
    assert result["correct_api"] is not None
    assert result["confidence"] == "medium"


def test_unknown_type_no_similar_found(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    result = srv._explain_error(
        error="Type 'ZzzQqq' is not accessible",
        version="v0.3.1",
    )

    assert result["error_category"] == "unknown_type"
    assert result["correct_api"] is None
    assert result["confidence"] == "medium"


# ---------------------------------------------------------------------------
# Unknown signal diagnosis
# ---------------------------------------------------------------------------


def test_unknown_signal_on_known_type(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    result = srv._explain_error(
        error="Cannot connect to non-existent signal 'clickled'",
        code="PanelWindow {\n    onClicked: console.log('hi')\n}",
        version="v0.3.1",
    )

    assert result["error_category"] == "unknown_signal"
    assert result["api_exists"] is False
    assert result["relevant_type"]["type_name"] == "PanelWindow"
    assert "clickled" in result["fix"]


# ---------------------------------------------------------------------------
# Unknown method diagnosis
# ---------------------------------------------------------------------------


def test_unknown_method_on_known_type(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    result = srv._explain_error(
        error="destroyAll is not a function",
        code="PanelWindow {\n    Component.onCompleted: destroyAll()\n}",
        version="v0.3.1",
    )

    assert result["error_category"] == "unknown_method"
    assert result["api_exists"] is False
    assert result["relevant_type"]["type_name"] == "PanelWindow"


def test_existing_method_detected(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    result = srv._explain_error(
        error="setVisible is not a function",
        code="PanelWindow {\n    Component.onCompleted: setVisible(true)\n}",
        version="v0.3.1",
    )

    assert result["error_category"] == "unknown_method"
    assert result["api_exists"] is True


# ---------------------------------------------------------------------------
# Missing import diagnosis
# ---------------------------------------------------------------------------


def test_missing_import(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    result = srv._explain_error(
        error="namespace 'Quickshell.Services.Pipewire' is not installed",
        version="v0.3.1",
    )

    assert result["error_category"] == "missing_import"
    assert result["confidence"] == "high"
    assert "Quickshell.Services.Pipewire" in result["fix"]


# ---------------------------------------------------------------------------
# Component not found diagnosis
# ---------------------------------------------------------------------------


def test_component_not_found(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    result = srv._explain_error(
        error="Could not find or load the component MyCustomWidget",
        version="v0.3.1",
    )

    assert result["error_category"] == "component_not_found"
    assert result["relevant_type"] is None


# ---------------------------------------------------------------------------
# Binding error diagnosis
# ---------------------------------------------------------------------------


def test_binding_error(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    result = srv._explain_error(
        error="Cannot apply binding to value property 'width'",
        version="v0.3.1",
    )

    assert result["error_category"] == "binding_error"
    assert "width" in result["fix"]


# ---------------------------------------------------------------------------
# Type mismatch diagnosis
# ---------------------------------------------------------------------------


def test_type_mismatch(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    result = srv._explain_error(
        error="Invalid assignment: Cannot assign string to int",
        version="v0.3.1",
    )

    assert result["error_category"] == "type_mismatch"
    assert "int" in result["fix"]


# ---------------------------------------------------------------------------
# Uncertain diagnosis
# ---------------------------------------------------------------------------


def test_uncertain_diagnosis(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    result = srv._explain_error(
        error="Quantum entanglement detected in QML engine",
        version="v0.3.1",
    )

    assert result["error_category"] == "unknown"
    assert result["confidence"] == "low"


# ---------------------------------------------------------------------------
# Unverified target (no type docs available): fix must not be empty
# ---------------------------------------------------------------------------


def test_non_existent_property_no_type_provides_fix(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    result = srv._explain_error(
        error="Cannot assign to non-existent property 'foo'",
        version="v0.3.1",
    )

    assert result["error_category"] == "non_existent_property"
    assert result["fix"], "fix must not be empty when type docs are unavailable"
    assert "foo" in result["fix"]
    assert result["confidence"] != "high"


def test_unknown_signal_no_type_provides_fix(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    result = srv._explain_error(
        error="Cannot connect to non-existent signal 'clickled'",
        version="v0.3.1",
    )

    assert result["error_category"] == "unknown_signal"
    assert result["fix"], "fix must not be empty when type docs are unavailable"
    assert "clickled" in result["fix"]
    assert result["confidence"] != "high"


def test_unknown_method_no_type_provides_fix(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    result = srv._explain_error(
        error="destroyAll is not a function",
        version="v0.3.1",
    )

    assert result["error_category"] == "unknown_method"
    assert result["fix"], "fix must not be empty when type docs are unavailable"
    assert "destroyAll" in result["fix"]
    assert result["confidence"] != "high"


# ---------------------------------------------------------------------------
# Component parameter override
# ---------------------------------------------------------------------------


def test_component_param_supplies_type(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    result = srv._explain_error(
        error="Cannot assign to non-existent property 'volumeLevel'",
        component="HyprlandMonitor",
        version="v0.3.1",
    )

    assert result["relevant_type"]["type_name"] == "HyprlandMonitor"
    assert result["relevant_type"]["namespace"] == "Quickshell.Hyprland"


# ---------------------------------------------------------------------------
# Code context extraction drives type lookup
# ---------------------------------------------------------------------------


def test_code_context_extracts_type(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    result = srv._explain_error(
        error="Cannot assign to non-existent property 'foo'",
        code="HyprlandMonitor {\n    foo: 42\n}",
        version="v0.3.1",
    )

    assert result["relevant_type"]["type_name"] == "HyprlandMonitor"
    assert result["relevant_type"]["namespace"] == "Quickshell.Hyprland"


# ---------------------------------------------------------------------------
# Wrapper records tool call stats
# ---------------------------------------------------------------------------


def test_wrapper_records_stats(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    before = dict(srv._TOOL_CALLS)
    srv.quickshell_explain_error(
        error="Cannot assign to non-existent property 'foo'",
        code="PanelWindow { foo: 123 }",
    )
    expected_count = before.get("quickshell_explain_error", 0) + 1
    assert srv._TOOL_CALLS["quickshell_explain_error"] == expected_count


# ---------------------------------------------------------------------------
# Related documentation search
# ---------------------------------------------------------------------------


def test_related_docs_in_result(monkeypatch, docs_fixture_urls):
    mapping = _build_type_page_mapping(docs_fixture_urls)
    mapping[srv.BASE + "/about/"] = load_fixture("about.html")

    def fake_fetch(url: str) -> str:
        for prefix, html in mapping.items():
            if url.startswith(prefix):
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    result = srv._explain_error(
        error="Cannot assign to non-existent property 'foo'",
        code="PanelWindow { foo: 123 }",
        version="v0.3.1",
    )

    assert isinstance(result["documentation"], list)
    for doc in result["documentation"]:
        assert "title" in doc
        assert "url" in doc
