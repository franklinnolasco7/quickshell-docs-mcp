"""Official example configs via the git.outfoxxed.me Gitea API."""

import json

import httpx

from .. import utils
from ..config import EXAMPLES_REPO_API, EXAMPLES_REPO_WEB


def _examples_branch() -> str:
    repo_info = json.loads(utils._fetch_raw(EXAMPLES_REPO_API))
    branch = repo_info.get("default_branch")
    if not branch:
        raise RuntimeError(
            "examples repo metadata carries no default_branch; the Gitea API "
            "shape may have changed."
        )
    return branch


def _examples_listing(path: str) -> dict:
    path = path.strip("/")
    branch = _examples_branch()
    contents_base = f"{EXAMPLES_REPO_API}/contents"
    api_url = f"{contents_base}/{path}?ref={branch}" if path else f"{contents_base}?ref={branch}"
    entries = json.loads(utils._fetch_raw(api_url))
    if isinstance(entries, dict):
        entries = [entries]
    listing = [
        {
            "name": entry.get("name"),
            "path": entry.get("path"),
            "type": entry.get("type"),
            "size": entry.get("size"),
            # Lets consumers judge whether an example predates their Quickshell.
            "last_modified": entry.get("last_commit_when"),
            "kind": "official example",
        }
        for entry in entries
    ]
    return {
        "repo": EXAMPLES_REPO_WEB,
        "branch": branch,
        "kind": "official examples",
        "path": path,
        "entries": listing,
        "source": api_url,
    }


def _examples_known_paths(path: str) -> list[str]:
    """Paths of entries at `path`, falling back to the repo root when the
    parent itself doesn't exist (keeps the did-you-mean message useful)."""
    for probe in (path, ""):
        try:
            return [entry["path"] for entry in _examples_listing(probe)["entries"]]
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise
    return []


def _example_file(path: str) -> str:
    path = path.strip("/")
    branch = _examples_branch()
    url = f"{EXAMPLES_REPO_WEB}/raw/branch/{branch}/{path}"
    try:
        text = utils._fetch_raw(url)
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            parent_directory = "/".join(path.split("/")[:-1])
            raise ValueError(
                f"No file '{path}' in the examples repo. "
                f"Known paths: {', '.join(_examples_known_paths(parent_directory))}"
            ) from error
        raise
    return utils._with_source(url, text)
