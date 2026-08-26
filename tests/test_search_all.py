"""Unified cross-source search (quickshell_search_all), driven entirely by
the committed per-source fixtures: docs discovery pages, Qt module snapshots,
implementation tree JSONs, and the examples repo listing."""

from __future__ import annotations

import re

from conftest import http_404, load_fixture

import quickshell_docs_mcp.server as srv
from quickshell_docs_mcp import utils  # noqa: E402

QT = srv.QT_DOCS_BASE
_CAEL_TREE = f"{srv._GITHUB_API}/repos/caelestia-dots/shell/git/trees/main?recursive=1"


def _install(monkeypatch, docs_fixture_urls, extra_404=None, guide_bodies=None):
    """Wire every source to its committed snapshot. guide_bodies maps guide
    slugs to synthetic bodies layered over the discovery fixtures; unlisted
    guide pages get filler."""
    extra_404 = extra_404 or set()
    guide_bodies = guide_bodies or {}

    qt_htmls = [
        load_fixture("qt_qtquick_qmlmodule.html"),
        load_fixture("qt_qtquick_controls_qmlmodule.html"),
    ]
    mapping = {
        f"{QT}/qtquick-qmlmodule.html": qt_htmls[0],
        f"{QT}/qtquick-controls-qmlmodule.html": qt_htmls[1],
        f"{srv._GITHUB_API}/repos/caelestia-dots/shell": load_fixture(
            "impl_caelestia_repo_info.json"
        ),
        _CAEL_TREE: load_fixture("impl_caelestia_tree.json"),
        f"{srv._GITHUB_API}/repos/noctalia-dev/noctalia/git/trees/legacy-v4?recursive=1": (
            load_fixture("impl_noctalia_tree.json")
        ),
        srv.EXAMPLES_REPO_API: load_fixture("examples_repo_info.json"),
        f"{srv.EXAMPLES_REPO_API}/contents?ref=master": load_fixture("examples_contents_root.json"),
    }
    # Sibling module pages linked by the snapshots contribute no types.
    for html in qt_htmls:
        for stem in re.findall(r"href=\"([a-z0-9-]+-qmlmodule)\.html\"", html):
            mapping.setdefault(f"{QT}/{stem}.html", "")

    def fake_fetch(url: str) -> str:
        if url in extra_404:
            raise http_404(url)
        if url == f"{srv.BASE}/docs/v0.3.1/guide/qml-language/":
            return load_fixture("qml_language.html")
        if url in docs_fixture_urls:
            return docs_fixture_urls[url]
        if "/docs/v0.3.1/guide/" in url:
            slug = url.rstrip("/").rsplit("/", 1)[-1]
            return f"<html><body><main>{guide_bodies.get(slug, 'filler text')}</main></body></html>"
        if url not in mapping:
            raise AssertionError(f"unexpected fetch in test: {url}")
        return mapping[url]

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)


def test_api_query_ranks_exact_type_first(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._search_everything("PanelWindow", "v0.3.1")

    assert out["section_order"][0] == "quickshell_types"
    top = out["results"]["quickshell_types"][0]
    assert top["type_name"] == "PanelWindow"
    assert top["kind"] == "api reference"
    assert top["relevance"] == 95
    assert top["match_reason"] == "exact type name"
    assert top["url"].endswith("/types/Quickshell/PanelWindow/")
    # Shell repos may mention panelwindow in file paths, but an API question
    # keeps exact type matches on top.
    for key, group in out["results"].items():
        if key.endswith("_implementations"):
            assert group[0]["relevance"] < top["relevance"]
    assert "quickshell_get_type" in out["note"]


def test_feature_query_ranks_implementations_first(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._search_everything("volume OSD", "v0.3.1")

    impl_sections = [key for key in out["section_order"] if key.endswith("_implementations")]
    assert len(impl_sections) == 2  # both shells carry osd/audio paths
    # Feature phrasing puts working code ahead of reference material.
    assert out["section_order"].index(impl_sections[0]) < out["section_order"].index(
        "official_examples"
    )
    for section in impl_sections:
        for entry in out["results"][section]:
            assert entry["kind"] == "real-world implementation"
            assert entry["url"].startswith("https://github.com/")
            assert entry["path"].endswith(".qml")
            assert entry["relevance"] >= 50
    # The official volume-osd example matches too, at a lower tier.
    examples = out["results"]["official_examples"]
    assert any(entry["path"] == "volume-osd" for entry in examples)
    best_impl = out["results"][impl_sections[0]][0]["relevance"]
    assert all(entry["relevance"] < best_impl for entry in examples)


def test_mixed_query_groups_docs_and_implementations(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    # No word here doubles as an exact type name, so the feature phrasing
    # decides: working implementations outrank reference pages.
    out = srv._search_everything("workspace pager switcher", "v0.3.1")

    assert "quickshell_types" in out["results"]
    assert {entry.get("type_name") for entry in out["results"]["quickshell_types"]} >= {
        "HyprlandWorkspace",
        "I3Workspace",
    }
    impl_sections = [key for key in out["results"] if key.endswith("_implementations")]
    assert impl_sections, "workspaces topic should hit implementation paths"
    assert set(out["section_order"]) == set(out["results"])
    assert out["section_order"][0] == impl_sections[0]


def test_namespace_hits_survive_the_type_limit(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._search_everything("Hyprland", "v0.3.1")
    entries = out["results"]["quickshell_types"]

    # Exact hit first...
    assert entries[0]["type_name"] == "Hyprland"
    assert entries[0]["relevance"] == 95
    # ...and the namespace context stays visible even though single-token
    # substring types fill every regular slot.
    namespaces = [entry for entry in entries if entry["kind"] == "namespace"]
    assert any(entry["namespace"] == "Quickshell.Hyprland" for entry in namespaces)
    assert all("url" not in entry for entry in namespaces)
    assert all(entry["relevance"] <= 50 for entry in namespaces)
    assert len([e for e in entries if e["kind"] == "api reference"]) <= 4


def test_no_result_query_is_loud_not_silent(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._search_everything("zzzqqq wibble", "v0.3.1")

    assert out["total_matches"] == 0
    assert out["results"] == {}
    assert out["section_order"] == []
    assert out["errors"] == {}
    assert "No matches" in out["note"]


def test_exact_type_outranks_substring_and_limits_apply(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._search_everything("workspace HyprlandWorkspace", "v0.3.1")
    entries = out["results"]["quickshell_types"]
    assert entries[0]["type_name"] == "HyprlandWorkspace"
    assert entries[0]["relevance"] == 95
    substring = [entry for entry in entries if entry["relevance"] < 95]
    assert any(entry["type_name"] == "I3Workspace" for entry in substring)
    # A type matching both query words outranks single-word hits in the tier.
    one_word = [entry for entry in entries if entry["type_name"] == "Hyprland"]
    if one_word:
        workspace_pos = entries.index(
            next(e for e in entries if e["type_name"] == "HyprlandWorkspace")
        )
        assert workspace_pos < entries.index(one_word[0])

    limited = srv._search_everything("workspace HyprlandWorkspace", "v0.3.1", limit_per_source=2)
    assert all(len(group) <= 2 for group in limited["results"].values())
    assert limited["section_order"][0] == "quickshell_types"


def test_include_content_flag_adds_guide_text_section(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls, guide_bodies={"advanced": "ipc ipc ipc"})

    without = srv._search_everything("ipc", "v0.3.1")
    assert "guide_content" not in without["results"]

    with_content = srv._search_everything("ipc", "v0.3.1", include_content=True)
    content = with_content["results"]["guide_content"]
    slugs = {entry["slug"] for entry in content}
    assert "advanced" in slugs
    for entry in content:
        assert {"slug", "url", "occurrences", "snippet", "relevance", "match_reason"} <= set(entry)


def test_partial_source_failure_is_isolated(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls, extra_404={_CAEL_TREE})
    out = srv._search_everything("volume OSD", "v0.3.1")

    assert "caelestia_implementations" in out["errors"]
    assert out["section_order"][0] == "noctalia_implementations"
    assert "official_examples" in out["results"]
    assert "unavailable sources: caelestia_implementations" in out["note"]


def test_empty_query_short_circuits(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._search_everything("   ", "v0.3.1")
    assert out["total_matches"] == 0
    assert "Empty query" in out["note"]


def test_wrapper_resolves_version_and_records_stats(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    before = dict(srv._TOOL_CALLS)
    out = srv.quickshell_search_all("PanelWindow")
    assert out["version"] == "v0.3.1"
    assert srv._TOOL_CALLS["quickshell_search_all"] == before.get("quickshell_search_all", 0) + 1
