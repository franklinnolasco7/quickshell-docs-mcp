"""The adapters capability: safe read-only inspection of desktop environment
services (Hyprland, Wayland layers, PipeWire, D-Bus, system diagnostics).

Every adapter degrades gracefully when its binary/service is unavailable and
never mutates the environment. All tools are read-only.

Depends on: knowledge.
"""

from __future__ import annotations

from ..sources.adapters import (  # noqa: F401
    _ADAPTERS,
    _Adapter,
    _detect_adapter,
)

CAPABILITY_NAME = "adapters"
CAPABILITY_TOOLS = (
    "quickshell_hyprland_info",
    "quickshell_wayland_layers",
    "quickshell_pipewire_info",
    "quickshell_dbus_services",
    "quickshell_system_diagnostics",
)
CAPABILITY_DEPENDS_ON = ("knowledge",)
