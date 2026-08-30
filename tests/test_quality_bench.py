"""Tests for the E4 hardening artifacts: the per-tool quality audit script,
the end-to-end benchmark script, and the registry thread-safety locks.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    return importlib.import_module(name)


# ---------------------------------------------------------------------------
# quality_audit
# ---------------------------------------------------------------------------


def test_quality_audit_finds_tools(capsys, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["quality_audit.py"])
    qa = _load("quality_audit")
    code = qa.main()
    out = capsys.readouterr().out
    assert "quickshell_validate_qml" in out
    assert "quickshell_stats" in out
    assert "Tool quality audit" in out
    assert code in (0, 1)


def test_all_tools_have_docstrings():
    import quickshell_mcp.server as srv

    missing = [
        t.name for t in srv.mcp._tool_manager.list_tools() if not getattr(t, "__doc__", None)
    ]
    assert not missing, f"tools missing docstrings: {missing}"


# ---------------------------------------------------------------------------
# benchmark
# ---------------------------------------------------------------------------


def test_benchmark_reports_metrics(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["benchmark.py"])
    bm = _load("benchmark")

    class _DummyTool:
        name = "quickshell_validate_qml"

    monkeypatch.setattr(
        "quickshell_mcp.server.quickshell_list_versions",
        lambda: {"all_versions": ["v0.3.1", "v0.2.0"]},
    )
    monkeypatch.setattr(
        "quickshell_mcp.server.quickshell_validate_qml",
        lambda *a, **k: {"diagnostics": []},
    )
    monkeypatch.setattr(
        "quickshell_mcp.server.quickshell_check_compatibility",
        lambda **k: {"change_info": {"status": "compatible"}},
    )
    monkeypatch.setattr(
        "quickshell_mcp.server.quickshell_search",
        lambda *a, **k: {"namespace_matches": ["Quickshell.Services.Pam"]},
    )
    # Inject a fake tool list so the count is deterministic.
    fake_tools = [_DummyTool()] * 60
    monkeypatch.setattr("quickshell_mcp.server.mcp._tool_manager.list_tools", lambda: fake_tools)

    code = bm.main()
    out = capsys.readouterr().out
    assert "tool_count: 60" in out
    assert "End-to-end benchmark" in out
    assert code in (0, 1)


def test_benchmark_recovers_from_failure(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["benchmark.py"])
    bm = _load("benchmark")

    def _boom(*a, **k):
        raise ValueError("syntax error")

    monkeypatch.setattr("quickshell_mcp.server.quickshell_validate_qml", _boom)
    monkeypatch.setattr(
        "quickshell_mcp.server.quickshell_list_versions",
        lambda: {"all_versions": ["v0.3.1"]},
    )
    monkeypatch.setattr(
        "quickshell_mcp.server.quickshell_check_compatibility",
        lambda **k: {"change_info": {"status": "compatible"}},
    )
    monkeypatch.setattr(
        "quickshell_mcp.server.quickshell_search",
        lambda *a, **k: {"namespace_matches": []},
    )
    monkeypatch.setattr("quickshell_mcp.server.mcp._tool_manager.list_tools", lambda: [])
    code = bm.main()
    out = capsys.readouterr().out
    assert "recovery: raised-ValueError" in out
    assert code in (0, 1)


# ---------------------------------------------------------------------------
# Thread-safety locks
# ---------------------------------------------------------------------------


def test_session_registry_has_lock():
    from quickshell_mcp.sources import runtime_session as rs

    assert hasattr(rs, "_SESSION_LOCK")


def test_profile_registry_has_lock():
    from quickshell_mcp.sources import ecosystem as eco

    assert hasattr(eco, "_PROFILE_LOCK")


def test_memory_registry_has_lock():
    from quickshell_mcp.sources import project_memory as pm

    assert hasattr(pm, "_MEMORY_LOCK")
