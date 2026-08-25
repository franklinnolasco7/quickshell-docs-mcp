"""Guide-page full-text content search."""

from __future__ import annotations

from conftest import http_404, load_fixture

import quickshell_docs_mcp.server as srv
from quickshell_docs_mcp import utils  # noqa: E402


def make_guide_fetch(monkeypatch, docs_fixture_urls, extra_body: str = ""):
    """Serve the discovery/index fixtures plus synthetic guide-page bodies.
    Any guide page other than qml-language gets `extra_body` as its content,
    so tests control what the content index contains."""

    def fake_fetch(url: str) -> str:
        if url == f"{srv.BASE}/docs/v0.3.1/guide/qml-language/":
            return load_fixture("qml_language.html")
        if url in docs_fixture_urls:  # exact: /about/ and the guide index page
            return docs_fixture_urls[url]
        if "/docs/v0.3.1/guide/" in url:
            return f"<html><body><main>{extra_body}</main></body></html>"
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)


def test_content_search_finds_prose(monkeypatch, docs_fixture_urls):
    make_guide_fetch(
        monkeypatch, docs_fixture_urls, "You can anchor panels using the anchors property."
    )
    matches = srv._search_guide_content("anchors", "v0.3.1")
    assert matches
    assert all("anchors" in m["snippet"].lower() for m in matches)
    assert {m["slug"] for m in matches} >= {"qml-language"}


def test_content_search_sorted_by_occurrences(monkeypatch, docs_fixture_urls):
    make_guide_fetch(
        monkeypatch,
        docs_fixture_urls,
        "ipc ipc ipc and more ipc",
    )
    matches = srv._search_guide_content("ipc", "v0.3.1")
    assert matches
    occurrences = [m["occurrences"] for m in matches]
    assert occurrences == sorted(occurrences, reverse=True)
    top = next(m for m in matches if m["slug"] != "qml-language")
    assert top["occurrences"] >= 4


def test_content_search_no_match_returns_empty(monkeypatch, docs_fixture_urls):
    make_guide_fetch(monkeypatch, docs_fixture_urls, "nothing relevant here")
    assert srv._search_guide_content("zzz-no-such-term", "v0.3.1") == []


def test_search_tool_include_content_flag(monkeypatch, docs_fixture_urls):
    make_guide_fetch(monkeypatch, docs_fixture_urls, "anchors are set via anchors {}")
    without = srv.quickshell_search("anchors")
    assert without["content_matches"] == []
    assert "include_content" in without["note"]

    with_content = srv.quickshell_search("anchors", include_content=True)
    assert with_content["content_matches"]
    expected_keys = {"slug", "url", "occurrences", "snippet"}
    assert all(set(m) == expected_keys for m in with_content["content_matches"])


def test_content_index_is_cached(monkeypatch, docs_fixture_urls):
    count = {"n": 0}

    def counting(url: str) -> str:
        count["n"] += 1
        if url == f"{srv.BASE}/docs/v0.3.1/guide/qml-language/":
            return load_fixture("qml_language.html")
        if url in docs_fixture_urls:
            return docs_fixture_urls[url]
        if "/docs/v0.3.1/guide/" in url:
            return "<html><body><main>filler text</main></body></html>"
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", counting)
    srv._guide_content_index("v0.3.1")
    first_build = count["n"]
    srv._guide_content_index("v0.3.1")  # second call must be fully cached
    assert count["n"] == first_build


def test_stats_counters_track_cache_and_network(monkeypatch):
    import httpx

    def ok_get(url: str) -> httpx.Response:
        return httpx.Response(200, text="page body", request=httpx.Request("GET", url))

    monkeypatch.setattr(utils._client, "get", ok_get)
    before_hits = srv._FETCH_STATS["cache_hits"]
    before_fetches = srv._FETCH_STATS["network_fetches"]
    srv._fetch_raw("https://example.com/once")
    srv._fetch_raw("https://example.com/once")  # cached now
    stats = srv.quickshell_stats()
    assert stats["network_fetches"] == before_fetches + 1
    assert stats["cache_hits"] == before_hits + 1


def test_type_page_deep_search_skips_dead_pages_and_caches(monkeypatch):
    """include_type_pages deep-search: every indexed type page gets fetched
    once (concurrently), dead pages are skipped, results rank by occurrences,
    and the built index is fully cached."""
    from quickshell_docs_mcp.sources import docs as docs_src

    calls: list[str] = []

    def fake_build(version: str) -> dict:
        return {
            "types_by_namespace": {
                "Quickshell": ["PanelWindow", "Ghost"],
                "Quickshell.Hyprland": ["HyprlandMonitor"],
            },
            "guide_pages": [],
        }

    def fake_fetch(url: str) -> str:
        calls.append(url)
        panel_window = f"{srv.BASE}/docs/v0.3.1/types/Quickshell/PanelWindow/"
        ghost = f"{srv.BASE}/docs/v0.3.1/types/Quickshell/Ghost/"
        hyprland_monitor = f"{srv.BASE}/docs/v0.3.1/types/Quickshell.Hyprland/HyprlandMonitor/"
        pages = {
            panel_window: "# PanelWindow\nanchors top left",
            ghost: "nothing relevant here",
            hyprland_monitor: "anchors active workspace anchors",
        }
        if url not in pages:
            raise http_404(url)
        return pages[url]

    monkeypatch.setattr(docs_src, "_build_index", fake_build)
    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    matches = srv._search_type_content("anchors", "v0.3.1")
    assert [match["type_name"] for match in matches] == ["HyprlandMonitor", "PanelWindow"]
    assert {match["namespace"] for match in matches} == {"Quickshell", "Quickshell.Hyprland"}
    assert all(match["occurrences"] >= 1 for match in matches)
    assert len(calls) == 3  # every indexed page attempted exactly once

    srv._search_type_content("anchors", "v0.3.1")  # second call must be cached
    assert len(calls) == 3


def test_search_wrapper_notes_and_type_page_flag(mock_fetch, docs_fixture_urls):
    out = srv.quickshell_search("panel")
    assert "include_content=True" in out["note"]
    assert "include_type_pages=True" in out["note"]
    assert out["type_page_matches"] == []
