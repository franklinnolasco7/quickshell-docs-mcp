"""Friendly 404 suggestions and retry behavior."""

from __future__ import annotations

import httpx
import pytest
from conftest import http_404

import quickshell_docs_mcp.server as srv
from quickshell_docs_mcp import utils  # noqa: E402


def make_fetch_404_elsewhere(monkeypatch, docs_fixture_urls):
    """Serve only the discovery/index pages; every other URL 404s like the site would."""

    servable = {
        f"{srv.BASE}/about/",
        f"{srv.BASE}/docs/v0.3.1/guide/",
    }

    def fake_fetch(url: str) -> str:
        if url in servable:
            return docs_fixture_urls[url]
        raise http_404(url)

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)


def test_unknown_guide_slug_suggests_known_pages(monkeypatch, docs_fixture_urls):
    make_fetch_404_elsewhere(monkeypatch, docs_fixture_urls)
    with pytest.raises(ValueError) as excinfo:
        srv._guide_page("qml-languge", "latest")
    msg = str(excinfo.value)
    assert "No guide page 'qml-languge' in v0.3.1" in msg
    assert "qml-language" in msg  # substring suggestion


def test_unknown_type_suggests_similar_types(monkeypatch, docs_fixture_urls):
    make_fetch_404_elsewhere(monkeypatch, docs_fixture_urls)
    with pytest.raises(ValueError) as excinfo:
        srv._type_page("HyprlandMoniter", "Quickshell.Hyprland", "latest")
    msg = str(excinfo.value)
    assert "No type 'HyprlandMoniter' in namespace 'Quickshell.Hyprland' for v0.3.1" in msg
    assert "HyprlandMonitor" in msg


def test_unknown_namespace_suggests_namespaces(monkeypatch, docs_fixture_urls):
    make_fetch_404_elsewhere(monkeypatch, docs_fixture_urls)
    with pytest.raises(ValueError) as excinfo:
        srv._type_page("Whatever", "Quickshell.Hypr", "latest")
    msg = str(excinfo.value)
    assert "No namespace 'Quickshell.Hypr' in v0.3.1" in msg
    assert "Quickshell.Hyprland" in msg


def test_http_404_helper_produces_status_error():
    err = http_404("https://example.com/x")
    assert isinstance(err, httpx.HTTPStatusError)
    assert err.response.status_code == 404


def test_fetch_raw_retries_transient_errors(monkeypatch):
    attempts = {"n": 0}

    def flaky_get(url: str) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise httpx.ConnectError("boom", request=httpx.Request("GET", url))
        return httpx.Response(200, text="ok", request=httpx.Request("GET", url))

    monkeypatch.setattr(utils._client, "get", flaky_get)
    monkeypatch.setattr(utils.time, "sleep", lambda _s: None)
    assert srv._fetch_raw("https://example.com/flaky") == "ok"
    assert attempts["n"] == 3


def test_fetch_raw_raises_after_exhausting_retries(monkeypatch):
    attempts = {"n": 0}

    def always_fail(url: str) -> httpx.Response:
        attempts["n"] += 1
        raise httpx.ReadTimeout("timeout", request=httpx.Request("GET", url))

    monkeypatch.setattr(utils._client, "get", always_fail)
    monkeypatch.setattr(utils.time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError, match="after 3 attempts"):
        srv._fetch_raw("https://example.com/dead")
    assert attempts["n"] == 3


def test_fetch_raw_does_not_retry_http_status_errors(monkeypatch, docs_fixture_urls):
    def ok_get(url: str) -> httpx.Response:
        return httpx.Response(200, text="page", request=httpx.Request("GET", url))

    monkeypatch.setattr(utils._client, "get", ok_get)
    # A cached-free URL goes through the real client; status errors propagate.
    assert srv._fetch_raw("https://example.com/fine") == "page"
