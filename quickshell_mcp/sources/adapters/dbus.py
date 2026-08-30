"""D-Bus adapter: safe read-only service discovery via ``busctl``.

Lists user-session D-Bus services and interfaces.  Never invokes methods —
this first version only performs discovery.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

from .base import _Adapter


def _busctl_list() -> str:
    try:
        result = subprocess.run(
            ["busctl", "--user", "list"], capture_output=True, text=True, timeout=5
        )
        if result.returncode != 0:
            return ""
        return result.stdout
    except (subprocess.SubprocessError, OSError):
        return ""


_SERVICE_RE = re.compile(r"^([^\s]+)\s+", re.MULTILINE)


class _DBusAdapter(_Adapter):
    name = "D-Bus"
    binary = "busctl"

    def detect(self) -> dict[str, Any]:
        text = _busctl_list()
        services = sorted({m.group(1) for m in _SERVICE_RE.finditer(text)})
        return {
            "adapter": self.name,
            "services": services,
            "note": "Discovery only; method invocation is not performed.",
        }
