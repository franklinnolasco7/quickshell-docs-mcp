"""The performance capability: bounded runtime profiling and static analysis.

``profile`` samples a managed session's CPU/memory from /proc over a bounded
window. Component, binding, timer, object-tree, and diagnose analyses are
evidence-based and never attribute cost without evidence. All tools are
read-only.

Depends on: knowledge, project, runtime.
"""

from __future__ import annotations

from ..sources.perf_profile import (  # noqa: F401
    _performance_diagnose,
    _profile,
    _profile_bindings,
    _profile_component,
    _profile_object_tree,
    _profile_timers,
)

CAPABILITY_NAME = "performance"
CAPABILITY_TOOLS = (
    "quickshell_profile",
    "quickshell_profile_component",
    "quickshell_profile_bindings",
    "quickshell_profile_timers",
    "quickshell_profile_object_tree",
    "quickshell_performance_diagnose",
)
CAPABILITY_DEPENDS_ON = ("knowledge", "project", "runtime")
