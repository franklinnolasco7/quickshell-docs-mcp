"""The runtime capability: manage isolated Quickshell runtime sessions.

Sessions are launched from explicit runtime profiles with isolated XDG dirs,
tracked in a registry, and inspectable via status, logs, and ping. The
capability is mutating: starting, stopping, and resetting sessions alter
process state and must be explicitly invoked.

Depends on: knowledge, project (runtime tools use project detection and
documentation for diagnostics).
"""

from __future__ import annotations

from ..sources.runtime_profile import _RuntimeProfile  # noqa: F401
from ..sources.runtime_session import (  # noqa: F401
    _SESSION_REGISTRY,
    _logs,
    _ping,
    _qs_binary,
    _reset_session,
    _start_session,
    _status_session,
    _stop_session,
)

CAPABILITY_NAME = "runtime"
CAPABILITY_TOOLS = (
    "quickshell_runtime_start",
    "quickshell_runtime_stop",
    "quickshell_runtime_reset",
    "quickshell_runtime_status",
    "quickshell_runtime_logs",
    "quickshell_runtime_ping",
)
CAPABILITY_DEPENDS_ON = ("knowledge", "project")
