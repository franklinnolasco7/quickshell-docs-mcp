# ruff: noqa: E501
"""Explain error: grounded diagnosis of QML errors."""

from __future__ import annotations

import quickshell_docs_mcp.server as srv


def _qs_index():
    return {
        "types_by_namespace": {
            "Quickshell": ["PanelWindow", "FloatingWindow"],
            "Quickshell.Hyprland": ["HyprlandMonitor", "HyprlandWorkspace"],
            "Quickshell.Services.Pipewire": ["PwNode"],
        },
        "guide_pages": ["qml-language", "introduction"],
    }


def _qt_index():
    return {
        "modules": {
            "qtquick": ["Rectangle", "Item", "Text"],
            "qtquick-controls": ["AbstractButton"],
        },
        "pages": {"qtquick": "https://doc.qt.io/qt-6/qtquick-qmlmodule.html"},
    }


def test_extract_type_from_code_simple():
    assert srv._extract_type_from_code("PanelWindow { foo: 123 }", None) == "PanelWindow"
    assert srv._extract_type_from_code("  Rectangle {\n width: 10 }", None) == "Rectangle"
    assert srv._extract_type_from_code(None, "HyprlandMonitor") == "HyprlandMonitor"
    assert srv._extract_type_from_code("PanelWindow {", "CustomType") == "CustomType"


def test_extract_quoted():
    assert srv._extract_quoted("Cannot assign to non-existent property 'foo'") == ["foo"]
    assert srv._extract_quoted('Unknown type "Bar"') == ["Bar"]
    assert srv._extract_quoted("no quotes") == []


def test_classify_error_categories():
    assert (
        srv._classify_error("Cannot assign to non-existent property 'foo'")[0]
        == "non-existent property"
    )
    assert srv._classify_error("Unknown type 'FooBar'")[0] == "unknown type"
    assert srv._classify_error('module "Quickshell.Foo" is not installed')[0] == "missing import"
    assert srv._classify_error("is not a signal")[0] == "unknown signal"
    assert srv._classify_error("is not a function")[0] == "unknown method"
    assert srv._classify_error("Cannot assign string to int")[0] == "type mismatch"
    assert srv._classify_error("Binding loop detected")[0] == "binding error"
    assert srv._classify_error("Component not found")[0] == "component not found"
    assert srv._classify_error("something completely weird")[0] == "unknown"


def test_non_existent_property_with_code(monkeypatch, docs_fixture_urls):
    # mock index and qt
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    # mock type page fetch — PanelWindow has 'anchors' but not 'foo'
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._fetch_page_markdown",
        lambda url: "PanelWindow type. Properties: anchors, width, height, visible",
    )
    # avoid impl search hitting network
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._try_impl_examples", lambda q: [])

    res = srv._explain_error(
        "Cannot assign to non-existent property 'foo'",
        code="PanelWindow { foo: 123 }",
        version="v0.3.1",
    )
    assert res["error_type"] == "non-existent property"
    assert res["relevant_api"] == "PanelWindow.foo"
    assert res["exists"] is False
    assert "foo" in res["meaning"]
    assert "PanelWindow" in res["fix"]
    assert res["confidence"] in ("high", "medium")
    assert any("PanelWindow" in d["url"] for d in res["documentation"])


def test_non_existent_property_verifies_exists_when_found(monkeypatch):
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._fetch_page_markdown",
        lambda url: "Properties: foo, anchors",
    )
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._try_impl_examples", lambda q: [])
    res = srv._explain_error(
        "Cannot assign to non-existent property 'foo'", code="PanelWindow { foo: 123 }"
    )
    # if property found, exists True and message notes availability
    assert res["exists"] is True
    assert "available" in res["meaning"].lower() or "found" in res["meaning"].lower()


def test_unknown_type_quickshell_with_suggestion(monkeypatch):
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    res = srv._explain_error("Unknown type 'PanelWindw'")
    assert res["error_type"] == "unknown type"
    assert res["exists"] is False
    assert res["alternative"] == "PanelWindow"
    assert any("PanelWindow" in d["url"] for d in res["documentation"])


def test_unknown_type_qt(monkeypatch):
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    res = srv._explain_error("Unknown type 'Rectangel'")
    assert res["error_type"] == "unknown type"
    # should suggest Rectangle from Qt
    assert res["alternative"] in ("Rectangle", "PanelWindow", None)
    # Rectangle is Qt, so at least one doc URL should be Qt
    if res["alternative"] == "Rectangle":
        assert any("doc.qt.io" in d["url"] or "Rectangle" in d["url"] for d in res["documentation"])


def test_missing_import_known_namespace(monkeypatch):
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    res = srv._explain_error('module "Quickshell.Hyprland" is not installed')
    assert res["error_type"] == "missing import"
    assert res["exists"] is True


def test_missing_import_unknown_with_suggestion(monkeypatch):
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    res = srv._explain_error('module "Quickshell.Hypr" is not installed')
    assert res["error_type"] == "missing import"
    assert res["exists"] is False
    assert res["alternative"] == "Quickshell.Hyprland"


def test_unknown_signal_with_component(monkeypatch):
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._fetch_page_markdown",
        lambda url: "Signals: onClicked, onChanged",
    )
    res = srv._explain_error("is not a signal 'onFooBar'", component="PanelWindow")
    assert res["error_type"] == "unknown signal"
    assert res["exists"] is False


def test_unknown_method(monkeypatch):
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._fetch_page_markdown",
        lambda url: "Methods: doThing(), update()",
    )
    res = srv._explain_error("is not a function 'doThin'", component="PanelWindow")
    assert res["error_type"] == "unknown method"


def test_type_mismatch(monkeypatch):
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    res = srv._explain_error("Cannot assign string to int", code="Item { width: 'foo' }")
    assert res["error_type"] == "type mismatch"
    assert "Cannot assign" in res["likely_cause"]


def test_binding_error(monkeypatch):
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    # mock guide search to return something
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.docs._search_guide_content",
        lambda q, v, limit=2, refresh=False: [
            {"url": "https://example.com/guide", "snippet": "binding loop"}
        ],
    )
    res = srv._explain_error("Binding loop detected for property 'width'")
    assert res["error_type"] == "binding error"
    assert "loop" in res["meaning"].lower()


def test_component_not_found(monkeypatch):
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    res = srv._explain_error("Component 'MyComp' not found")
    assert res["error_type"] == "component not found"
    assert res["exists"] is False


def test_uncertain_error(monkeypatch):
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    res = srv._explain_error("something completely weird happened")
    assert res["error_type"] == "unknown"
    assert res["confidence"] == "low"
    assert res["exists"] is None
    assert (
        "uncertain" in res["meaning"].lower() or "could not be classified" in res["meaning"].lower()
    )


def test_no_hallucinated_api_on_unknown(monkeypatch):
    """Never invent an alternative that is not in the index."""
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    res = srv._explain_error("Unknown type 'ZzzQqqXxx'")
    # alternative must be None or one of the known types
    known = {n for names in _qs_index()["types_by_namespace"].values() for n in names} | {
        n for names in _qt_index()["modules"].values() for n in names
    }
    if res["alternative"] is not None:
        assert res["alternative"] in known


def test_tool_wrapper_records_stats(monkeypatch):
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._fetch_page_markdown",
        lambda url: "PanelWindow docs",
    )
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._try_impl_examples", lambda q: [])
    out = srv.quickshell_explain_error(
        error="Cannot assign to non-existent property 'foo'", code="PanelWindow { foo: 1 }"
    )
    assert out["error_type"] == "non-existent property"
    assert srv._TOOL_CALLS.get("quickshell_explain_error", 0) >= 1


def test_version_notes_and_code_context(monkeypatch):
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._resolve_version", lambda v: "v0.3.1")
    res = srv._explain_error(
        "Cannot assign to non-existent property 'foo'",
        code="PanelWindow { foo: 1 }",
        filename="shell.qml",
        line_number=10,
    )
    assert "v0.3.1" in (res["version_notes"] or "")
    assert res["code_context"]["filename"] == "shell.qml"
    assert res["code_context"]["line_number"] == 10


def test_empty_error():
    res = srv._explain_error("")
    assert res["confidence"] == "low"
    assert res["error_type"] == "unknown"


def test_unquoted_unknown_type_without_code(monkeypatch):
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    res = srv._explain_error("Foo is not a type")
    assert res["error_type"] == "unknown type"
    assert res["relevant_api"] == "Foo"
    # should attempt search and provide low/high confidence, not crash
    assert res["confidence"] in ("high", "medium", "low")


def test_reference_error_without_code(monkeypatch):
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    res = srv._explain_error("ReferenceError: MyType is not defined")
    assert res["error_type"] == "unknown type"
    assert res["relevant_api"] == "MyType"


def test_full_namespace_preserved_for_deep_type(monkeypatch):
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    # typo should suggest PwNode and docs should point to full namespace
    res = srv._explain_error("Unknown type 'PwNod'")
    assert res["alternative"] == "PwNode"
    assert any("Quickshell.Services.Pipewire" in d["url"] for d in res["documentation"])
    # when type exists but missing import, fix must preserve full 3-segment ns
    res2 = srv._explain_error("Unknown type 'PwNode'")
    assert res2["exists"] is True
    assert "Quickshell.Services.Pipewire" in res2["fix"]


def test_exact_equality_no_case_insensitive_false_positive(monkeypatch):
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    # lower-case should not be found, but should suggest correct casing
    res = srv._explain_error("Unknown type 'panelwindow'")
    assert res["exists"] is False
    assert res["alternative"] == "PanelWindow"


def test_index_unavailable_graceful(monkeypatch):
    def fail_qs(v):
        raise RuntimeError("index fail")

    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", fail_qs)
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    res = srv._explain_error("Unknown type 'Foo'")
    # should not abort, should be low confidence with Qt fallback
    assert res["confidence"] == "low" or res["exists"] is None or res["exists"] is False


def test_qt_property_verified(monkeypatch):
    monkeypatch.setattr("quickshell_docs_mcp.sources.errors._build_index", lambda v: _qs_index())
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._build_qt_index", lambda **_: _qt_index()
    )
    monkeypatch.setattr(
        "quickshell_docs_mcp.sources.errors._fetch_qt_page_markdown",
        lambda url: "Rectangle props: width, height",
    )
    res = srv._explain_error(
        "Cannot assign to non-existent property 'width'", code="Rectangle { width: 1 }"
    )
    assert res["exists"] is True
    res2 = srv._explain_error(
        "Cannot assign to non-existent property 'foo'", code="Rectangle { foo: 1 }"
    )
    assert res2["exists"] is False
