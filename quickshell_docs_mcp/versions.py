"""Runtime discovery of quickshell.org doc versions."""

import re

import httpx

from . import utils
from .caches import _cache_get, _cache_set
from .config import _VERSION_NUM, BASE

VERSION_RE = re.compile(rf"/docs/(v{_VERSION_NUM})/")


def _version_sort_key(version: str) -> tuple[int, int, int, int, str]:
    # Releases sort above their own prereleases (semver-ish): v0.4.0 > v0.4.0-rc1.
    match = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)(?:-(.+))?", version)
    if not match:
        return (-1, -1, -1, 0, "")
    prerelease = match.group(4)
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        0 if prerelease else 1,
        prerelease or "",
    )


def list_versions(refresh: bool = False) -> list[str]:
    """Discover every doc version currently linked from the site, newest first."""
    if refresh:
        from .caches import _cache

        _cache.clear()
    cached = _cache_get("versions")
    if cached is not None:
        return cached
    # There is no canonical /docs/ index (it 404s); version links live in the
    # nav switcher of every docs page and on /about/. Scan candidates in order
    # and stop at the first page that lists several versions (/about/ carries
    # the complete set today).
    found: set[str] = set()
    for url in (f"{BASE}/about/", f"{BASE}/docs/", f"{BASE}/"):
        try:
            html = utils._fetch_raw(url)
        except httpx.HTTPError:
            continue
        found.update(VERSION_RE.findall(html))
        if len(found) >= 2:
            break
    versions = sorted(found, key=_version_sort_key, reverse=True)
    utils.log.info("discovered %d doc version(s): %s", len(versions), ", ".join(versions))
    _cache_set("versions", versions)
    return versions


def _latest_version() -> str:
    versions = list_versions()
    if not versions:
        raise RuntimeError(
            "Could not discover any Quickshell doc version from quickshell.org. "
            "The site structure may have changed."
        )
    return versions[0]


def _resolve_version(version: str | None) -> str:
    if not version or version.lower() == "latest":
        return _latest_version()
    normalized = version if version.startswith("v") else f"v{version}"
    known = list_versions()
    if known and normalized not in known:
        raise ValueError(f"Unknown version '{version}'. Known versions: {', '.join(known)}")
    return normalized
