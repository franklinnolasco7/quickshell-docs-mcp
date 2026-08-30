"""Hyprland adapter: safe read-only inspection via ``hyprctl``.

Uses ``hyprctl -j monitors``, ``hyprctl -j workspaces``, and
``hyprctl -j clients`` to report monitors, workspaces, the active workspace,
and clients.  Never issues commands that modify the compositor.
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from .base import _Adapter


def _hyprctl_json(args: list[str]) -> list[Any] | dict[str, Any] | None:
    """Run ``hyprctl -j <args>`` and parse JSON, or None on failure."""
    try:
        result = subprocess.run(["hyprctl", "-j", *args], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)
    except (ValueError, subprocess.SubprocessError, OSError):
        return None


class _HyprlandAdapter(_Adapter):
    name = "Hyprland"
    binary = "hyprctl"

    def detect(self) -> dict[str, Any]:
        monitors = _hyprctl_json(["monitors"]) or []
        workspaces = _hyprctl_json(["workspaces"]) or []
        clients = _hyprctl_json(["clients"]) or []

        active_workspace = None
        for ws in workspaces:
            if isinstance(ws, dict) and ws.get("focused"):
                active_workspace = ws.get("id")
                break

        return {
            "adapter": self.name,
            "monitors": [
                {
                    "name": m.get("name"),
                    "model": m.get("model"),
                    "make": m.get("make"),
                    "width": m.get("width"),
                    "height": m.get("height"),
                    "focused": m.get("focused", False),
                    "active_workspace": m.get("activeWorkspace", {}).get("id")
                    if isinstance(m.get("activeWorkspace"), dict)
                    else None,
                }
                for m in monitors
                if isinstance(m, dict)
            ],
            "workspaces": [
                {
                    "id": w.get("id"),
                    "name": w.get("name"),
                    "monitor": w.get("monitor"),
                    "windows": w.get("windows", 0),
                    "focused": w.get("focused", False),
                }
                for w in workspaces
                if isinstance(w, dict)
            ],
            "active_workspace": active_workspace,
            "clients": [
                {
                    "class": c.get("class"),
                    "title": c.get("title"),
                    "mapped": c.get("mapped", False),
                    "hidden": c.get("hidden", False),
                    "workspace": c.get("workspace", {}).get("id")
                    if isinstance(c.get("workspace"), dict)
                    else None,
                }
                for c in clients
                if isinstance(c, dict)
            ],
        }
