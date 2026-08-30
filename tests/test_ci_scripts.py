"""Tests for the CI entrypoint scripts (E3): validation, screenshot
regression, runtime test, API compatibility, and migration.

Each script exposes a ``run()`` function separate from its argparse ``main``
so the logic is testable offline by monkeypatching the underlying sources
helper it wraps. Exit codes are asserted: 0 = pass, 1 = fail/regression,
2 = operational error.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))


def _load(name: str):
    return importlib.import_module(name)


def _validate_result(errors: int, warnings: int) -> dict:
    return {"summary": {"errors": errors, "warnings": warnings, "infos": 0}, "files": {"a.qml": {}}}


def _screenshot_diff(differs: bool, metric: int) -> dict:
    return {"differs": differs, "metric": metric, "diff_path": "/d.png", "note": None}


# ---------------------------------------------------------------------------
# ci_validate
# ---------------------------------------------------------------------------


def test_ci_validate_pass(monkeypatch, capsys):
    ci = _load("ci_validate")
    monkeypatch.setattr(
        "quickshell_mcp.sources.project_validate._validate_project",
        lambda p, version="latest": _validate_result(0, 1),
    )
    assert ci.run("/tmp/x") == 0
    assert "[PASS]" in capsys.readouterr().err


def test_ci_validate_fail(monkeypatch, capsys):
    ci = _load("ci_validate")
    monkeypatch.setattr(
        "quickshell_mcp.sources.project_validate._validate_project",
        lambda p, version="latest": _validate_result(2, 0),
    )
    assert ci.run("/tmp/x") == 1
    assert "[FAIL]" in capsys.readouterr().err


def test_ci_validate_error(monkeypatch):
    ci = _load("ci_validate")

    def _boom(p, version="latest"):
        raise RuntimeError("nope")

    monkeypatch.setattr("quickshell_mcp.sources.project_validate._validate_project", _boom)
    assert ci.run("/tmp/x") == 2


# ---------------------------------------------------------------------------
# ci_screenshot
# ---------------------------------------------------------------------------


def test_ci_screenshot_pass(monkeypatch, capsys):
    ci = _load("ci_screenshot")
    monkeypatch.setattr(
        "quickshell_mcp.sources.ui_runtime._screenshot_diff",
        lambda b, a, output=None: _screenshot_diff(False, 0),
    )
    assert ci.run("/b.png", "/a.png", threshold=0) == 0
    assert "[PASS]" in capsys.readouterr().err


def test_ci_screenshot_regression(monkeypatch, capsys):
    ci = _load("ci_screenshot")
    monkeypatch.setattr(
        "quickshell_mcp.sources.ui_runtime._screenshot_diff",
        lambda b, a, output=None: _screenshot_diff(True, 50),
    )
    assert ci.run("/b.png", "/a.png", threshold=10) == 1
    assert "[FAIL]" in capsys.readouterr().err


def test_ci_screenshot_within_threshold(monkeypatch):
    ci = _load("ci_screenshot")
    monkeypatch.setattr(
        "quickshell_mcp.sources.ui_runtime._screenshot_diff",
        lambda b, a, output=None: _screenshot_diff(True, 5),
    )
    assert ci.run("/b.png", "/a.png", threshold=10) == 0


# ---------------------------------------------------------------------------
# ci_runtime_test
# ---------------------------------------------------------------------------


class _FakeSession:
    status = "running"
    session_id = "ci-test-1"

    def to_dict(self):
        return {"session_id": self.session_id, "status": self.status}


def _fake_runtime_session(monkeypatch, pass_count: int) -> None:
    monkeypatch.setattr(
        "quickshell_mcp.sources.runtime_session._start_session", lambda p: _FakeSession()
    )
    monkeypatch.setattr(
        "quickshell_mcp.sources.runtime_test._run_test_suite",
        lambda sid, tests: {
            "total": 2,
            "passed": pass_count,
            "failed": 2 - pass_count,
            "results": [],
        },
    )
    monkeypatch.setattr("quickshell_mcp.sources.runtime_session._stop_session", lambda s: None)


def test_ci_runtime_test_pass(monkeypatch, capsys):
    ci = _load("ci_runtime_test")
    _fake_runtime_session(monkeypatch, pass_count=2)
    assert ci.run("/tmp/x", [{"name": "t"}]) == 0
    assert "[PASS]" in capsys.readouterr().err


def test_ci_runtime_test_fail(monkeypatch, capsys):
    ci = _load("ci_runtime_test")
    _fake_runtime_session(monkeypatch, pass_count=1)
    assert ci.run("/tmp/x", [{"name": "t"}]) == 1
    assert "[FAIL]" in capsys.readouterr().err


def test_ci_runtime_test_start_error(monkeypatch):
    ci = _load("ci_runtime_test")

    class _ErrSession:
        status = "error"
        session_id = "err-1"

        def to_dict(self):
            return {"status": "error"}

    monkeypatch.setattr(
        "quickshell_mcp.sources.runtime_session._start_session", lambda p: _ErrSession()
    )
    assert ci.run("/tmp/x", []) == 2


# ---------------------------------------------------------------------------
# ci_api_compat
# ---------------------------------------------------------------------------


def test_ci_api_compat_pass(monkeypatch, capsys):
    ci = _load("ci_api_compat")
    monkeypatch.setattr(
        "quickshell_mcp.sources.compat._check_compatibility",
        lambda **k: {"change_info": {"status": "compatible"}},
    )
    assert ci.run(["PanelWindow"], version="v0.3.1") == 0
    assert "[PASS]" in capsys.readouterr().err


def test_ci_api_compat_confirmed(monkeypatch, capsys):
    ci = _load("ci_api_compat")
    monkeypatch.setattr(
        "quickshell_mcp.sources.compat._check_compatibility",
        lambda **k: {
            "change_info": {
                "status": "removed",
                "detail": "removed in v0.3.0",
                "documentation": [{"url": "https://x/y"}],
            }
        },
    )
    assert ci.run(["LegacyThing"], version="v0.3.1") == 1
    assert "[FAIL]" in capsys.readouterr().err


def test_ci_api_compat_unknown(monkeypatch):
    ci = _load("ci_api_compat")
    monkeypatch.setattr(
        "quickshell_mcp.sources.compat._check_compatibility",
        lambda **k: {"change_info": {"status": "not_found"}},
    )
    assert ci.run(["NoSuchThing"], version="v0.3.1") == 0


# ---------------------------------------------------------------------------
# ci_migration
# ---------------------------------------------------------------------------


def test_ci_migration_pass(monkeypatch, capsys):
    ci = _load("ci_migration")
    monkeypatch.setattr(
        "quickshell_mcp.sources.project_validate._migrate_project",
        lambda p, f, t: {"issues": []},
    )
    assert ci.run("/tmp/x", "v0.2.0", "v0.3.1") == 0
    assert "[PASS]" in capsys.readouterr().err


def test_ci_migration_breaking(monkeypatch, capsys):
    ci = _load("ci_migration")
    monkeypatch.setattr(
        "quickshell_mcp.sources.project_validate._migrate_project",
        lambda p, f, t: {"issues": [{"status": "renamed", "old_api": "A", "new_api": "B"}]},
    )
    assert ci.run("/tmp/x", "v0.2.0", "v0.3.1") == 1
    assert "[FAIL]" in capsys.readouterr().err


def test_ci_migration_error(monkeypatch):
    ci = _load("ci_migration")

    def _boom(p, f, t):
        raise RuntimeError("bad")

    monkeypatch.setattr("quickshell_mcp.sources.project_validate._migrate_project", _boom)
    assert ci.run("/tmp/x", "v0.2.0", "v0.3.1") == 2
