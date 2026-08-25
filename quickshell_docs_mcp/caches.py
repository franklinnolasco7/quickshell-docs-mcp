"""Caching: a 30-minute in-memory layer for every fetch, plus a disk layer
that keeps the expensive bulk doc indexes (guide/type/qt) warm across server
restarts. Raw HTML is never persisted; disk holds only the built indexes."""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from .config import _CACHE_TTL

_log = logging.getLogger(__name__)

_DEFAULT_DISK_TTL_HOURS = 720  # 30 days; published versions are effectively frozen


@dataclass
class _CacheEntry:
    value: object
    ts: float = field(default_factory=time.time)


_cache: dict[str, _CacheEntry] = {}


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry and (time.time() - entry.ts) < _CACHE_TTL:
        return entry.value
    return None


def _cache_set(key: str, value: object):
    _cache[key] = _CacheEntry(value)


def _disk_dir() -> Path | None:
    """Cache root, or None when disabled via QUICKSHELL_DOCS_MCP_DISK_CACHE.
    Read per call so tests can redirect it without re-importing."""
    override = os.environ.get("QUICKSHELL_DOCS_MCP_DISK_CACHE", "").strip()
    if override.lower() in ("off", "0", "false"):
        return None
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(xdg) / "quickshell-docs-mcp"


def _disk_ttl_seconds() -> float:
    raw = os.environ.get("QUICKSHELL_DOCS_MCP_DISK_TTL_HOURS", "").strip()
    try:
        hours = float(raw) if raw else _DEFAULT_DISK_TTL_HOURS
    except ValueError:
        log_warning = logging.getLogger("quickshell-docs-mcp")
        log_warning.warning("invalid QUICKSHELL_DOCS_MCP_DISK_TTL_HOURS=%r; using default", raw)
        hours = _DEFAULT_DISK_TTL_HOURS
    return max(hours, 0.0) * 3600


def _disk_path(key: str) -> Path | None:
    directory = _disk_dir()
    if directory is None:
        return None
    # ':' would be legal on Linux but smells like a Windows portability trap.
    return directory / (key.replace(":", "_") + ".json")


def _disk_get(key: str) -> object | None:
    path = _disk_path(key)
    if path is None:
        return None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    saved_at = envelope.get("saved_at", 0)
    if not isinstance(saved_at, (int, float)):
        return None
    if time.time() - saved_at > _disk_ttl_seconds():
        return None
    return envelope.get("value")


def _disk_set(key: str, value: object) -> None:
    path = _disk_path(key)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        envelope = {"saved_at": time.time(), "value": value}
        path.write_text(json.dumps(envelope), encoding="utf-8")
    except OSError as error:
        # Disk cache is an optimization only; never fail a request over it.
        _log.warning("disk cache write failed for %s: %s", key, error)
