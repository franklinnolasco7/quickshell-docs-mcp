"""Shared fixtures: real saved HTML snapshots from quickshell.org plus a
fetch mock so the whole suite runs offline."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import quickshell_mcp.server as srv  # noqa: E402
from quickshell_mcp import utils  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.fixture(autouse=True)
def _clear_cache_and_stats(tmp_path, monkeypatch):
    # Disk cache redirected to a throwaway dir so the offline suite never
    # reads or pollutes the user's real ~/.cache.
    monkeypatch.setenv("QUICKSHELL_DOCS_MCP_DISK_CACHE", str(tmp_path / "disk-cache"))
    srv._cache.clear()
    srv._TOOL_CALLS.clear()
    srv._FETCH_STATS.update(cache_hits=0, network_fetches=0)
    yield
    srv._cache.clear()
    srv._TOOL_CALLS.clear()
    srv._FETCH_STATS.update(cache_hits=0, network_fetches=0)


@pytest.fixture
def docs_fixture_urls() -> dict[str, str]:
    """URL-prefix -> HTML mapping covering version discovery and index building."""
    return {
        f"{srv.BASE}/about/": load_fixture("about.html"),
        f"{srv.BASE}/docs/v0.3.1/guide/": load_fixture("guide_index.html"),
    }


@pytest.fixture
def mock_fetch(monkeypatch) -> Callable[[dict[str, str]], None]:
    """Install a fake ``_fetch_raw`` driven by a {url_prefix: html} mapping.
    Requests that match no prefix fail loudly instead of leaking to the net."""

    def install(mapping: dict[str, str]) -> None:
        def fake_fetch(url: str) -> str:
            for prefix, html in mapping.items():
                if url.startswith(prefix):
                    return html
            raise AssertionError(f"unexpected fetch in test: {url}")

        monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    return install


def http_404(url: str) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", url)
    response = httpx.Response(404, request=request)
    return httpx.HTTPStatusError(
        f"Client error '404 Not Found' for url '{url}'", request=request, response=response
    )
