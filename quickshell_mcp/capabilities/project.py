"""The project capability: analyze a Quickshell project on disk.

Provides structured project intelligence built on the shared
``ProjectContext``: an overview, a static relationship map, project-scoped
search, dependency classification, and config-convention detection. All
tools are read-only and never modify the project.

Depends on: knowledge (project search reuses the shared search/index
infrastructure).
"""

from __future__ import annotations

from ..sources.project import (  # noqa: F401
    _ALL_FIELDS,
    _build_project_context,
    _ProjectContext,
)
from ..sources.project_intel import (  # noqa: F401
    _analyze_project,
    _config_conventions,
    _map_project,
    _project_dependencies,
    _search_project,
)
from ..sources.project_validate import (  # noqa: F401
    _lint_project,
    _migrate_project,
    _project_compatibility,
    _validate_project,
)

CAPABILITY_NAME = "project"
CAPABILITY_TOOLS = (
    "quickshell_project_analyze",
    "quickshell_project_map",
    "quickshell_project_find",
    "quickshell_project_dependencies",
    "quickshell_project_config",
    "quickshell_project_validate",
    "quickshell_project_lint",
    "quickshell_project_compatibility",
    "quickshell_project_migrate",
)
CAPABILITY_DEPENDS_ON = ("knowledge", "validation")
