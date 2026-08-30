"""The generation capability: produce grounded QML component code.

Depends on: knowledge, validation (generation uses compat, find_pattern,
search_all, and validate).
"""

from __future__ import annotations

from ..sources.generate import (  # noqa: F401
    _build_section,
    _generate_component,
    _generate_panel,
    _generate_service,
    _interpret_component_query,
)
from ..sources.refactor import _apply_patch, _refactor  # noqa: F401
from ..sources.style_match import _style_match  # noqa: F401

CAPABILITY_NAME = "generation"
CAPABILITY_TOOLS = (
    "quickshell_generate_component",
    "quickshell_generate_service",
    "quickshell_generate_panel",
    "quickshell_refactor",
    "quickshell_apply_patch",
    "quickshell_style_match",
)
CAPABILITY_DEPENDS_ON = ("knowledge", "validation")
