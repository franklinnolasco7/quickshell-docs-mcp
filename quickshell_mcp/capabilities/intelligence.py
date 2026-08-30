"""The intelligence capability: project memory, architecture
recommendations, regression detection, root-cause correlation, and
inspect-before-modify task planning.

Memory is explicit, evidence-backed, and session-scoped (inspectable and
resettable). Architecture recommendations and regressions cite their
evidence; root-cause correlation separates inferred hypotheses from observed
evidence; the task planner never executes anything.

Depends on: knowledge, project, validation, runtime, inspection.
"""

from __future__ import annotations

from ..sources.intelligence import (  # noqa: F401
    _root_cause,
    _task_plan,
)
from ..sources.project_memory import (  # noqa: F401
    _architecture,
    _memory_clear,
    _memory_get,
    _memory_list,
    _memory_reset,
    _memory_save,
    _regression,
)

CAPABILITY_NAME = "intelligence"
CAPABILITY_TOOLS = (
    "quickshell_project_memory",
    "quickshell_project_architecture",
    "quickshell_regression_detect",
    "quickshell_root_cause",
    "quickshell_task_plan",
)
CAPABILITY_DEPENDS_ON = ("knowledge", "project", "validation", "runtime", "inspection")
