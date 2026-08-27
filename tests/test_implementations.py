"""Implementation-reference tools (Caelestia / Noctalia via the GitHub API),
driven by pruned-but-real tree snapshots and real raw files.

Tree fixtures are the live API responses with non-QML blobs dropped (keys
unchanged); raw-file fixtures are verbatim file contents."""

from __future__ import annotations

import json

import pytest
from conftest import http_404, load_fixture

import quickshell_mcp.server as srv
from quickshell_mcp import utils  # noqa: E402


def _install(monkeypatch, extra_404: set[str] | None = None):
    extra_404 = extra_404 or set()
    cael_tree = f"{srv._GITHUB_API}/repos/caelestia-dots/shell/git/trees/main?recursive=1"
    noct_tree = f"{srv._GITHUB_API}/repos/noctalia-dev/noctalia/git/trees/legacy-v4?recursive=1"
    cael_raw = (
        "https://raw.githubusercontent.com/caelestia-dots/shell/main/components/AnchorAnim.qml"
    )
    noct_raw = (
        "https://raw.githubusercontent.com/noctalia-dev/noctalia/legacy-v4/Widgets/NButton.qml"
    )
    mapping = {
        f"{srv._GITHUB_API}/repos/caelestia-dots/shell": load_fixture(
            "impl_caelestia_repo_info.json"
        ),
        cael_tree: load_fixture("impl_caelestia_tree.json"),
        cael_raw: load_fixture("impl_caelestia_anchoranim.qml"),
        noct_tree: load_fixture("impl_noctalia_tree.json"),
        noct_raw: load_fixture("impl_noctalia_nbutton.qml"),
    }

    def fake_fetch(url: str) -> str:
        if url in extra_404:
            raise http_404(url)
        if url not in mapping:
            raise AssertionError(f"unexpected fetch in test: {url}")
        return mapping[url]

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)


def test_search_finds_bar_in_both_shells_with_metadata(monkeypatch):
    _install(monkeypatch)
    out = srv.quickshell_search_implementations("find a Quickshell bar implementation")
    assert out["total_matches"] > 0
    for src, entries in out["results"].items():
        assert src in ("caelestia", "noctalia")
        for entry in entries:
            assert entry["source"] == src
            assert entry["kind"] == "real-world implementation"
            assert entry["repo"].startswith(("caelestia-dots/", "noctalia-dev/"))
            assert entry["url"].startswith("https://github.com/")
            assert entry["path"].endswith(".qml")
            assert "bar" in entry["topics"] or "bar" in entry["path"].lower()
    cael_paths = {e["path"] for e in out["results"]["caelestia"]}
    assert any(p.startswith("modules/bar/") for p in cael_paths)
    noct_paths = {e["path"] for e in out["results"]["noctalia"]}
    assert any("/Bar/" in p or p.startswith("Bar/") for p in noct_paths)


def test_search_source_filter_and_component_attribution(monkeypatch):
    _install(monkeypatch)
    only = srv.quickshell_search_implementations("notification implementation", source="Caelestia")
    assert list(only["results"]) == ["caelestia"]
    assert all(e["component"] for e in only["results"]["caelestia"])
    # description names the matched topic
    assert any("Notification" in e["description"] for e in only["results"]["caelestia"])


def test_segment_match_outranks_incidental_substring(monkeypatch):
    _install(monkeypatch)
    out = srv.quickshell_search_implementations("find a Quickshell bar implementation")
    cael_top = [e["path"] for e in out["results"]["caelestia"]]
    assert cael_top, "no caelestia hits"
    assert any(p.startswith("modules/bar/") for p in cael_top[:3])
    assert not any("searchbar" in p for p in cael_top[:3])


def test_multi_monitor_query_skips_battery_monitors(monkeypatch):
    _install(monkeypatch)
    out = srv.quickshell_search_implementations("find multi-monitor implementation")
    tops = {src: entries[0]["path"] for src, entries in out["results"].items() if entries}
    assert tops, "no multi-monitor hits"
    # Screen handling outranks incidental "*Monitor*" files (battery/CPU).
    for path in tops.values():
        assert "battery" not in path.lower()
        assert "systemmonitor" not in path.lower()


def test_broad_single_source_query_returns_structural_tour(monkeypatch):
    _install(monkeypatch)
    out = srv.quickshell_search_implementations(
        "find similar implementation in Noctalia", source="noctalia"
    )
    entries = out["results"]["noctalia"]
    assert entries, "broad query should return a structural tour"
    components = {e["component"] for e in entries}
    assert len(components) >= 3  # spread across the tree, not one directory


def test_wifi_query_resolves_caelestia_nmcli_path(monkeypatch):
    """Caelestia has no 'wifi' in any QML path; the network topic must catch
    services/Nmcli.qml anyway."""
    _install(monkeypatch)
    out = srv.quickshell_search_implementations("find wifi implementation")
    cael_hits = [e["path"] for e in out["results"]["caelestia"]]
    assert cael_hits, "caelestia wifi recall was empty before the network topic existed"
    assert any("nmcli" in p.lower() or "network" in p.lower() for p in cael_hits)
    noct_hits = [e["path"] for e in out["results"]["noctalia"]]
    assert any("wifi" in p.lower() for p in noct_hits)


def test_audio_and_media_topics_hit_real_files_not_noise(monkeypatch):
    _install(monkeypatch)
    volume = srv.quickshell_search_implementations("find volume implementation")
    cael_volume = [e["path"] for e in volume["results"]["caelestia"]]
    assert any("audio" in p.lower() or "volume" in p.lower() for p in cael_volume)

    media = srv.quickshell_search_implementations("find media controls")
    cael_media = [(e["path"], e["topics"]) for e in media["results"]["caelestia"]]
    # At the default limit every slot is a genuine media file (dashboard/
    # media/*, services/Players.qml); the old token-only behavior surfaced
    # components/controls noise like ButtonBase.qml instead.
    assert len(cael_media) == 8
    assert all("media" in topics for _, topics in cael_media)
    assert not any("buttonbase" in p.lower() for p, _ in cael_media)
    wide = srv.quickshell_search_implementations("find media controls", limit=15)
    assert any("players" in e["path"].lower() for e in wide["results"]["caelestia"]), (
        "Caelestia's MPRIS hub (services/Players.qml) should surface with a wider net"
    )


def test_search_unknown_topic_suggests_topics(monkeypatch):
    _install(monkeypatch)
    out = srv.quickshell_search_implementations("zzz-no-such-thing")
    assert out["total_matches"] == 0
    assert "Try an implementation topic" in out["note"]
    assert "osd" in out["note"]


def test_search_unknown_source_is_friendly():
    with pytest.raises(ValueError, match="Known sources"):
        srv.quickshell_search_implementations("bar", source="plasma")


def test_get_implementation_reads_exact_raw_url_with_kind_header(monkeypatch):
    _install(monkeypatch)
    body = srv.quickshell_get_implementation("noctalia", "Widgets/NButton.qml", find="button")
    assert (
        "https://raw.githubusercontent.com/noctalia-dev/noctalia/legacy-v4/"
        "Widgets/NButton.qml" not in body  # citation uses the blob URL instead
    )
    assert "github.com/noctalia-dev/noctalia/blob/legacy-v4/Widgets/NButton.qml" in body
    assert "real-world implementation" in body
    assert "not official documentation" in body
    assert "import QtQuick" in body or "property" in body


def test_get_implementation_find_window_narrows_output(monkeypatch):
    _install(monkeypatch)
    narrow = srv.quickshell_get_implementation(
        "caelestia", "components/AnchorAnim.qml", find="duration"
    )
    full = srv.quickshell_get_implementation("caelestia", "components/AnchorAnim.qml")
    assert len(narrow) < len(full)
    assert "showing lines" in narrow


def test_get_implementation_truncates_large_files(monkeypatch):
    _install(monkeypatch)
    body = srv.quickshell_get_implementation("noctalia", "Widgets/NButton.qml", max_chars=500)
    assert "[truncated at 500 chars" in body
    assert len(body) < 1500


def test_get_implementation_unknown_path_suggests_siblings(monkeypatch):
    _install(monkeypatch)
    with pytest.raises(ValueError, match="Did you mean"):
        srv.quickshell_get_implementation("noctalia", "Widgets/NoSuchWidget.qml")


def test_get_implementation_unknown_source_is_friendly():
    with pytest.raises(ValueError, match="Known sources"):
        srv.quickshell_get_implementation("kde", "anything.qml")


def test_truncated_github_tree_is_refused(monkeypatch):
    truncated = load_fixture("impl_caelestia_tree.json").replace(
        '"truncated": false', '"truncated": true'
    )
    mapping = {
        f"{srv._GITHUB_API}/repos/caelestia-dots/shell": load_fixture(
            "impl_caelestia_repo_info.json"
        ),
        f"{srv._GITHUB_API}/repos/caelestia-dots/shell/git/trees/main?recursive=1": truncated,
    }
    monkeypatch.setattr(utils, "_fetch_raw", lambda url: mapping[url])
    from quickshell_mcp.sources.implementations import _build_impl_index

    with pytest.raises(RuntimeError, match="truncated"):
        _build_impl_index("caelestia")


def test_examples_listing_carries_official_kind(monkeypatch):
    from pathlib import Path

    root = Path(__file__).parent / "fixtures"
    info = json.dumps({"default_branch": "master"})
    contents = root.joinpath("examples_contents_root.json").read_text()

    def fake_fetch(url: str) -> str:
        if url == srv.EXAMPLES_REPO_API:
            return info
        if url == f"{srv.EXAMPLES_REPO_API}/contents?ref=master":
            return contents
        raise AssertionError(f"unexpected fetch in test: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)
    out = srv.quickshell_list_examples()
    assert out["kind"] == "official examples"
    assert all(entry["kind"] == "official example" for entry in out["entries"])
