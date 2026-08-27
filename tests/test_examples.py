"""Examples-repo tools (Gitea API on git.outfoxxed.me), driven by real API
response snapshots."""

from __future__ import annotations

import json

import pytest
from conftest import http_404, load_fixture

import quickshell_mcp.server as srv
from quickshell_mcp import utils  # noqa: E402


def _install(monkeypatch, extra_404: set[str] | None = None):
    extra_404 = extra_404 or set()
    info = load_fixture("examples_repo_info.json")
    root = load_fixture("examples_contents_root.json")
    readme = load_fixture("example_readme.md")

    mapping = {
        srv.EXAMPLES_REPO_API: info,
        f"{srv.EXAMPLES_REPO_API}/contents?ref=master": root,
        f"{srv.EXAMPLES_REPO_WEB}/raw/branch/master/README.md": readme,
    }

    def fake_fetch(url: str) -> str:
        if url in extra_404:
            raise http_404(url)
        if url not in mapping:
            raise AssertionError(f"unexpected fetch in test: {url}")
        return mapping[url]

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)


def test_list_examples_root_shape(monkeypatch):
    _install(monkeypatch)
    out = srv.quickshell_list_examples()
    assert out["branch"] == "master"  # resolved from repo metadata, not hardcoded
    assert out["source"] == f"{srv.EXAMPLES_REPO_API}/contents?ref=master"
    paths = {entry["path"] for entry in out["entries"]}
    assert "README.md" in paths
    assert "volume-osd" in paths
    types = {entry["path"]: entry["type"] for entry in out["entries"]}
    assert types["README.md"] == "file"
    assert types["lockscreen"] == "dir"
    # Freshness hint from the Gitea API, surfaced so consumers can judge
    # whether an example predates their Quickshell.
    assert all(entry.get("last_modified") for entry in out["entries"])


def test_list_examples_bad_path_suggests_known_entries(monkeypatch):
    _install(
        monkeypatch,
        extra_404={
            f"{srv.EXAMPLES_REPO_API}/contents/nope?ref=master",
            f"{srv.EXAMPLES_REPO_API}/contents/nope/deeper?ref=master",
        },
    )
    with pytest.raises(ValueError, match="Known entries"):
        srv.quickshell_list_examples("nope")
    # A bad nested path whose parent also doesn't exist still gets suggestions.
    with pytest.raises(ValueError, match="Known entries"):
        srv.quickshell_list_examples("nope/deeper")


def test_get_example_reads_exact_raw_url(monkeypatch):
    _install(monkeypatch)
    expected_url = f"{srv.EXAMPLES_REPO_WEB}/raw/branch/master/README.md"
    body = srv.quickshell_get_example("README.md")
    assert expected_url in body
    assert "quickshell" in body.lower()


def test_get_example_bad_path_is_friendly(monkeypatch):
    _install(monkeypatch, extra_404={f"{srv.EXAMPLES_REPO_WEB}/raw/branch/master/nope.qml"})
    with pytest.raises(ValueError, match="No file 'nope.qml'"):
        srv.quickshell_get_example("nope.qml")


def test_branch_resolution_requires_default_branch(monkeypatch):
    broken = json.dumps({"name": "quickshell-examples"})
    monkeypatch.setattr(utils, "_fetch_raw", lambda url: broken)
    with pytest.raises(RuntimeError, match="default_branch"):
        srv._examples_branch()
