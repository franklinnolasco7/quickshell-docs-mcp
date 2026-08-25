"""Index building and search behavior, driven by the real guide-page fixture."""

from __future__ import annotations

import quickshell_docs_mcp.server as srv
from quickshell_docs_mcp import utils  # noqa: E402


def test_build_index_from_guide_page(mock_fetch, docs_fixture_urls):
    mock_fetch(docs_fixture_urls)
    index = srv._build_index("v0.3.1")
    types = index["types_by_namespace"]

    assert "Quickshell" in types
    assert "PanelWindow" in types["Quickshell"]
    assert "Quickshell.Hyprland" in types
    assert "HyprlandMonitor" in types["Quickshell.Hyprland"]
    assert "qml-language" in index["guide_pages"]
    # Only links for the requested version are indexed.
    for ns, ns_types in types.items():
        assert all("/" not in t and "." not in t for t in ns_types), ns


def test_index_falls_back_to_version_root(monkeypatch):
    """If the guide index page 404s, the version root page is used instead."""
    root_html = (
        '<nav><a href="/docs/v0.3.1/types/Quickshell/PanelWindow">PW</a>'
        '<a href="/docs/v0.3.1/guide/introduction">intro</a></nav>'
    )

    def fake_fetch(url: str) -> str:
        if url.endswith("/docs/v0.3.1/guide/"):
            from conftest import http_404

            raise http_404(url)
        return root_html

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)
    index = srv._build_index("v0.3.1")
    assert index["types_by_namespace"] == {"Quickshell": ["PanelWindow"]}
    assert index["guide_pages"] == ["introduction"]


def test_search_separates_namespaces_from_type_flood(mock_fetch, docs_fixture_urls):
    mock_fetch(docs_fixture_urls)
    v = srv._resolve_version("latest")
    index = srv._build_index(v)

    q = "hyprland"
    namespace_matches = sorted(ns for ns in index["types_by_namespace"] if q in ns.lower())
    type_matches = [
        {"namespace": ns, "type_name": t}
        for ns, types in index["types_by_namespace"].items()
        for t in types
        if q in t.lower()
    ]

    assert namespace_matches == ["Quickshell.Hyprland"]
    assert {m["type_name"] for m in type_matches} >= {
        "Hyprland",
        "HyprlandMonitor",
        "HyprlandWindow",
    }


def test_search_monitor_shape(mock_fetch, docs_fixture_urls):
    mock_fetch(docs_fixture_urls)
    v = srv._resolve_version("latest")
    index = srv._build_index(v)

    q = "monitor"
    type_matches = [
        {"namespace": ns, "type_name": t}
        for ns, types in index["types_by_namespace"].items()
        for t in types
        if q in t.lower()
    ]
    names = {(m["namespace"], m["type_name"]) for m in type_matches}
    assert ("Quickshell.Hyprland", "HyprlandMonitor") in names
    assert ("Quickshell.I3", "I3Monitor") in names


def test_list_types_filter_and_suggestion_data(mock_fetch, docs_fixture_urls):
    mock_fetch(docs_fixture_urls)
    index = srv._build_index("v0.3.1")
    types_by_ns = index["types_by_namespace"]

    exact = {ns: t for ns, t in types_by_ns.items() if ns.lower() == "quickshell.hyprland"}
    assert list(exact) == ["Quickshell.Hyprland"]

    close = [ns for ns in types_by_ns if "hypr".lower() in ns.lower()]
    assert close == ["Quickshell.Hyprland"]
