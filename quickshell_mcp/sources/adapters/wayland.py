"""Wayland layer adapter (scaffold).

Safe read-only inspection of Wayland layer/surface information for the
managed Quickshell runtime.  Full implementation requires a compositor
adapter (e.g. wlr-foreign-toplevel); until then this adapter reports
"not yet available" without failing.
"""

from __future__ import annotations

from typing import Any

from .base import _Adapter


class _WaylandLayersAdapter(_Adapter):
    name = "Wayland layers"
    binary = None  # no dedicated binary yet; future wlr-foreign-toplevel

    def detect(self) -> dict[str, Any]:
        return {
            "adapter": self.name,
            "layers": [],
            "note": (
                "Layer/surface inspection requires a compositor adapter "
                "(wlr-foreign-toplevel); not available in this environment."
            ),
        }
