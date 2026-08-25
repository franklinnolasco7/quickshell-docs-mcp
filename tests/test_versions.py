"""Version discovery: regex, sort order (incl. prereleases), caching."""

from __future__ import annotations

import pytest
from conftest import http_404

import quickshell_docs_mcp.server as srv
from quickshell_docs_mcp import utils  # noqa: E402

ALL_VERSIONS = ["v0.3.1", "v0.3.0", "v0.2.1", "v0.2.0", "v0.1.0"]


def test_version_sort_key_orders_semver():
    versions = ["v0.10.0", "v0.2.0", "v0.3.1", "v1.0.0"]
    assert sorted(versions, key=srv._version_sort_key, reverse=True) == [
        "v1.0.0",
        "v0.10.0",
        "v0.3.1",
        "v0.2.0",
    ]


def test_version_sort_key_release_above_prerelease():
    versions = ["v0.4.0-rc1", "v0.4.0", "v0.3.1"]
    assert sorted(versions, key=srv._version_sort_key, reverse=True) == [
        "v0.4.0",
        "v0.4.0-rc1",
        "v0.3.1",
    ]


def test_version_regex_matches_prereleases_and_ignores_unversioned():
    html = (
        '<a href="/docs/v0.4.0-rc1/">a</a><a href="/docs/v0.3.1/">b</a><a href="/docs/guide/">c</a>'
    )
    assert srv.VERSION_RE.findall(html) == ["v0.4.0-rc1", "v0.3.1"]


def test_discovery_from_about_page_stops_early(monkeypatch, docs_fixture_urls):
    seen: list[str] = []

    def counting_fetch(url: str) -> str:
        for prefix, html in docs_fixture_urls.items():
            if url.startswith(prefix):
                seen.append(url)
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", counting_fetch)
    versions = srv.list_versions()
    assert versions == ALL_VERSIONS
    # /about/ alone lists every version, so no other candidate is fetched.
    assert seen == [f"{srv.BASE}/about/"]


def test_latest_version(mock_fetch, docs_fixture_urls):
    mock_fetch(docs_fixture_urls)
    assert srv._latest_version() == "v0.3.1"


def test_resolve_version(mock_fetch, docs_fixture_urls):
    mock_fetch(docs_fixture_urls)
    assert srv._resolve_version("latest") == "v0.3.1"
    assert srv._resolve_version("latest") == "v0.3.1"  # cached path
    assert srv._resolve_version("0.2.0") == "v0.2.0"
    assert srv._resolve_version("v0.2.0") == "v0.2.0"


def test_resolve_unknown_version_lists_known(mock_fetch, docs_fixture_urls):
    mock_fetch(docs_fixture_urls)
    with pytest.raises(ValueError, match="Unknown version 'v9.9.9'.*v0.3.1"):
        srv._resolve_version("v9.9.9")


def test_refresh_bypasses_cache(monkeypatch, docs_fixture_urls):
    count = {"n": 0}

    def counting_fetch(url: str) -> str:
        for prefix, html in docs_fixture_urls.items():
            if url.startswith(prefix):
                count["n"] += 1
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", counting_fetch)
    first = srv.list_versions()
    assert count["n"] == 1
    assert srv.list_versions() == first
    assert count["n"] == 1  # second call served from cache
    refreshed = srv.list_versions(refresh=True)
    assert count["n"] == 2  # cache was bypassed and repopulated
    assert refreshed == first


def test_discovery_survives_dead_candidates(monkeypatch):
    """If /about/ dies but a docs page lives on, discovery still works."""
    guide_html = '<nav><a href="/docs/v0.5.0/">x</a><a href="/docs/v0.4.0/">y</a></nav>'

    def fake_fetch(url: str) -> str:
        if url.endswith("/about/"):
            raise http_404(url)
        return guide_html

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)
    assert srv.list_versions() == ["v0.5.0", "v0.4.0"]
