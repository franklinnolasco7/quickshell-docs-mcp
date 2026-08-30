"""Adapter base interface for desktop environment inspection.

Each adapter inspects a specific external service/compositor (Hyprland, PipeWire,
D-Bus, etc.) and reports read-only information. Adapters never invoke methods,
never write, and degrade gracefully with an explanatory note when the binary or
service is unavailable.
"""

from __future__ import annotations

import shutil
from abc import ABC, abstractmethod
from typing import Any


class _Adapter(ABC):
    """Base class for a desktop environment adapter.

    Subclasses override ``detect()`` to return a dict with the adapter's
    findings.  The base handles ``available()`` via ``shutil.which`` and
    ``missing_message()`` for graceful degradation.
    """

    name: str
    """Human-readable adapter name, e.g. ``"Hyprland"``."""

    binary: str | None = None
    """Name of the binary to detect (e.g. ``"hyprctl"``).  ``None`` means
    always-unavailable (the adapter is a future scaffold)."""

    def available(self) -> bool:
        """True if the required binary is on PATH."""
        if self.binary is None:
            return False
        return shutil.which(self.binary) is not None

    @abstractmethod
    def detect(self) -> dict[str, Any]:
        """Inspect the service and return findings.  Must be safe, read-only,
        and never invoke methods on the service itself."""

    def missing_message(self) -> str:
        """Explanatory note returned when the adapter is unavailable."""
        if self.binary:
            return f"'{self.binary}' not found on PATH; {self.name} adapter unavailable."
        return f"{self.name} adapter is not yet available in this environment."
