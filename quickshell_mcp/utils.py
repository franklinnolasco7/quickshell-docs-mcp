"""Shared plumbing: logging, the HTTP client, fetch with retry, and session
stats. Domain modules call ``utils._fetch_raw`` by module attribute so tests
can monkeypatch a single seam."""

import logging
import os
import sys
import time

import httpx

from .caches import _cache_get, _cache_set
from .config import _RETRY_ATTEMPTS, USER_AGENT

_log_level_name = os.environ.get("QUICKSHELL_DOCS_MCP_LOG", "").strip().upper()
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format="quickshell-mcp: %(levelname)s %(message)s",
)
log = logging.getLogger("quickshell-mcp")
logging.getLogger("httpx").setLevel(
    getattr(logging, _log_level_name, logging.INFO) if _log_level_name else logging.WARNING
)

_client = httpx.Client(
    headers={"User-Agent": USER_AGENT},
    timeout=15.0,
    follow_redirects=True,
)

# Session stats: per-tool call counts plus fetch/cache-hit counters. Process
# local, reset on restart; exposed via quickshell_stats.
_TOOL_CALLS: dict[str, int] = {}
_FETCH_STATS = {"cache_hits": 0, "network_fetches": 0}
_STATS_STARTED = time.time()


def _record_tool(name: str) -> None:
    _TOOL_CALLS[name] = _TOOL_CALLS.get(name, 0) + 1


def _fetch_raw(url: str) -> str:
    cached = _cache_get(url)
    if cached is not None:
        _FETCH_STATS["cache_hits"] += 1
        return cached
    last_error: Exception | None = None
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            response = _client.get(url)
            response.raise_for_status()
            text = response.text
            _FETCH_STATS["network_fetches"] += 1
            log.debug("fetched %s (%d chars)", url, len(text))
            _cache_set(url, text)
            return text
        except (httpx.TimeoutException, httpx.TransportError) as err:
            last_error = err
            log.warning("fetch %s failed (attempt %d/%d): %s", url, attempt, _RETRY_ATTEMPTS, err)
            if attempt < _RETRY_ATTEMPTS:
                time.sleep(0.5 * attempt)
    raise RuntimeError(
        f"failed to fetch {url} after {_RETRY_ATTEMPTS} attempts: {last_error}"
    ) from last_error


def _with_source(url: str, markdown: str) -> str:
    """Prefix fetched pages with their source URL so the model can cite them."""
    return f"*Source: [{url}]({url})*\n\n{markdown}"
