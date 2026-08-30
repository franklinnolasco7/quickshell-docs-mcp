"""Ecosystem diagnostics: safe runtime dependency detection, Nix-aware
diagnostics with non-Nix fallback, and a named/versioned/inspectable
runtime profile registry.

All tools are read-only or in-memory data operations. The profile
registry is a session-scoped dict; nothing is persisted to disk.
"""

from __future__ import annotations

import re
import shutil
import threading
from pathlib import Path
from typing import Any, cast

from .project import _build_project_context
from .runtime_profile import _RuntimeProfile

# ---------------------------------------------------------------------------
# Nix-aware diagnostics
# ---------------------------------------------------------------------------

_NIX_SHELL_RE = re.compile(r"devShells\s*\.\s*([\w.-]+)", re.IGNORECASE)
_NIXPKGS_INPUT_RE = re.compile(
    r"^\s*(?:inputs\s*\.\s*)?(nixpkgs|nixos-[\w-]+|nixpkgs-[\w-]+)\s*\.\s*url",
    re.IGNORECASE | re.MULTILINE,
)


def _nix_diagnostics(project: str) -> dict[str, Any]:
    """Detect Nix infrastructure in *project* and report diagnostics.

    Scans for flake.nix, flake.lock, devShells, and nixpkgs inputs.
    Falls back to the package manager when Nix is absent.
    """
    root = Path(project).expanduser().resolve()
    flax = root / "flake.nix"
    lock = root / "flake.lock"
    nix_available = shutil.which("nix") is not None

    flake_info: dict[str, Any] = {"present": False}
    if flax.is_file():
        text = flax.read_text(encoding="utf-8", errors="replace")
        shells = sorted({m.group(1) for m in _NIX_SHELL_RE.finditer(text)})
        if not shells and re.search(r"devShells", text, re.IGNORECASE):
            shells.append("(unnamed)")
        nixpkgs = sorted({m.group(1) for m in _NIXPKGS_INPUT_RE.finditer(text)})
        flake_info = {
            "present": True,
            "path": str(flax),
            "devShells": shells,
            "nixpkgs_inputs": nixpkgs,
            "locked": lock.is_file(),
        }

    fallback = _non_nix_fallback() if not flake_info["present"] else None

    return {
        "project": str(root),
        "nix_available": nix_available,
        "flake": flake_info,
        "fallback": fallback,
        "note": (
            "Nix diagnostics are file-based (no nix evaluation). "
            "When flake.nix is absent, the package manager is reported as fallback."
        ),
    }


def _non_nix_fallback() -> dict[str, Any] | None:
    """Detect the system package manager as a non-Nix fallback."""
    candidates = [
        ("apt", "dpkg"),
        ("dnf", "rpm"),
        ("pacman", "pacman"),
        ("brew", "brew"),
        ("emerge", "portageq"),
        ("zypper", "zypper"),
    ]
    for name, binary in candidates:
        if shutil.which(binary):
            return {"package_manager": name, "binary": binary}
    return None


# ---------------------------------------------------------------------------
# Runtime dependency detection (safe, static)
# ---------------------------------------------------------------------------

_RUNTIME_BINARIES = ("qs", "quickshell", "hyprctl", "pw-cli", "busctl")


def _runtime_dependencies(project: str) -> dict[str, Any]:
    """Detect what a Quickshell project needs at runtime, statically.

    Uses the project context scanner (no execution). Reports detected
    QML types (Process, IpcHandler, ...), config keywords, imports,
    compositor, and which system binaries are on PATH.
    """
    ctx = _build_project_context(project)
    info = cast(
        dict[str, Any],
        ctx.discover(
            {
                "runtime_dependencies",
                "dependencies",
                "quickshell_modules",
                "compositor",
                "services",
            }
        ),
    )

    binaries = {cmd: shutil.which(cmd) is not None for cmd in _RUNTIME_BINARIES}

    runtime = info.get("runtime_dependencies") or {}
    services = info.get("services") or {}

    return {
        "project_root": str(ctx.root) if ctx.root else project,
        "runtime_qml_types": runtime.get("qml_types", []),
        "config_keywords": runtime.get("config", []),
        "imports": sorted(info.get("dependencies", [])),
        "compositor": info.get("compositor"),
        "services": sorted(services.get("modules", []) + services.get("objects", [])),
        "system_binaries": binaries,
        "note": "Detection is static and evidence-based; nothing is executed.",
    }


# ---------------------------------------------------------------------------
# Runtime profile registry
# ---------------------------------------------------------------------------

# Increment when the profile schema changes; export/import round-trips carry
# it so an imported payload from an older schema is detected, not silently
# reinterpreted.
_PROFILE_SCHEMA_VERSION = 1

# Registry mutations are guarded because the MCP server can dispatch
# concurrent requests; a torn read must never hand out a half-written entry.
_PROFILE_LOCK = threading.RLock()

_PROFILE_REGISTRY: dict[str, _RuntimeProfile] = {}


def _profile_save(
    name: str,
    project_root: str,
    entrypoint: str | None = None,
    config_dir: str | None = None,
    compositor: str | None = None,
    arguments: list[str] | None = None,
    environment: dict[str, str] | None = None,
    fixture_data: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Save a named runtime profile in the registry."""
    profile = _RuntimeProfile(
        project_root=project_root,
        entrypoint=entrypoint,
        config_dir=config_dir,
        compositor=compositor,
        arguments=arguments or [],
        environment=environment or {},
        fixture_data=fixture_data or {},
    )
    with _PROFILE_LOCK:
        _PROFILE_REGISTRY[name] = profile
    return _profile_entry(name, profile)


def _profile_entry(name: str, profile: _RuntimeProfile) -> dict[str, Any]:
    return {"name": name, "schema_version": _PROFILE_SCHEMA_VERSION, "profile": profile.to_dict()}


def _profile_list() -> dict[str, Any]:
    """List saved profiles with summary info."""
    entries = []
    with _PROFILE_LOCK:
        for name, profile in sorted(_PROFILE_REGISTRY.items()):
            d = profile.to_dict()
            entries.append(
                {
                    "name": name,
                    "schema_version": _PROFILE_SCHEMA_VERSION,
                    "project_root": d["project_root"],
                    "entrypoint": d["entrypoint"],
                    "compositor": d["compositor"],
                }
            )
    return {"profiles": entries, "count": len(entries)}


def _profile_get(name: str) -> dict[str, Any]:
    """Get a single profile by name, or raise."""
    with _PROFILE_LOCK:
        profile = _PROFILE_REGISTRY.get(name)
        if profile is None:
            available = sorted(_PROFILE_REGISTRY)
            raise ValueError(f"Profile '{name}' not found. Available: {available}")
        return _profile_entry(name, profile)


def _profile_delete(name: str) -> dict[str, Any]:
    """Delete a named profile from the registry."""
    with _PROFILE_LOCK:
        if name not in _PROFILE_REGISTRY:
            available = sorted(_PROFILE_REGISTRY)
            raise ValueError(f"Profile '{name}' not found. Available: {available}")
        del _PROFILE_REGISTRY[name]
        return {"deleted": name, "remaining": len(_PROFILE_REGISTRY)}


def _profile_export(name: str) -> dict[str, Any]:
    """Export a profile as a JSON-serializable dict (with schema version)."""
    with _PROFILE_LOCK:
        profile = _PROFILE_REGISTRY.get(name)
        if profile is None:
            available = sorted(_PROFILE_REGISTRY)
            raise ValueError(f"Profile '{name}' not found. Available: {available}")
        return _profile_entry(name, profile)


def _profile_import(name: str, data: dict[str, Any]) -> dict[str, Any]:
    """Import a profile from a dict (e.g. deserialized JSON).

    The payload may carry ``schema_version``; a version newer than the
    current one is refused rather than silently reinterpreted.
    """
    version = data.get("schema_version", 1)
    if version > _PROFILE_SCHEMA_VERSION:
        raise ValueError(
            f"Profile payload schema v{version} is newer than supported "
            f"v{_PROFILE_SCHEMA_VERSION}; upgrade the server or re-export."
        )
    profile = _RuntimeProfile(
        project_root=data.get("project_root", ""),
        entrypoint=data.get("entrypoint"),
        config_dir=data.get("config_dir"),
        compositor=data.get("compositor"),
        arguments=data.get("arguments", []),
        environment=data.get("environment", {}),
        fixture_data=data.get("fixture_data", {}),
    )
    with _PROFILE_LOCK:
        _PROFILE_REGISTRY[name] = profile
    return _profile_entry(name, profile)
