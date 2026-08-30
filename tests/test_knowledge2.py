"""Tests for knowledge 2.0 tools: api_diff, api_graph, best_practice,
pattern_compare, provenance. Offline via the compat/migrate fixtures.
"""

from __future__ import annotations

import pytest

import quickshell_mcp.server as srv
from quickshell_mcp.sources import knowledge2 as k2

FIXTURES = __file__


def _install(mapping, monkeypatch):
    from test_migrate import _install_fetch

    _install_fetch(monkeypatch, mapping)


def _build_mapping(docs_fixture_urls):
    from test_migrate import _build_mapping

    return _build_mapping(docs_fixture_urls)


# ---------------------------------------------------------------------------
# API diff
# ---------------------------------------------------------------------------


def test_api_diff_added_removed(monkeypatch, docs_fixture_urls):
    _install(_build_mapping(docs_fixture_urls), monkeypatch)
    result = srv.quickshell_api_diff("v0.1.0", "v0.3.1")
    assert result["added"]
    assert result["removed"]
    assert result["added"] or result["removed"]
    assert result["provenance"]
    assert "changelog" in result


def test_api_diff_renamed_detected(monkeypatch, docs_fixture_urls):
    from test_migrate import _build_mapping

    _install(_build_mapping(docs_fixture_urls), monkeypatch)
    result = srv.quickshell_api_diff("v0.1.0", "v0.3.1")
    # shellRoot -> shellDir rename is in the changelog fixture.
    renamed = result.get("renamed", [])
    assert any("shellRoot" in r.get("old", "") or "shellDir" in r.get("new", "") for r in renamed)


def test_api_diff_same_version(monkeypatch, docs_fixture_urls):
    _install(_build_mapping(docs_fixture_urls), monkeypatch)
    result = srv.quickshell_api_diff("v0.3.1", "v0.3.1")
    assert result["added"] == []
    assert result["removed"] == []
    assert result["renamed"] == []


# ---------------------------------------------------------------------------
# API graph
# ---------------------------------------------------------------------------


def test_api_graph_panel_window(monkeypatch, docs_fixture_urls):
    _install(_build_mapping(docs_fixture_urls), monkeypatch)
    result = srv.quickshell_api_graph("PanelWindow", version="v0.3.1")
    assert result["api"] == "PanelWindow"
    assert result["nodes"]
    assert result["edges"]
    assert "documented" in result["note"]


def test_api_graph_not_found(monkeypatch, docs_fixture_urls):
    _install(_build_mapping(docs_fixture_urls), monkeypatch)
    with pytest.raises(ValueError, match="not found"):
        srv.quickshell_api_graph("TotallyMadeUp", version="v0.3.1")


def test_api_graph_with_members(monkeypatch, docs_fixture_urls):
    _install(_build_mapping(docs_fixture_urls), monkeypatch)
    result = srv.quickshell_api_graph("Quickshell", version="v0.3.1")
    # Quickshell has documented properties.
    assert result["nodes"]
    assert result["edges"]


# ---------------------------------------------------------------------------
# Best practice
# ---------------------------------------------------------------------------


def test_best_practice_returns_ranked(monkeypatch, docs_fixture_urls):
    from test_search_all import _install as install_search

    install_search(monkeypatch, docs_fixture_urls)
    result = k2._best_practice("PanelWindow", version="v0.3.1")
    assert result["guidance"]["documented"]
    assert result["note"]
    assert "Ranked" in result["note"]


def test_best_practice_empty_query(monkeypatch, docs_fixture_urls):
    from test_search_all import _install as install_search

    install_search(monkeypatch, docs_fixture_urls)
    result = k2._best_practice("", version="v0.3.1")
    assert result["guidance"]["documented"] == []


# ---------------------------------------------------------------------------
# Pattern compare
# ---------------------------------------------------------------------------


def test_pattern_compare_shape(monkeypatch, docs_fixture_urls):
    from test_search_all import _install as install_search

    install_search(monkeypatch, docs_fixture_urls)
    result = k2._pattern_compare("osd", version="v0.3.1")
    assert result["per_project"]
    assert all("project" in p for p in result["per_project"])
    assert result["note"]


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


def test_provenance_shape(monkeypatch, docs_fixture_urls):
    from test_search_all import _install as install_search

    install_search(monkeypatch, docs_fixture_urls)
    result = k2._provenance("PanelWindow", version="v0.3.1", limit=3)
    assert result["query"] == "PanelWindow"
    assert result["entries"]
    assert all("authority_level" in e for e in result["entries"])
    assert result["note"]


def test_provenance_empty_query(monkeypatch, docs_fixture_urls):
    from test_search_all import _install as install_search

    install_search(monkeypatch, docs_fixture_urls)
    result = k2._provenance("", version="v0.3.1")
    assert result["entries"] == []


# ---------------------------------------------------------------------------
# Tool wrappers
# ---------------------------------------------------------------------------


def test_api_diff_tool_records_stats(monkeypatch, docs_fixture_urls):
    _install(_build_mapping(docs_fixture_urls), monkeypatch)
    before = dict(srv._TOOL_CALLS)
    srv.quickshell_api_diff("v0.2.0", "v0.3.1")
    assert srv._TOOL_CALLS["quickshell_api_diff"] == before.get("quickshell_api_diff", 0) + 1


def test_provenance_tool_records_stats(monkeypatch, docs_fixture_urls):
    from test_search_all import _install as install_search

    install_search(monkeypatch, docs_fixture_urls)
    before = dict(srv._TOOL_CALLS)
    srv.quickshell_provenance("PanelWindow", version="v0.3.1")
    assert srv._TOOL_CALLS["quickshell_provenance"] == before.get("quickshell_provenance", 0) + 1
