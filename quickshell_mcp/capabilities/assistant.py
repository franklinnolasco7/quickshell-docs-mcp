"""The assistant capability: orchestrate a plain-language request across every
other capability.

Depends on: knowledge, validation, generation, migration, debugging.
"""

from __future__ import annotations

from ..sources.assistant import (  # noqa: F401
    _classify_intent,
    _coding_assistant,
    _detect_compositor,
    _project_info,
    _resolve_version_hint,
    _safe_step,
)
from ..sources.project import _build_project_context  # noqa: F401

CAPABILITY_NAME = "assistant"
CAPABILITY_TOOLS = ("quickshell_coding_assistant",)
CAPABILITY_DEPENDS_ON = ("knowledge", "validation", "generation", "migration", "debugging")
