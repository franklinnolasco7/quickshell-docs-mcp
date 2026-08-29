"""Capability / domain layer.

Each capability module sits between the MCP tool wrappers in ``server.py``
and the shared services in ``sources/``.  Capabilities own the tool-to-domain
mapping, declare explicit inter-capability dependencies, and re-export the
entry-point helpers that the tool wrappers call.

The dependency graph among implemented capabilities is acyclic:

    knowledge (root)
        ├── validation
        ├── debugging
    validation ──┬── generation
                 └── migration
    knowledge, validation, debugging, generation, migration ── assistant
"""

from . import (
    assistant,
    debugging,
    generation,
    knowledge,
    migration,
    registry,
    validation,
)

__all__ = [
    "assistant",
    "debugging",
    "generation",
    "knowledge",
    "migration",
    "registry",
    "validation",
]
