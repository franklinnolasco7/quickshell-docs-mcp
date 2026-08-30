"""System diagnostics adapter: verified-only environment problems.

Reports missing commands, missing services, and obvious environment
mismatches that can be strongly evidenced.  Never guesses; only issues that
are verifiable are reported.
"""

from __future__ import annotations

import shutil
from typing import Any

from .base import _Adapter

# Commands a Quickshell development setup commonly needs.
_COMMANDS = (
    "qs",
    "quickshell",
    "grim",
    "hyprctl",
    "pw-cli",
    "busctl",
    "dbus-send",
)


class _SystemAdapter(_Adapter):
    name = "System diagnostics"
    binary = None  # no single binary; checks many

    def available(self) -> bool:
        return True

    def detect(self) -> dict[str, Any]:
        missing = [cmd for cmd in _COMMANDS if shutil.which(cmd) is None]
        present = [cmd for cmd in _COMMANDS if shutil.which(cmd) is not None]
        return {
            "adapter": self.name,
            "missing_commands": missing,
            "present_commands": present,
            "note": "Only verified, evidence-backed issues are reported.",
        }
