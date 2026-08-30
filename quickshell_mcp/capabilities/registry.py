"""Capability registry: the boundary map between MCP tools and the domain layer.

Each capability module (``knowledge``, ``validation``, ``generation``,
``migration``, ``debugging``, ``assistant``) declares which tools it owns and
which other capabilities it depends on. This module aggregates those
declarations into a single map plus a cycle-checked topological ordering, so
server.py and tests can answer "which capability owns this tool?" and prove
the capability graph is acyclic.

Capabilities that are planned but not implemented yet (runtime, inspection,
testing, performance) are registered with ``status="planned"`` and no tools.
No modules are created for them until the features land.

Every capability carries a ``safety_level``:

* **read-only** — analysis only; no state changes, no file writes, no process
  execution (default for all capabilities today).
* **mutating** — alters live state (runtime sessions, explicit file writes via
  ``apply_patch``). Requires explicit invocation.
* **high-risk** — arbitrary evaluation or destructive filesystem operations.
  Reserved for future eval/patch capabilities; not yet assigned.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import (
    adapters,
    agent,
    assistant,
    debugging,
    ecosystem,
    generation,
    inspection,
    knowledge,
    knowledge2,
    migration,
    performance,
    project,
    runtime,
    testing,
    validation,
)

__all__ = [
    "ALL_CAPABILITIES",
    "CAPABILITIES",
    "Capability",
    "PLANNED_CAPABILITIES",
    "SAFETY_LEVELS",
    "capability_for_tool",
    "classify_capability",
    "dependency_order",
    "safety_level_for_tool",
]


@dataclass(frozen=True)
class Capability:
    name: str
    tools: tuple[str, ...]
    depends_on: tuple[str, ...]
    status: str = "implemented"
    safety_level: str = "read-only"


# Mutating capabilities alter live state rather than only reading project/docs.
# high-risk is not yet assigned to any capability; it is reserved for future
# evaluation/patch capabilities.
_MUTATING_CAPABILITIES = ("runtime", "testing")

# Per-tool safety overrides.  A tool listed here overrides its owning
# capability's default safety level.
_TOOL_SAFETY_LEVELS: dict[str, str] = {
    "quickshell_apply_patch": "mutating",
    "quickshell_ui_set_property": "mutating",
    "quickshell_ui_invoke": "mutating",
    "quickshell_ui_eval": "high-risk",
}


def _safety_level(name: str) -> str:
    return "mutating" if name in _MUTATING_CAPABILITIES else "read-only"


_CAPABILITY_MODULES = (
    knowledge,
    knowledge2,
    validation,
    generation,
    migration,
    debugging,
    project,
    runtime,
    inspection,
    testing,
    performance,
    adapters,
    ecosystem,
    agent,
    assistant,
)

CAPABILITIES: dict[str, Capability] = {
    mod.CAPABILITY_NAME: Capability(
        name=mod.CAPABILITY_NAME,
        tools=mod.CAPABILITY_TOOLS,
        depends_on=mod.CAPABILITY_DEPENDS_ON,
        safety_level=_safety_level(mod.CAPABILITY_NAME),
    )
    for mod in _CAPABILITY_MODULES
}

PLANNED_CAPABILITIES: dict[str, Capability] = {}

ALL_CAPABILITIES: dict[str, Capability] = {**CAPABILITIES, **PLANNED_CAPABILITIES}

# Convenience dict derived from the authoritative dataclass fields.
SAFETY_LEVELS: dict[str, str] = {name: cap.safety_level for name, cap in ALL_CAPABILITIES.items()}

# `quickshell_stats` reports session telemetry and lives entirely in server.py;
# it is not owned by any domain capability.
_SYSTEM_TOOLS = ("quickshell_stats",)


def capability_for_tool(tool: str) -> str | None:
    """Return the capability that owns *tool*, or None for system tools."""
    for cap in CAPABILITIES.values():
        if tool in cap.tools:
            return cap.name
    return None


def classify_capability(name: str) -> str:
    """Return the safety level of a registered capability.

    Levels: ``read-only`` (analysis), ``mutating`` (changes live state),
    ``high-risk`` (arbitrary evaluation or file mutation; not yet assigned).
    """
    cap = ALL_CAPABILITIES.get(name)
    if cap is None:
        raise ValueError(f"Unknown capability '{name}'")
    return cap.safety_level


def safety_level_for_tool(tool: str) -> str:
    """Return the safety level of the capability owning *tool*.

    A per-tool override (``_TOOL_SAFETY_LEVELS``) wins; otherwise the level
    is inherited from the owning capability. System tools (e.g.
    ``quickshell_stats``) are telemetry and are always classified read-only.
    """
    if tool in _TOOL_SAFETY_LEVELS:
        return _TOOL_SAFETY_LEVELS[tool]
    cap = capability_for_tool(tool)
    if cap is not None:
        return classify_capability(cap)
    if tool in _SYSTEM_TOOLS:
        return "read-only"
    raise ValueError(f"Unknown tool '{tool}'")


def dependency_order() -> list[str]:
    """Topologically order the implemented capabilities (raises on a cycle)."""
    graph = {name: set(cap.depends_on) for name, cap in CAPABILITIES.items()}
    for name, deps in graph.items():
        missing = deps - set(CAPABILITIES)
        if missing:
            raise ValueError(f"capability {name!r} depends on unregistered {sorted(missing)!r}")
    order: list[str] = []
    resolved: set[str] = set()
    while len(order) < len(graph):
        progress = False
        for name, deps in graph.items():
            if name in resolved:
                continue
            if deps <= resolved:
                order.append(name)
                resolved.add(name)
                progress = True
        if not progress:
            cycle = sorted(set(graph) - resolved)
            raise ValueError(f"circular capability dependency: {cycle}")
    return order
