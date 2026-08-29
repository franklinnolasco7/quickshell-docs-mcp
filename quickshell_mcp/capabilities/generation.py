"""The generation capability: produce grounded QML component code.

Depends on: knowledge, validation (generation uses compat, find_pattern,
search_all, and validate).
"""

from __future__ import annotations

from ..sources.generate import (  # noqa: F401
    _build_section,
    _generate_component,
    _interpret_component_query,
)

CAPABILITY_NAME = "generation"
CAPABILITY_TOOLS = ("quickshell_generate_component",)
CAPABILITY_DEPENDS_ON = ("knowledge", "validation")
