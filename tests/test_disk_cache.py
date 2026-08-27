"""Disk persistence for the bulk doc indexes."""

from __future__ import annotations

import json
import time

import pytest

import quickshell_mcp.server as srv
from quickshell_mcp import caches, utils


@pytest.fixture
def disk_dir(tmp_path, monkeypatch):
    directory = tmp_path / "disk-cache"
    monkeypatch.setenv("QUICKSHELL_DOCS_MCP_DISK_CACHE", str(directory))
    return directory


def test_disk_roundtrip_within_ttl(disk_dir):
    caches._disk_set("type_content:v0.3.1", [{"a": 1}])
    assert caches._disk_get("type_content:v0.3.1") == [{"a": 1}]
    files = list(disk_dir.glob("*.json"))
    assert len(files) == 1  # ':' sanitized out of the filename


def test_expired_entry_reads_as_missing(disk_dir):
    caches._disk_set("type_content:v0.3.1", ["stale"])
    path = next(disk_dir.glob("*.json"))
    envelope = json.loads(path.read_text())
    envelope["saved_at"] = time.time() - (31 * 24 * 3600)
    path.write_text(json.dumps(envelope))
    assert caches._disk_get("type_content:v0.3.1") is None


def test_ttl_hours_env_override(disk_dir, monkeypatch):
    caches._disk_set("qt_index:latest", {"modules": {}})
    path = next(disk_dir.glob("*.json"))
    envelope = json.loads(path.read_text())
    envelope["saved_at"] = time.time() - (2 * 3600)  # 2 hours old

    monkeypatch.setenv("QUICKSHELL_DOCS_MCP_DISK_TTL_HOURS", "720")
    path.write_text(json.dumps(envelope))
    assert caches._disk_get("qt_index:latest") == {"modules": {}}

    monkeypatch.setenv("QUICKSHELL_DOCS_MCP_DISK_TTL_HOURS", "1")
    assert caches._disk_get("qt_index:latest") is None


def test_disabled_via_env(monkeypatch):
    monkeypatch.setenv("QUICKSHELL_DOCS_MCP_DISK_CACHE", "off")
    caches._disk_set("type_content:v0.3.1", [1])
    assert caches._disk_get("type_content:v0.3.1") is None


def test_corrupt_file_reads_as_missing(disk_dir):
    disk_dir.mkdir(parents=True)
    (disk_dir / "broken.json").write_text("{not json")
    assert caches._disk_get("broken") is None


def test_type_index_survives_process_restart(monkeypatch):
    """Simulated restart: memory cache cleared between the two builds; the
    second build must be served entirely from disk."""
    from quickshell_mcp.sources import docs as docs_src

    calls: list[str] = []

    def fake_build(version: str) -> dict:
        return {"types_by_namespace": {"Quickshell": ["PanelWindow"]}, "guide_pages": []}

    def fake_fetch(url: str) -> str:
        calls.append(url)
        return "# PanelWindow\nanchors everywhere"

    monkeypatch.setattr(docs_src, "_build_index", fake_build)
    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    first = docs_src._type_content_index("v0.3.1")
    assert len(calls) == 1

    srv._cache.clear()  # process restart equivalent
    second = docs_src._type_content_index("v0.3.1")
    assert len(calls) == 1  # served from disk, no refetch
    assert second == first


def test_refresh_bypasses_disk(disk_dir, monkeypatch):
    from quickshell_mcp.sources import docs as docs_src

    calls: list[str] = []

    def fake_build(version: str) -> dict:
        return {"types_by_namespace": {"Quickshell": ["PanelWindow"]}, "guide_pages": []}

    def fake_fetch(url: str) -> str:
        calls.append(url)
        return f"body {len(calls)}"

    monkeypatch.setattr(docs_src, "_build_index", fake_build)
    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)

    docs_src._type_content_index("v0.3.1")
    srv._cache.clear()
    refreshed = docs_src._type_content_index("v0.3.1", refresh=True)
    assert len(calls) == 2  # disk entry ignored on refresh
    assert refreshed[0]["markdown"] == "body 2"
