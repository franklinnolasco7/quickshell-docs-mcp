"""The agent capability: high-level orchestration tools that compose the
existing per-source helpers into end-to-end operations.

Each tool runs an explicit staged plan with per-step results and failure
isolation, delegating to the lower-level capabilities (project, knowledge,
generation, validation, migration, debugging, runtime, testing, performance)
without duplicating their logic.

Depends on: the capabilities whose helpers these tools orchestrate.
"""

from __future__ import annotations

from ..sources.agent_tools import (  # noqa: F401
    _build_feature,
    _debug,
    _migrate_project,
    _optimize,
    _test_feature,
)

CAPABILITY_NAME = "agent"
CAPABILITY_TOOLS = (
    "quickshell_build_feature",
    "quickshell_debug",
    "quickshell_migrate_project",
    "quickshell_test_feature",
    "quickshell_optimize",
)
CAPABILITY_DEPENDS_ON = (
    "knowledge",
    "knowledge2",
    "validation",
    "generation",
    "migration",
    "debugging",
    "project",
    "runtime",
    "testing",
    "performance",
)
