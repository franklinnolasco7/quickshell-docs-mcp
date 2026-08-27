"""Pattern-oriented lookup (quickshell_find_pattern), offline off the same
committed fixtures as the other search tools."""

from __future__ import annotations

from conftest import load_fixture

# Both pattern lookup and search_all read the exact same upstreams, so they
# share one installer built on committed fixtures.
from test_search_all import _install as install_search_fixtures

import quickshell_mcp.server as srv
from quickshell_mcp.sources.docs import TYPE_LINK_RE
from quickshell_mcp.sources.find_pattern import _PATTERNS, _interpret_query


def test_spotlight_alias_finds_launchers_in_both_shells(monkeypatch, docs_fixture_urls):
    install_search_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._find_pattern("launcher like Spotlight", "v0.3.1")

    interpreted = {entry["pattern"]: entry for entry in out["interpreted_as"]}
    assert "launcher" in interpreted
    assert "spotlight" in interpreted["launcher"]["why"]
    sources = {entry["source"] for entry in out["implementations"]}
    assert sources == {"caelestia", "noctalia"}
    for entry in out["implementations"]:
        assert entry["api_hints"] == ["IpcHandler", "Process"]
        assert entry["url"].startswith("https://github.com/")
        assert "launcher" in entry["topics"] or "launcher" in entry["path"].lower()


def test_system_tray_exact_match_includes_type_docs(monkeypatch, docs_fixture_urls):
    install_search_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._find_pattern("system tray", "v0.3.1")

    type_names = {
        entry.get("type_name") for entry in out["docs"].get("types", []) if entry.get("type_name")
    }
    assert {"SystemTray", "SystemTrayItem"} <= type_names
    for entry in out["implementations"]:
        assert "tray" in entry["path"].lower() or "tray" in entry["topics"]
    assert any(entry["pattern"] == "tray" for entry in out["interpreted_as"])


def test_volume_osd_groups_cross_project_and_examples(monkeypatch, docs_fixture_urls):
    install_search_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._find_pattern("volume OSD", "v0.3.1")

    patterns = {entry["pattern"] for entry in out["interpreted_as"]}
    assert {"osd", "audio"} <= patterns
    grouped = {group["pattern"]: group for group in out["cross_project_patterns"]}
    assert grouped, "both shells ship OSD and audio code; grouping should fire"
    for group in grouped.values():
        assert set(group["projects"]) == {"caelestia", "noctalia"}
        assert all(group["projects"][source] for source in group["projects"])
    example_paths = {entry["path"] for entry in out["examples"]}
    assert "volume-osd" in example_paths


def test_unknown_query_is_loud(monkeypatch, docs_fixture_urls):
    install_search_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._find_pattern("zzzqqq wibble", "v0.3.1")

    assert out["interpreted_as"] == []
    assert out["total_matches"] == 0
    assert out["implementations"] == []
    assert out["errors"] == {}
    assert "No known pattern matched" in out["note"]


def test_ranking_respects_cap(monkeypatch, docs_fixture_urls):
    install_search_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._find_pattern("workspace indicator", "v0.3.1", limit=2)

    impls = out["implementations"]
    assert len(impls) <= 2
    relevances = [entry["relevance"] for entry in impls]
    assert relevances == sorted(relevances, reverse=True)
    # Both projects still get representation despite the tiny cap.
    assert {entry["source"] for entry in impls} == {"caelestia", "noctalia"}

    default = srv._find_pattern("workspace indicator", "v0.3.1")
    assert len(default["implementations"]) <= 5


def test_limit_one_keeps_the_top_hit(monkeypatch, docs_fixture_urls):
    """The cross-project swap trades the last slot; at limit=1 that slot is
    the best result, so it must survive untouched."""
    from quickshell_mcp.sources import find_pattern as fp

    def fake_impl(source, query, tokens, limit):
        if source == "caelestia":
            return [
                {
                    "source": "caelestia",
                    "path": "a/Top.qml",
                    "relevance": 95,
                    "topics": ["workspaces"],
                    "kind": "real-world implementation",
                    "url": "https://github.com/caelestia-dots/shell/blob/main/a/Top.qml",
                }
            ]
        return [
            {
                "source": "noctalia",
                "path": "z/Lower.qml",
                "relevance": 40,
                "topics": [],
                "kind": "real-world implementation",
                "url": "https://github.com/noctalia-dev/noctalia/blob/legacy-v4/z/Lower.qml",
            }
        ]

    monkeypatch.setattr(fp, "_search_impl_source", fake_impl)
    out = srv._find_pattern("workspace indicator", "v0.3.1", limit=1)
    assert [entry["path"] for entry in out["implementations"]] == ["a/Top.qml"]

    wider = srv._find_pattern("workspace indicator", "v0.3.1", limit=5)
    assert {entry["source"] for entry in wider["implementations"]} == {
        "caelestia",
        "noctalia",
    }


def test_grouping_survives_result_capping(monkeypatch, docs_fixture_urls):
    """cross_project_patterns reads the uncapped collection, so a tight
    implementation cap must not hide that both shells ship the pattern."""
    install_search_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._find_pattern("workspace indicator", "v0.3.1", limit=1)

    assert len(out["implementations"]) == 1
    impl_sources = {entry["source"] for entry in out["implementations"]}
    assert "caelestia" not in impl_sources  # capped away entirely

    groups = {group["pattern"]: group for group in out["cross_project_patterns"]}
    assert "workspaces" in groups
    assert set(groups["workspaces"]["projects"]) == {"caelestia", "noctalia"}
    assert groups["workspaces"]["projects"]["caelestia"]


def test_multi_pattern_grouping_at_limit_one(monkeypatch, docs_fixture_urls):
    """Grouping data must not depend on the per-source cap: with limit=1 each
    source's top file is OSD-pure, yet audio is implemented in both shells and
    still has to group."""
    install_search_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._find_pattern("volume OSD", "v0.3.1", limit=1)

    assert len(out["implementations"]) == 1
    groups = {group["pattern"]: group for group in out["cross_project_patterns"]}
    assert {"osd", "audio"} <= set(groups)
    for key in ("osd", "audio"):
        assert set(groups[key]["projects"]) == {"caelestia", "noctalia"}


def test_version_is_echoed(monkeypatch, docs_fixture_urls):
    install_search_fixtures(monkeypatch, docs_fixture_urls)
    assert srv._find_pattern("system tray", "v0.3.1")["version"] == "v0.3.1"
    via_wrapper = srv.quickshell_find_pattern("system tray")
    assert via_wrapper["version"] == "v0.3.1"


def test_interpret_query_units():
    matched = {
        pattern["key"]: reason for pattern, reason in _interpret_query("launcher like Spotlight")
    }
    assert "launcher" in matched
    assert "spotlight" in matched["launcher"]

    multi = {pattern["key"] for pattern, _ in _interpret_query("volume OSD")}
    assert {"osd", "audio"} <= multi

    # Aliases added for real query misses.
    assert {pattern["key"] for pattern, _ in _interpret_query("animated popup")} >= {"animations"}
    assert {pattern["key"] for pattern, _ in _interpret_query("quick settings panel")} >= {
        "control-center"
    }

    assert _interpret_query("zzzqqq wibble") == []

    # Multi-word aliases win: the center alias must not hide the OSD topic.
    nested = {pattern["key"] for pattern, _ in _interpret_query("notification center")}
    assert "notifications" in nested


def test_alias_matching_respects_word_boundaries(monkeypatch, docs_fixture_urls):
    """Near misses sharing a substring with an alias must not activate it."""
    assert {pattern["key"] for pattern, _ in _interpret_query("fix my toaster")} == set()
    assert {pattern["key"] for pattern, _ in _interpret_query("reanimated sprite")} == set()

    # Real boundary matches keep working, hyphens included.
    assert "notifications" in {pattern["key"] for pattern, _ in _interpret_query("a toast popup")}
    assert "animations" in {pattern["key"] for pattern, _ in _interpret_query("animated popup")}
    assert "bar" in {pattern["key"] for pattern, _ in _interpret_query("menu bar module")}
    assert "launcher" in {pattern["key"] for pattern, _ in _interpret_query("spotlight search")}


def test_every_curated_api_hint_exists_in_the_docs_index():
    html = load_fixture("guide_index.html")
    real_types = {name for _, _, name in TYPE_LINK_RE.findall(html)}
    for pattern in _PATTERNS:
        unknown = set(pattern["api_hints"]) - real_types
        assert not unknown, f"{pattern['key']} hints at types missing from the index: {unknown}"
        # Catalog order is the single source of truth for every output field
        # (entries, interpreted_as, cross_project_patterns); keep it uniform.
        assert pattern["api_hints"] == sorted(pattern["api_hints"]), (
            f"{pattern['key']} api_hints are not alphabetized"
        )


def test_partial_failure_is_isolated(monkeypatch, docs_fixture_urls):
    noct_tree = f"{srv._GITHUB_API}/repos/noctalia-dev/noctalia/git/trees/legacy-v4?recursive=1"
    install_search_fixtures(
        monkeypatch,
        docs_fixture_urls,
        extra_404={noct_tree},
    )
    out = srv._find_pattern("volume OSD", "v0.3.1")

    assert "noctalia_implementations" in out["errors"]
    assert {entry["source"] for entry in out["implementations"]} == {"caelestia"}
    assert out["examples"], "examples source is independent of the GitHub failure"
