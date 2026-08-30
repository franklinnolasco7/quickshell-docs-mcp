"""PipeWire adapter: safe read-only inspection via ``pw-cli``.

Reports sinks, sources, and device identity from ``pw-cli ls Node``.  Never
changes device state.
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

from .base import _Adapter

# pw-cli emits lines like `media.class = "Audio/Sink"`.
_PROP_RE = re.compile(r'^\s*([\w.+-]+)\s*=\s*"([^"]*)"\s*$')
_ID_RE = re.compile(r"^id\s+(\d+)", re.MULTILINE)


def _pw_nodes() -> str:
    try:
        result = subprocess.run(["pw-cli", "ls", "Node"], capture_output=True, text=True, timeout=5)
        if result.returncode != 0:
            return ""
        return result.stdout
    except (subprocess.SubprocessError, OSError):
        return ""


def _parse_nodes(text: str) -> list[dict[str, Any]]:
    """Parse `pw-cli ls Node` output into a list of node dicts.

    A new node starts at an ``id N`` line; subsequent ``key = "value"``
    lines populate that node until the next id or blank line.
    """
    nodes: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal current
        if current is not None:
            nodes.append(current)
            current = None

    for line in text.splitlines():
        id_match = _ID_RE.match(line)
        if id_match:
            flush()
            current = {"id": int(id_match.group(1))}
            continue
        prop = _PROP_RE.match(line)
        if prop and current is not None:
            current[prop.group(1)] = prop.group(2)
    flush()
    return nodes


class _PipewireAdapter(_Adapter):
    name = "PipeWire"
    binary = "pw-cli"

    def detect(self) -> dict[str, Any]:
        nodes = _parse_nodes(_pw_nodes())
        sinks = [
            {"id": n["id"], "name": n.get("node.name"), "description": n.get("node.description")}
            for n in nodes
            if n.get("media.class") == "Audio/Sink"
        ]
        sources = [
            {"id": n["id"], "name": n.get("node.name"), "description": n.get("node.description")}
            for n in nodes
            if n.get("media.class") == "Audio/Source"
        ]
        return {
            "adapter": self.name,
            "sinks": sinks,
            "sources": sources,
            "note": (
                "Volume, mute, and default-device state require additional "
                "introspection; device identity is reported here."
            ),
        }
