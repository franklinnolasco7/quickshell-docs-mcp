"""HTML -> Markdown extraction quality, checked against real page snapshots."""

from __future__ import annotations

import quickshell_mcp.server as srv
from quickshell_mcp import utils  # noqa: E402


def test_extraction_strips_chrome_and_keeps_type_content():
    from conftest import load_fixture

    md = srv._extract_main_content(load_fixture("hyprland_monitor.html"))
    assert "HyprlandMonitor" in md
    assert "Properties" in md
    # Sidebar/nav chrome must be gone.
    assert "Switch Version" not in md
    assert "Quickshell Examples" not in md


def test_extraction_strips_chrome_and_keeps_guide_content():
    from conftest import load_fixture

    md = srv._extract_main_content(load_fixture("qml_language.html"))
    assert "# QML Language" in md
    assert "Structure" in md
    assert "Switch Version" not in md


def test_with_source_header_format():
    out = srv._with_source("https://example.com/docs/v1/", "# Title\n")
    first_line = out.splitlines()[0]
    assert first_line == "*Source: [https://example.com/docs/v1/](https://example.com/docs/v1/)*"
    assert out.endswith("# Title\n")


def test_fetched_urls_use_trailing_slash(monkeypatch, docs_fixture_urls):
    """Page fetches must request the trailing-slash URL directly (no 308 hop)."""
    seen: list[str] = []

    def fake_fetch(url: str) -> str:
        for prefix, html in docs_fixture_urls.items():
            if url.startswith(prefix):
                seen.append(url)
                return html
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)
    srv._guide_page("qml-language", "latest")
    assert f"{srv.BASE}/docs/v0.3.1/guide/qml-language/" in seen
