"""The debugging capability: explain QML errors and diagnose runtime problems.

Owns both static error explanation (``quickshell_explain_error``) and runtime
debugging (``quickshell_runtime_diagnose``, ``quickshell_runtime_errors``,
``quickshell_trace``, ``quickshell_binding_inspect``, ``quickshell_reload``).
Runtime diagnostics combine logs, errors, project context, and docs into
root-cause hypotheses with confidence; original error text is preserved.
Reload is mutating; the rest are read-only.

Depends on: knowledge, project, runtime, inspection.
"""

from __future__ import annotations

from ..sources.explain_error import (  # noqa: F401
    _categorize_error,
    _explain_error,
    _extract_type_from_code,
)
from ..sources.runtime_debug import (  # noqa: F401
    _binding_inspect,
    _diagnose,
    _reload,
    _runtime_errors,
    _trace,
)

CAPABILITY_NAME = "debugging"
CAPABILITY_TOOLS = (
    "quickshell_explain_error",
    "quickshell_runtime_diagnose",
    "quickshell_runtime_errors",
    "quickshell_trace",
    "quickshell_binding_inspect",
    "quickshell_reload",
)
CAPABILITY_DEPENDS_ON = ("knowledge", "project", "runtime", "inspection")
