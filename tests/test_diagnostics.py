"""Tests for the structured diagnostic model: serialization, field presence,
ordering, and severity filtering across validate and migrate diagnostics.

These tests focus on the shared diagnostic surface (file, related_location,
code, severity, ordering). Core validation logic and migration logic are
tested in test_validate.py and test_migrate.py respectively.
"""

from __future__ import annotations

import quickshell_mcp.server as srv
from quickshell_mcp.sources.validate import _diag, _Diagnostic


def _diag_kwds(
    *, severity: str, code: str, message: str, line: int | None, column: int | None
) -> dict:
    return dict(
        severity=severity,
        code=code,
        message=message,
        line=line,
        column=column,
        type=None,
        api=None,
        alternatives=[],
        source=None,
        confidence="medium",
        could_not_verify=False,
    )


# ---------------------------------------------------------------------------
# _Diagnostic serialization
# ---------------------------------------------------------------------------


def test_diagnostic_to_dict_includes_new_fields():
    d = _Diagnostic(
        severity="warning",
        code="test_code",
        message="test message",
        line=1,
        column=5,
        type="TestType",
        api="testApi",
        alternatives=[],
        source=None,
        confidence="medium",
        could_not_verify=False,
        suggestion="try X instead",
        file="test.qml",
        related_location={"line": 3, "column": 10},
    )
    serialized = d.to_dict()
    assert serialized["file"] == "test.qml"
    assert serialized["related_location"] == {"line": 3, "column": 10}
    assert serialized["suggestion"] == "try X instead"
    assert serialized["code"] == "test_code"
    assert serialized["severity"] == "warning"
    assert serialized["message"] == "test message"


def test_diagnostic_new_fields_default_to_none():
    d = _Diagnostic(
        severity="error",
        code="missing_field",
        message="something is missing",
        line=None,
        column=None,
        type=None,
        api=None,
        alternatives=[],
        source=None,
        confidence="high",
        could_not_verify=False,
    )
    serialized = d.to_dict()
    assert serialized["file"] is None
    assert serialized["related_location"] is None
    assert serialized["suggestion"] is None


def test_diag_factory_accepts_file_and_related_location():
    d = _diag(
        severity="info",
        code="custom",
        message="a custom diagnostic",
        line=10,
        column=3,
        type="Custom",
        api="customProp",
        alternatives=["use X"],
        source={"text": "quickshell.org", "url": "https://example.com"},
        confidence="high",
        file="component.qml",
        related_location={"line": 5, "column": 1},
    )
    assert d.file == "component.qml"
    assert d.related_location == {"line": 5, "column": 1}
    assert d.to_dict()["file"] == "component.qml"


# ---------------------------------------------------------------------------
# Validate file stamping
# ---------------------------------------------------------------------------


def test_validate_stamps_file_on_diagnostics(docs_fixture_urls, mock_fetch):
    mock_fetch(docs_fixture_urls)
    result = srv._validate("PanelWindow {", filename="test_shell.qml")
    assert result["diagnostics"], "expected at least one diagnostic"
    for diag in result["diagnostics"]:
        assert diag.get("file") == "test_shell.qml", f"diag {diag['code']} missing file"


def test_validate_without_filename_file_is_none(docs_fixture_urls, mock_fetch):
    mock_fetch(docs_fixture_urls)
    result = srv._validate("PanelWindow {")
    assert result["diagnostics"], "expected at least one diagnostic"
    for diag in result["diagnostics"]:
        assert diag.get("file") is None, f"diag {diag['code']} has unexpected file"


# ---------------------------------------------------------------------------
# Diagnostic ordering
# ---------------------------------------------------------------------------


def test_diagnostics_ordered_by_line_column_severity():
    kwargs = _diag_kwds
    diags = [
        _diag(**kwargs(severity="error", code="e1", message="e1", line=2, column=1)),
        _diag(**kwargs(severity="info", code="i1", message="i1", line=1, column=1)),
        _diag(**kwargs(severity="warning", code="w1", message="w1", line=1, column=5)),
        _diag(**kwargs(severity="error", code="e2", message="e2", line=1, column=1)),
    ]
    diags.sort(
        key=lambda d: (
            d.line or 10**9,
            d.column or 10**9,
            {"error": 0, "warning": 1, "info": 2}.get(d.severity, 3),
        )
    )
    codes = [d.code for d in diags]
    assert codes == ["e2", "i1", "w1", "e1"], f"got {codes}"


# ---------------------------------------------------------------------------
# Migration issue file stamping
# ---------------------------------------------------------------------------


def test_migrate_stamps_file_on_issues(monkeypatch, docs_fixture_urls):
    from test_migrate import _build_mapping, _migrate

    mapping = _build_mapping(docs_fixture_urls)
    report = _migrate(
        mapping,
        monkeypatch,
        code='import Quickshell\nQuickshell {\n    shellRoot: "/etc"\n}',
        from_version="v0.1.0",
        to_version="v0.3.1",
        filename="test_shell.qml",
    )
    for issue in report["issues"]:
        assert issue.get("file") == "test_shell.qml", f"issue {issue['status']} missing file"


def test_migrate_without_filename_file_is_none(monkeypatch, docs_fixture_urls):
    from test_migrate import _build_mapping, _migrate

    mapping = _build_mapping(docs_fixture_urls)
    report = _migrate(
        mapping,
        monkeypatch,
        api="Quickshell.shellRoot",
        from_version="v0.1.0",
        to_version="v0.3.1",
    )
    for issue in report["issues"]:
        assert issue.get("file") is None, f"issue {issue['status']} has unexpected file"


# ---------------------------------------------------------------------------
# Severity filtering
# ---------------------------------------------------------------------------


def test_diagnostics_severity_filter():
    kwargs = _diag_kwds
    diags = [
        _diag(**kwargs(severity="error", code="e1", message="e1", line=1, column=1)),
        _diag(**kwargs(severity="warning", code="w1", message="w1", line=2, column=1)),
        _diag(**kwargs(severity="info", code="i1", message="i1", line=3, column=1)),
    ]
    errors = [d for d in diags if d.severity == "error"]
    warnings = [d for d in diags if d.severity == "warning"]
    infos = [d for d in diags if d.severity == "info"]
    assert len(errors) == 1
    assert len(warnings) == 1
    assert len(infos) == 1
