"""Tests for quickshell_coding_assistant: the orchestration layer.

The assistant composes the existing per-source helpers, so these tests reuse
the generate fixtures (per-version indexes, type pages, changelog, Qt module
pages, impl trees, examples) and layer the per-version Quickshell/PanelWindow
pages the migrate path needs, mirroring test_migrate's API history
(Quickshell.shellRoot renamed to shellDir in v0.2.0, exclusiveZone introduced
in v0.2.0).
"""

from __future__ import annotations

from test_generate import _install_generate_fixtures
from test_migrate import (
    _changelog_markdown,
    _panel_window_page,
    _quickshell_old_page,
    _quickshell_page,
)

import quickshell_mcp.server as srv
from quickshell_mcp import utils  # noqa: E402
from quickshell_mcp.sources import assistant

BASE = srv.BASE
_VERSIONS = ["v0.3.1", "v0.3.0", "v0.2.1", "v0.2.0", "v0.1.0"]


def _wrap(markdown: str) -> str:
    return f"<html><body><main>{markdown}</main></body></html>"


def _install(monkeypatch, docs_fixture_urls, extra_404=None):
    """Generate fixtures plus the migrate history, and a raw-file wildcard so
    implementation excerpts resolve offline."""
    _install_generate_fixtures(monkeypatch, docs_fixture_urls, extra_404=extra_404)
    base_fetch = utils._fetch_raw
    mapping: dict[str, str] = {f"{BASE}/changelog/": _wrap(_changelog_markdown())}
    for version in _VERSIONS:
        if version != "v0.3.1":
            mapping[f"{BASE}/docs/{version}/types/Quickshell/PanelWindow/"] = _wrap(
                _panel_window_page(version)
            )
        page = _quickshell_old_page() if version == "v0.1.0" else _quickshell_page()
        mapping[f"{BASE}/docs/{version}/types/Quickshell/Quickshell/"] = _wrap(page)

    def fake_fetch(url: str) -> str:
        if "raw.githubusercontent.com" in url:
            return 'import Quickshell\nPanelWindow { color: "#1e1e2e" }\n'
        if url in mapping:
            return mapping[url]
        return base_fetch(url)

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)


def _tools(out: dict) -> list[str]:
    return [entry["tool"] for entry in out["orchestration"]]


def test_classify_intent_modes():
    cases = [
        ("Build a Hyprland workspace bar", {}, "build", "hyprland"),
        ("Add an animated volume popup", {}, "build", None),
        ("Why is this PanelWindow failing?", {"error": "boom"}, "debug", None),
        ("Fix this QML error", {"code": "PanelWindow {}"}, "debug", None),
        ("Migrate this shell from v0.2 to v0.3", {}, "migrate", None),
        ("upgrade my shell", {"from_version": "v0.1.0"}, "migrate", None),
        ("Find an implementation of a volume OSD and adapt the pattern", {}, "pattern", None),
        ("How should I structure this Quickshell component?", {}, "research", None),
        ("What is PanelWindow?", {}, "research", None),
        ("workspace indicator on sway", {}, "research", "sway"),
    ]
    for request, extra, expected_type, expected_compositor in cases:
        intent = assistant._classify_intent(
            request,
            code=None,
            error=extra.get("error"),
            from_version=extra.get("from_version"),
            to_version=None,
        )
        assert intent["type"] == expected_type, request
        assert intent["compositor"] == expected_compositor, request


def test_resolve_version_hint(mock_fetch, docs_fixture_urls):
    mock_fetch(docs_fixture_urls)
    assert assistant._resolve_version_hint("0.2") == "v0.2.1"
    assert assistant._resolve_version_hint("v0.3") == "v0.3.1"
    assert assistant._resolve_version_hint("v0.3.0") == "v0.3.0"
    assert assistant._resolve_version_hint("latest") == "v0.3.1"
    assert assistant._resolve_version_hint("9.9") is None
    assert assistant._resolve_version_hint(None) is None


def test_empty_request_short_circuits():
    out = srv._coding_assistant("   ")
    assert out["orchestration"] == []
    assert out["intent"]["type"] is None
    assert "Empty request" in out["note"]


def test_build_request_routes_to_generate(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._coding_assistant("Build a Hyprland workspace bar")

    assert out["intent"]["type"] == "build"
    assert out["intent"]["compositor"] == "hyprland"
    tools = _tools(out)
    assert "quickshell_generate_component" in tools
    assert not any(t in ("quickshell_search_all", "quickshell_find_pattern") for t in tools)
    assert out["understanding"]
    assert any("Hyprland" in line for line in out["understanding"])
    workspace = next(api for api in out["relevant_apis"] if api["name"] == "HyprlandWorkspace")
    assert workspace["verified"] is True
    assert workspace["url"].startswith("https://quickshell.org/")
    assert out["validation"]["summary"]["errors"] == 0
    assert out["compatibility"]["verdict"] == "verified"
    assert out["sources"]


def test_build_request_detects_compositor_from_text(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    hypr = srv._coding_assistant("Build a Hyprland workspace bar")
    assert hypr["intent"]["compositor"] == "hyprland"
    generic = srv._coding_assistant("Build a workspace bar")
    assert generic["intent"]["compositor"] is None
    assert not any("Compositor detected" in line for line in generic["understanding"])


def test_version_specific_build_flags_missing_api(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._coding_assistant("Build a clock", version="v0.2.0")

    assert out["intent"]["version"] == "v0.2.0"
    # SystemClock does not exist in v0.2.0, so the build must not claim it.
    assert out["compatibility"]["verdict"] == "unverified"
    assert "could not be verified" in out["note"]
    assert all(api["verified"] for api in out["relevant_apis"])


def test_research_request(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._coding_assistant("What is PanelWindow?")

    assert out["intent"]["type"] == "research"
    tools = _tools(out)
    assert "quickshell_search_all" in tools
    assert "quickshell_get_type" in tools
    assert "quickshell_check_compatibility" in tools
    assert out["validation"] is None
    assert out["understanding"]
    panel = next(api for api in out["relevant_apis"] if api["name"] == "PanelWindow")
    assert panel["verified"] is True
    assert panel["namespace"] == "Quickshell"
    assert out["compatibility"]["verdict"] == "compatible"
    assert out["sources"]


def test_debug_request_with_error_and_code(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._coding_assistant(
        "Why is this PanelWindow failing?",
        error="Cannot assign to non-existent property 'foo'",
        code="PanelWindow { foo: 1 }",
    )

    assert out["intent"]["type"] == "debug"
    tools = _tools(out)
    assert "quickshell_explain_error" in tools
    assert "quickshell_validate_qml" in tools
    assert "quickshell_check_compatibility" in tools
    assert any("non_existent_property" in line for line in out["understanding"])
    assert out["validation"]["summary"]["warnings"] >= 1
    assert any(issue["api"] == "foo" for issue in out["remaining_issues"])
    assert out["sources"]


def test_debug_request_invalid_qml(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._coding_assistant("fix this broken QML", code="PanelWindow { ")

    assert out["intent"]["type"] == "debug"
    assert out["validation"]["summary"]["errors"] == 1
    assert any("Unbalanced" in issue["message"] for issue in out["remaining_issues"])


def test_migrate_request_with_code(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._coding_assistant(
        "Migrate this shell",
        code='Quickshell { shellRoot: "/etc" }',
        from_version="v0.1.0",
        to_version="v0.3.1",
    )

    assert out["intent"]["type"] == "migrate"
    tools = _tools(out)
    assert "quickshell_migrate" in tools
    assert "quickshell_validate_qml" in tools
    assert any("Migrating from v0.1.0 to v0.3.1" in line for line in out["understanding"])
    assert any(api["name"] == "Quickshell.shellDir" for api in out["relevant_apis"])
    assert any("shellRoot" in issue["message"] for issue in out["remaining_issues"])
    assert any(entry["basis"] == "changelog" for entry in out["recommended_approach"])
    assert out["validation"] is not None


def test_migrate_request_without_code_reads_changelog(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._coding_assistant("Migrate this shell from v0.2 to v0.3")

    assert out["intent"]["type"] == "migrate"
    tools = _tools(out)
    assert "quickshell_changelog" in tools
    assert "quickshell_migrate" not in tools
    assert out["validation"] is None
    assert out["remaining_issues"] == []
    assert any("Migrating from v0.2.1 to v0.3.1" in line for line in out["understanding"])
    changelog_steps = [
        entry["step"] for entry in out["recommended_approach"] if entry["basis"] == "changelog"
    ]
    assert changelog_steps
    assert any("LegacyThing" in entry["step"] for entry in out["recommended_approach"])


def test_migrate_ambiguous_range_asks_for_versions(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._coding_assistant("migrate my config")
    assert out["intent"]["type"] == "migrate"
    assert any("Pass from_version and to_version" in line for line in out["understanding"])


def test_pattern_request(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._coding_assistant("Find an implementation of a volume OSD and adapt the pattern")

    assert out["intent"]["type"] == "pattern"
    tools = _tools(out)
    assert "quickshell_find_pattern" in tools
    assert "quickshell_get_implementation" in tools
    assert "quickshell_check_compatibility" in tools
    assert out["implementation_references"]
    assert any("excerpt" in ref for ref in out["implementation_references"])
    assert out["relevant_apis"]


def test_conflicting_sources_docs_win(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    real = assistant._check_compatibility

    def fake(api=None, type=None, version="latest", **kwargs):
        if (type or api) == "Pipewire":
            return {
                "compatibility": "incompatible",
                "confidence": "high",
                "explanation": "Pipewire is not documented in this version.",
                "documentation": [],
            }
        return real(api=api, type=type, version=version, **kwargs)

    monkeypatch.setattr(assistant, "_check_compatibility", fake)
    out = srv._coding_assistant("Find an implementation of a volume OSD and adapt the pattern")

    pipewire = next(api for api in out["relevant_apis"] if api["name"] == "Pipewire")
    assert pipewire["compatibility"] == "incompatible"
    assert pipewire["verified"] is False


def test_uncertain_api_resolution_is_flagged(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    real = assistant._check_compatibility

    def fake(type=None, version="latest", **kwargs):
        if type == "PanelWindow":
            return {
                "compatibility": "uncertain",
                "confidence": "low",
                "explanation": "PanelWindow could not be verified.",
                "documentation": [],
            }
        return real(type=type, version=version, **kwargs)

    monkeypatch.setattr(assistant, "_check_compatibility", fake)
    out = srv._coding_assistant("What is PanelWindow?")

    panel = next(api for api in out["relevant_apis"] if api["name"] == "PanelWindow")
    assert panel["compatibility"] == "uncertain"
    assert panel["verified"] is False
    assert out["compatibility"]["verdict"] is None


def test_failed_step_is_isolated(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)

    def boom(query, version, **kwargs):
        raise RuntimeError("search backend down")

    monkeypatch.setattr(assistant, "_search_everything", boom)
    out = srv._coding_assistant("What is PanelWindow?")

    assert out["errors"]["quickshell_search_all"] == "search backend down"
    assert any("Search failed" in line for line in out["understanding"])
    assert out["relevant_apis"] == []


def test_malformed_step_response_is_isolated(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    monkeypatch.setattr(assistant, "_search_everything", lambda *a, **k: "not a dict")
    out = srv._coding_assistant("What is PanelWindow?")

    assert "quickshell_search_all" not in out["errors"]
    entry = next(e for e in out["orchestration"] if e["tool"] == "quickshell_search_all")
    assert entry["status"] == "malformed"
    assert out["relevant_apis"] == []


def test_timeout_step_is_isolated(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)

    def timeout(*args, **kwargs):
        raise TimeoutError("type page timed out")

    monkeypatch.setattr(assistant, "_type_page", timeout)
    out = srv._coding_assistant("What is PanelWindow?")

    assert "quickshell_get_type" in out["errors"]
    assert out["errors"]["quickshell_get_type"] == "type page timed out"
    assert out["relevant_apis"] == []
    assert out["understanding"]


def test_no_self_scheduling_and_no_duplicate_tools(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    requests = [
        "Build a Hyprland workspace bar",
        "What is PanelWindow?",
        "Why is this PanelWindow failing?",
        "Migrate this shell from v0.2 to v0.3",
        "Find an implementation of a volume OSD and adapt the pattern",
    ]
    for request in requests:
        out = srv._coding_assistant(request)
        tools = _tools(out)
        assert "quickshell_coding_assistant" not in tools, request
        # Multiple compat steps are fine (one per API); checking the same API
        # twice would be a redundant call, so no two compat steps may share a
        # reason.
        compat_reasons = [
            entry["reason"]
            for entry in out["orchestration"]
            if entry["tool"] == "quickshell_check_compatibility"
        ]
        assert len(compat_reasons) == len(set(compat_reasons)), (request, compat_reasons)


def test_safe_step_budget_caps_steps():
    trace, errors = [], {}
    for _ in range(assistant._MAX_STEPS):
        assert assistant._safe_step(trace, errors, "t", "r", lambda: {"ok": 1}, "dict") is not None
    assert assistant._safe_step(trace, errors, "t", "r", lambda: {"ok": 1}, "dict") is None
    assert trace[-1]["tool"] == "step-budget"
    assert errors == {}


def test_safe_step_records_error_and_malformed():
    trace, errors = [], {}

    def raise_error():
        raise RuntimeError("boom")

    assert assistant._safe_step(trace, errors, "boom", "r", raise_error, "dict") is None
    assert errors == {"boom": "boom"}
    assert trace[-1]["status"] == "error"

    assert assistant._safe_step(trace, errors, "bad", "r", lambda: "not a dict", "dict") is None
    assert trace[-1]["status"] == "malformed"


def test_wrapper_records_stats(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    before = dict(srv._TOOL_CALLS)
    srv.quickshell_coding_assistant("What is PanelWindow?")
    expected = before.get("quickshell_coding_assistant", 0) + 1
    assert srv._TOOL_CALLS["quickshell_coding_assistant"] == expected


def test_grounded_result_build(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._coding_assistant("Build a Hyprland workspace bar")
    grounded = out["grounded_result"]
    assert grounded["kind"] == "qml_component"
    assert "import Quickshell.Hyprland" in grounded["qml"]
    assert grounded["filename"].endswith(".qml")
    assert grounded["verified"] is True


def test_grounded_result_research(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._coding_assistant("What is PanelWindow?")
    grounded = out["grounded_result"]
    assert grounded["kind"] == "reference"
    assert any(t["type_name"] == "PanelWindow" for t in grounded["types"])


def test_grounded_result_debug(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._coding_assistant(
        "Why is this PanelWindow failing?",
        error="Cannot assign to non-existent property 'foo'",
        code="PanelWindow { foo: 1 }",
    )
    grounded = out["grounded_result"]
    assert grounded["kind"] == "diagnosis"
    assert grounded["category"] == "non_existent_property"
    assert "foo" in grounded["fix"]


def test_grounded_result_pattern(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._coding_assistant("Find an implementation of a volume OSD and adapt the pattern")
    grounded = out["grounded_result"]
    assert grounded["kind"] == "implementation_pattern"
    assert grounded["excerpt"]
    assert grounded["path"]


def test_grounded_result_migrate_with_code(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._coding_assistant(
        "Migrate this shell",
        code='Quickshell { shellRoot: "/etc" }',
        from_version="v0.1.0",
        to_version="v0.3.1",
    )
    grounded = out["grounded_result"]
    assert grounded["kind"] == "migration_plan"
    assert grounded["from_version"] == "v0.1.0"
    assert grounded["to_version"] == "v0.3.1"
    assert grounded["plan"]


def test_grounded_result_migrate_without_code(monkeypatch, docs_fixture_urls):
    _install(monkeypatch, docs_fixture_urls)
    out = srv._coding_assistant("Migrate this shell from v0.2 to v0.3")
    grounded = out["grounded_result"]
    assert grounded["kind"] == "migration_guidance"
    assert grounded["breaking"]


def test_pipeline_stage_activation(monkeypatch, docs_fixture_urls):
    """Research activates search+verify but not generate/validate/migrate."""
    _install(monkeypatch, docs_fixture_urls)
    out = srv._coding_assistant("What is PanelWindow?")
    tools = _tools(out)
    assert "quickshell_search_all" in tools
    assert "quickshell_check_compatibility" in tools
    assert "quickshell_generate_component" not in tools
    assert "quickshell_validate_qml" not in tools
    assert "quickshell_migrate" not in tools
