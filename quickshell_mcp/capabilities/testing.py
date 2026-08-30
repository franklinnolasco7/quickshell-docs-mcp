"""The testing capability: run machine-readable runtime tests against a
managed Quickshell session.

Provides test steps (find, interact, wait, assert, screenshot), suites with
isolation, assertion primitives, reusable macros, recording, and structured
reports. Mutating: running tests drives the runtime session.

Depends on: knowledge, project, runtime, inspection.
"""

from __future__ import annotations

from ..sources.runtime_test import (  # noqa: F401
    _assert_snapshot,
    _run_macro_test,
    _run_test,
    _run_test_suite,
    _test_macro,
    _test_record,
    _test_report,
)

CAPABILITY_NAME = "testing"
CAPABILITY_TOOLS = (
    "quickshell_test",
    "quickshell_test_suite",
    "quickshell_assert",
    "quickshell_test_macro",
    "quickshell_test_record",
    "quickshell_test_report",
)
CAPABILITY_DEPENDS_ON = ("knowledge", "project", "runtime", "inspection")
