"""Runtime profiles: explicit, inspectable launch configuration for managed
Quickshell runtime sessions.

A profile describes *how* to run a Quickshell project in isolation: the
project root, entrypoint, config directory, environment overrides, compositor
or backend, command-line arguments, and optional fixture data. Profiles are
pure data — nothing here launches processes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class _RuntimeProfile:
    """Explicit launch configuration for a managed Quickshell session."""

    project_root: str
    entrypoint: str | None = None
    config_dir: str | None = None
    environment: dict[str, str] = field(default_factory=dict)
    compositor: str | None = None
    arguments: list[str] = field(default_factory=list)
    fixture_data: dict[str, str] = field(default_factory=dict)

    def resolved_entrypoint(self) -> str:
        """The QML entrypoint: the configured one, or the project's detected
        entrypoint, or ``shell.qml`` / ``main.qml`` under the project root."""
        if self.entrypoint:
            return str(Path(self.entrypoint).expanduser().resolve())
        root = Path(self.project_root).expanduser().resolve()
        for name in ("shell.qml", "main.qml", "config.qml"):
            candidate = root / name
            if candidate.is_file():
                return str(candidate)
        raise ValueError(
            f"No entrypoint found under {root}; pass entrypoint= or add shell.qml/main.qml."
        )

    def isolated_environment(self, instance_id: str) -> dict[str, str]:
        """Environment for launching the session: inherited variables plus
        profile overrides and isolated XDG dirs for the instance."""
        import os
        import tempfile

        base = dict(os.environ)
        base.update(self.environment)
        prefix = Path(tempfile.gettempdir()) / f"qs-mcp-{instance_id}"
        # Isolate per-session state so a managed shell never touches the
        # user's real XDG dirs or other quickshell instances.
        base.update(
            {
                "QUICKSHELL_INSTANCE_ID": instance_id,
                "XDG_CONFIG_HOME": str(prefix / "config"),
                "XDG_CACHE_HOME": str(prefix / "cache"),
                "XDG_DATA_HOME": str(prefix / "data"),
                "XDG_STATE_HOME": str(prefix / "state"),
            }
        )
        return base

    def to_dict(self) -> dict[str, object]:
        root = Path(self.project_root).expanduser().resolve()
        entrypoint: str | None
        if self.entrypoint or root.is_dir():
            try:
                entrypoint = self.resolved_entrypoint()
            except ValueError:
                entrypoint = self.entrypoint
        else:
            entrypoint = self.entrypoint
        return {
            "project_root": self.project_root,
            "entrypoint": entrypoint,
            "config_dir": self.config_dir,
            "compositor": self.compositor,
            "arguments": self.arguments,
            "fixture_data": self.fixture_data,
        }
