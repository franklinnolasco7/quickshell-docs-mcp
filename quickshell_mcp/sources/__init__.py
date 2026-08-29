"""Shared services layer: data-source access, index building, parsing, and
low-level analysis that the capability modules in ``capabilities/`` compose.
No MCP decorators live here, and no module in this package imports from
``capabilities/`` (the dependency direction is one-way: down)."""
