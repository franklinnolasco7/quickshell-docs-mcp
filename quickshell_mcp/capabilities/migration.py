"""The migration capability: analyse what code must change between versions.

Depends on: knowledge, validation (migration uses compat, docs, and validate).
"""

from __future__ import annotations

from ..sources.migrate import (  # noqa: F401
    _behavioral_scan,
    _collect_api_refs,
    _import_diff,
    _migrate,
    _migration_plan,
    _symbol_issue,
)

CAPABILITY_NAME = "migration"
CAPABILITY_TOOLS = ("quickshell_migrate",)
CAPABILITY_DEPENDS_ON = ("knowledge", "validation")
