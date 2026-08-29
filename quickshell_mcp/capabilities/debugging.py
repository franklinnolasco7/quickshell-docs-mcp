"""The debugging capability: explain QML errors and suggest fixes.

Depends on: knowledge (debugging uses the docs and Qt indexes).
"""

from __future__ import annotations

from ..sources.explain_error import (  # noqa: F401
    _categorize_error,
    _explain_error,
    _extract_type_from_code,
)

CAPABILITY_NAME = "debugging"
CAPABILITY_TOOLS = ("quickshell_explain_error",)
CAPABILITY_DEPENDS_ON = ("knowledge",)
