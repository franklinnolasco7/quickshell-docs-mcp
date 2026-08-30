"""Desktop environment adapters: safe read-only inspection of external services.

Each adapter inspects one service (Hyprland, Wayland layers, PipeWire, D-Bus,
system diagnostics) and degrades gracefully when its binary/service is
unavailable.  Nothing is invoked beyond safe reads; nothing is written.
"""

from __future__ import annotations

from typing import Any

from .base import _Adapter
from .dbus import _DBusAdapter
from .hyprland import _HyprlandAdapter
from .pipewire import _PipewireAdapter
from .system import _SystemAdapter
from .wayland import _WaylandLayersAdapter

_ADAPTERS: tuple[_Adapter, ...] = (
    _HyprlandAdapter(),
    _WaylandLayersAdapter(),
    _PipewireAdapter(),
    _DBusAdapter(),
    _SystemAdapter(),
)

__all__ = [
    "_ADAPTERS",
    "_Adapter",
    "_DBusAdapter",
    "_HyprlandAdapter",
    "_PipewireAdapter",
    "_SystemAdapter",
    "_WaylandLayersAdapter",
    "_detect_adapter",
]


def _adapter_names() -> list[str]:
    return [a.name for a in _ADAPTERS]


def _detect_adapter(name: str) -> dict[str, Any]:
    """Run the named adapter, or all adapters when *name* is ``"all"``."""
    if name.strip().lower() == "all":
        return _detect_all()
    for adapter in _ADAPTERS:
        if adapter.name.lower() == name.strip().lower():
            return _run_adapter(adapter)
    raise ValueError(f"Unknown adapter '{name}'. Known adapters: {', '.join(_adapter_names())}")


def _detect_all() -> dict[str, Any]:
    return {"adapters": [_run_adapter(a) for a in _ADAPTERS]}


def _run_adapter(adapter: _Adapter) -> dict[str, Any]:
    if not adapter.available():
        return {
            "adapter": adapter.name,
            "available": False,
            "note": adapter.missing_message(),
        }
    try:
        findings = adapter.detect()
    except Exception as exc:  # noqa: BLE001 - an adapter must never sink others
        return {
            "adapter": adapter.name,
            "available": True,
            "note": f"Adapter failed during inspection: {exc}",
        }
    return {"adapter": adapter.name, "available": True, **findings}
