"""Capability registry: the boundary map between MCP tools and the domain layer.

Each capability module (``knowledge``, ``validation``, ``generation``,
``migration``, ``debugging``, ``assistant``) declares which tools it owns and
which other capabilities it depends on. This module aggregates those
declarations into a single map plus a cycle-checked topological ordering, so
server.py and tests can answer "which capability owns this tool?" and prove
the capability graph is acyclic.

Capabilities that are planned but not implemented yet (project, runtime,
inspection, testing, performance) are registered with ``status="planned"`` and
no tools. No modules are created for them until the features land.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import assistant, debugging, generation, knowledge, migration, validation

__all__ = [
    "ALL_CAPABILITIES",
    "CAPABILITIES",
    "Capability",
    "PLANNED_CAPABILITIES",
    "capability_for_tool",
    "dependency_order",
]


@dataclass(frozen=True)
class Capability:
    name: str
    tools: tuple[str, ...]
    depends_on: tuple[str, ...]
    status: str = "implemented"


_CAPABILITY_MODULES = (
    knowledge,
    validation,
    generation,
    migration,
    debugging,
    assistant,
)

CAPABILITIES: dict[str, Capability] = {
    mod.CAPABILITY_NAME: Capability(
        name=mod.CAPABILITY_NAME,
        tools=mod.CAPABILITY_TOOLS,
        depends_on=mod.CAPABILITY_DEPENDS_ON,
    )
    for mod in _CAPABILITY_MODULES
}

PLANNED_CAPABILITIES: dict[str, Capability] = {
    name: Capability(name=name, tools=(), depends_on=(), status="planned")
    for name in ("project", "runtime", "inspection", "testing", "performance")
}

ALL_CAPABILITIES: dict[str, Capability] = {**CAPABILITIES, **PLANNED_CAPABILITIES}

# `quickshell_stats` reports session telemetry and lives entirely in server.py;
# it is not owned by any domain capability.
_SYSTEM_TOOLS = ("quickshell_stats",)


def capability_for_tool(tool: str) -> str | None:
    """Return the capability that owns *tool*, or None for system tools."""
    for cap in CAPABILITIES.values():
        if tool in cap.tools:
            return cap.name
    return None


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
