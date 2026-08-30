"""The ecosystem capability: runtime dependency detection, Nix-aware
diagnostics, and a named/versioned/inspectable runtime profile registry.

Nix diagnostics and runtime dependency detection are read-only and safe
(file-based, nothing is executed). The profile registry is an in-memory
named/versioned/inspectable registry with import/export; only the registry
state (in this process) is mutated.

Depends on: project (runtime dependency detection reuses the project
context scanner).
"""

from __future__ import annotations

from ..sources.ecosystem import (  # noqa: F401
    _nix_diagnostics,
    _profile_delete,
    _profile_export,
    _profile_get,
    _profile_import,
    _profile_list,
    _profile_save,
    _runtime_dependencies,
)

CAPABILITY_NAME = "ecosystem"
CAPABILITY_TOOLS = (
    "quickshell_nix_diagnostics",
    "quickshell_runtime_dependencies",
    "quickshell_profile_save",
    "quickshell_profile_list",
    "quickshell_profile_get",
    "quickshell_profile_delete",
    "quickshell_profile_export",
    "quickshell_profile_import",
)
CAPABILITY_DEPENDS_ON = ("project",)
