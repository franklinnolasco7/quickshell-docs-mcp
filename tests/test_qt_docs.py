"""Qt (doc.qt.io) index and type-page fetching, driven by real Qt module
page snapshots."""

from __future__ import annotations

import pytest

import quickshell_docs_mcp.server as srv
from quickshell_docs_mcp import utils  # noqa: E402

QT = srv.QT_DOCS_BASE

# The QtQuick module page links every sibling qmlmodule page, so the crawl
# visits them all. The two pages under test get their real snapshots; the
# remaining siblings serve as empty pages (no type links to pick up).
_SIBLINGS_WITHOUT_SNAPSHOTS = (
    "qtquick-effects-qmlmodule",
    "qtquick-layouts-qmlmodule",
    "qtquick-localstorage-qmlmodule",
    "qtquick-particles-qmlmodule",
    "qtquick-shapes-qmlmodule",
    "qtquick-vectorimage-qmlmodule",
    "qttest-qmlmodule",
)


def _install(monkeypatch, http_404_for: str | None = None):
    import re

    from conftest import load_fixture

    mapping = {
        f"{QT}/qtquick-qmlmodule.html": load_fixture("qt_qtquick_qmlmodule.html"),
        f"{QT}/qtquick-controls-qmlmodule.html": load_fixture("qt_qtquick_controls_qmlmodule.html"),
        f"{QT}/qml-qtquick-rectangle.html": load_fixture("qt_qml_qtquick_rectangle.html"),
        f"{QT}/qml-color.html": "<html><body>color value type</body></html>",
    }
    # Sibling module pages linked by the snapshots (e.g. qtquick-templates
    # from the Controls page) get empty bodies; they contribute no types.
    for html in list(mapping.values()):
        for stem in re.findall(r"href=\"([a-z0-9-]+-qmlmodule)\.html\"", html):
            mapping.setdefault(f"{QT}/{stem}.html", "")
    for stem in _SIBLINGS_WITHOUT_SNAPSHOTS:
        mapping[f"{QT}/{stem}.html"] = ""

    def fake_fetch(url: str) -> str:
        if http_404_for is not None and url == http_404_for:
            from conftest import http_404

            raise http_404(url)
        if url not in mapping:
            raise AssertionError(f"unexpected fetch in test: {url}")
        return mapping[url]

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)


def test_qt_index_discovers_sibling_modules_and_buckets_types(monkeypatch):
    _install(monkeypatch)
    index = srv._build_qt_index()
    modules = index["modules"]

    assert "Rectangle" in modules["qtquick"]
    assert "Item" in modules["qtquick"]
    assert "AbstractButton" in modules["qtquick-controls"]
    # Prefix-less slugs (color, font, vector3d...) land in the value-types
    # bucket; link text keeps Qt's lowercase spelling for value types.
    assert "color" in modules["value-types"]
    # qtqml types are linked from the QtQuick page without a module page of
    # their own; they still get a bucket.
    assert "Component" in modules["qtqml"]
    assert index["pages"]["qtquick"].endswith("/qt-6/qtquick-qmlmodule.html")


def test_list_qt_tools_shape_and_filter(monkeypatch):
    _install(monkeypatch)
    out = srv.quickshell_list_qt_types()
    assert set(out["modules"]) >= {"qtquick", "qtquick-controls", "value-types"}
    assert out["source"] == f"{QT}/qtquick-qmlmodule.html"

    filtered = srv.quickshell_list_qt_types(module="QtQuick.Controls")
    assert list(filtered["modules"]) == ["qtquick-controls"]

    with pytest.raises(ValueError, match="Known modules"):
        srv.quickshell_list_qt_types(module="bogus")


def test_get_qt_type_fetches_exact_url(monkeypatch):
    _install(monkeypatch)
    md = srv.quickshell_get_qt_type("Rectangle")
    assert f"{QT}/qml-qtquick-rectangle.html" in md

    vt = srv.quickshell_get_qt_type("color")
    assert f"{QT}/qml-color.html" in vt


def test_resolve_qt_slug_ambiguous_across_modules(monkeypatch):
    from quickshell_docs_mcp.sources import qt_docs

    monkeypatch.setattr(
        qt_docs,
        "_build_qt_index",
        lambda refresh=False, qt_version=None: {
            "modules": {"mod-a": ["Foo"], "mod-b": ["Foo"]},
            "pages": {},
        },
    )
    with pytest.raises(ValueError, match="ambiguous"):
        srv._resolve_qt_slug("Foo", None)


def test_get_qt_type_suggestions_on_unknown_name(monkeypatch):
    _install(monkeypatch)
    with pytest.raises(ValueError, match="Did you mean"):
        srv.quickshell_get_qt_type("Rectangl")
    # Module scoping is honored in the suggestion message too.
    with pytest.raises(ValueError, match="No Qt type 'Rectangl' in module"):
        srv.quickshell_get_qt_type("Rectangl", module="qtquick-controls")


def test_get_qt_type_404_after_index_hit_is_friendly(monkeypatch):
    _install(monkeypatch, http_404_for=f"{QT}/qml-qtquick-rectangle.html")
    with pytest.raises(ValueError, match="404"):
        srv.quickshell_get_qt_type("Rectangle")


def test_qt_extraction_keeps_sidebar_classed_content():
    """doc.qt.io hosts page content in <article class="b-sidebar__content...">;
    the generic quickshell.org strip rule ([class*=sidebar]) must not eat it."""
    from conftest import load_fixture

    html = load_fixture("qt_qml_qtquick_rectangle.html")
    md = srv._extract_main_content(html, strip=srv._QT_STRIP_SELECTORS)
    assert "Rectangle" in md
    assert "border" in md.lower()
    assert len(md) > 5000


def test_qt_version_pins_base_path(monkeypatch):
    import re

    from conftest import load_fixture

    base68 = "https://doc.qt.io/qt-6.8"
    html = load_fixture("qt_qtquick_qmlmodule.html")
    mapping = {f"{base68}/qtquick-qmlmodule.html": html}
    for stem in set(re.findall(r"href=\"([a-z0-9-]+-qmlmodule)\.html\"", html)) - {
        "qtquick-qmlmodule"
    }:
        mapping[f"{base68}/{stem}.html"] = ""
    rectangle_url = f"{base68}/qml-qtquick-rectangle.html"
    mapping[rectangle_url] = "<html><body><h1>Rectangle</h1></body></html>"

    def fake_fetch(url: str) -> str:
        if url not in mapping:
            raise AssertionError(f"unexpected fetch in test: {url}")
        return mapping[url]

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    md = srv.quickshell_get_qt_type("Rectangle", qt_version="6.8")
    assert f"{base68}/qml-qtquick-rectangle.html" in md
    listing = srv.quickshell_list_qt_types(qt_version="6.8")
    assert listing["source"] == f"{base68}/qtquick-qmlmodule.html"

    with pytest.raises(ValueError, match="Invalid Qt version"):
        srv.quickshell_get_qt_type("Rectangle", qt_version="nine")
