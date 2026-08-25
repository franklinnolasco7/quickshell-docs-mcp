"""quickshell.org: type/guide index, full-text guide search, and page fetches."""

import re
from concurrent.futures import ThreadPoolExecutor
from typing import cast

import httpx

from .. import utils
from ..caches import _cache_get, _cache_set, _disk_get, _disk_set
from ..config import _VERSION_NUM, BASE
from ..extraction import _fetch_page_markdown
from ..versions import _resolve_version

TYPE_LINK_RE = re.compile(rf"/docs/(v{_VERSION_NUM})/types/([\w.]+)/([\w]+)")
GUIDE_LINK_RE = re.compile(rf"/docs/(v{_VERSION_NUM})/guide/([\w-]+)")


def _build_index(version: str) -> dict:
    cache_key = f"index:{version}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached

    # Both the guide index page and the version root page carry the full
    # sidebar nav (guide links + type links), so either works as a source.
    html = ""
    for url in (f"{BASE}/docs/{version}/guide/", f"{BASE}/docs/{version}/"):
        try:
            html = utils._fetch_raw(url)
            break
        except httpx.HTTPStatusError as error:
            if error.response.status_code != 404:
                raise
    if not html:
        raise RuntimeError(
            f"Could not load the docs index for {version}; the site structure may have changed."
        )

    types_by_namespace: dict[str, list[str]] = {}
    for link_version, namespace, type_name in TYPE_LINK_RE.findall(html):
        if link_version != version:
            continue
        types_by_namespace.setdefault(namespace, [])
        if type_name not in types_by_namespace[namespace]:
            types_by_namespace[namespace].append(type_name)

    guide_pages = sorted({slug for v, slug in GUIDE_LINK_RE.findall(html) if v == version})

    index = {"types_by_namespace": types_by_namespace, "guide_pages": guide_pages}
    utils.log.info(
        "built index for %s: %d namespace(s), %d guide page(s)",
        version,
        len(types_by_namespace),
        len(guide_pages),
    )
    _cache_set(cache_key, index)
    return index


_CONTENT_SNIPPET_CHARS = 160


def _content_snippet(markdown: str, needle_lower: str) -> str:
    """A trimmed window around the first occurrence, for search results."""
    markdown_lower = markdown.lower()
    window_start = max(0, markdown_lower.find(needle_lower) - 60)
    raw_snippet = markdown[window_start : window_start + _CONTENT_SNIPPET_CHARS]
    return re.sub(r"\s+", " ", raw_snippet).strip()


def _guide_content_index(version: str, refresh: bool = False) -> list[dict]:
    """Fetch and extract every guide page for a version once; cached in memory
    for the session and on disk across restarts (refresh=True skips both).
    A dead page is skipped rather than failing the search."""
    cache_key = f"guide_content:{version}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    if not refresh:
        disk_cached = _disk_get(cache_key)
        if disk_cached is not None:
            cached_pages = cast(list, disk_cached)
            _cache_set(cache_key, cached_pages)
            return cached_pages
    pages: list[dict] = []
    for slug in _build_index(version)["guide_pages"]:
        url = f"{BASE}/docs/{version}/guide/{slug}/"
        try:
            markdown = _fetch_page_markdown(url)
        except (httpx.HTTPError, RuntimeError) as error:
            utils.log.warning("content index: skipping guide page '%s': %s", slug, error)
            continue
        pages.append({"slug": slug, "url": url, "markdown": markdown})
    utils.log.info("built content index for %s: %d guide page(s)", version, len(pages))
    _cache_set(cache_key, pages)
    _disk_set(cache_key, pages)
    return pages


# Type pages number in the hundreds per version; fetching them sequentially on
# a cold cache would take minutes, so the index is built concurrently.
_TYPE_FETCH_WORKERS = 24


def _type_content_index(version: str, refresh: bool = False) -> list[dict]:
    """Fetch and extract every type reference page once per version; cached in
    memory for the session and on disk across restarts (refresh=True skips
    both). Dead pages are skipped rather than failing the search."""
    cache_key = f"type_content:{version}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached
    if not refresh:
        disk_cached = _disk_get(cache_key)
        if disk_cached is not None:
            cached_pages = cast(list, disk_cached)
            _cache_set(cache_key, cached_pages)
            return cached_pages

    type_names = [
        (namespace, name)
        for namespace, names in _build_index(version)["types_by_namespace"].items()
        for name in names
    ]

    def fetch_page(type_name_tuple: tuple[str, str]) -> dict | None:
        namespace, name = type_name_tuple
        url = f"{BASE}/docs/{version}/types/{namespace}/{name}/"
        try:
            return {
                "namespace": namespace,
                "type_name": name,
                "url": url,
                "markdown": _fetch_page_markdown(url),
            }
        except (httpx.HTTPError, RuntimeError) as error:
            utils.log.warning("type content index: skipping %s.%s: %s", namespace, name, error)
            return None

    with ThreadPoolExecutor(max_workers=_TYPE_FETCH_WORKERS) as pool:
        pages = [page for page in pool.map(fetch_page, type_names) if page]

    pages.sort(key=lambda page: (page["namespace"], page["type_name"]))
    utils.log.info("built type content index for %s: %d page(s)", version, len(pages))
    _cache_set(cache_key, pages)
    _disk_set(cache_key, pages)
    return pages


def _search_guide_content(
    query: str, version: str, limit: int = 8, refresh: bool = False
) -> list[dict]:
    """Case-insensitive full-text search across the extracted guide Markdown."""
    needle = query.lower()
    matches: list[dict] = []
    for page in _guide_content_index(version, refresh=refresh):
        occurrences = page["markdown"].lower().count(needle)
        if not occurrences:
            continue
        matches.append(
            {
                "slug": page["slug"],
                "url": page["url"],
                "occurrences": occurrences,
                "snippet": f"...{_content_snippet(page['markdown'], needle)}...",
            }
        )
    matches.sort(key=lambda match: -match["occurrences"])
    return matches[:limit]


def _search_type_content(
    query: str, version: str, limit: int = 8, refresh: bool = False
) -> list[dict]:
    """Full-text search over the extracted type reference Markdown."""
    needle = query.lower()
    matches: list[dict] = []
    for page in _type_content_index(version, refresh=refresh):
        occurrences = page["markdown"].lower().count(needle)
        if not occurrences:
            continue
        matches.append(
            {
                "namespace": page["namespace"],
                "type_name": page["type_name"],
                "url": page["url"],
                "occurrences": occurrences,
                "snippet": f"...{_content_snippet(page['markdown'], needle)}...",
            }
        )
    matches.sort(key=lambda match: -match["occurrences"])
    return matches[:limit]


def _guide_page(slug: str, version: str) -> str:
    resolved_version = _resolve_version(version)
    slug = slug.strip("/")
    url = f"{BASE}/docs/{resolved_version}/guide/{slug}/"
    try:
        markdown = _fetch_page_markdown(url)
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            index = _build_index(resolved_version)
            needle = slug.lower()
            close = [page for page in index["guide_pages"] if needle in page.lower()]
            raise ValueError(
                f"No guide page '{slug}' in {resolved_version}. "
                f"Known pages: {', '.join(close or index['guide_pages'])}"
            ) from error
        raise
    return utils._with_source(url, markdown)


def _type_page(type_name: str, namespace: str, version: str) -> str:
    resolved_version = _resolve_version(version)
    url = f"{BASE}/docs/{resolved_version}/types/{namespace}/{type_name}/"
    try:
        markdown = _fetch_page_markdown(url)
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            index = _build_index(resolved_version)
            namespaces = sorted(index["types_by_namespace"])
            namespace_types = index["types_by_namespace"].get(namespace)
            if namespace_types is None:
                ns_close = [ns for ns in namespaces if namespace.lower() in ns.lower()]
                raise ValueError(
                    f"No namespace '{namespace}' in {resolved_version}. "
                    f"Did you mean: {ns_close or namespaces}"
                ) from error
            needle = type_name.lower()
            close = [name for name in namespace_types if needle in name.lower()]
            raise ValueError(
                f"No type '{type_name}' in namespace '{namespace}' for {resolved_version}. "
                f"Did you mean one of: {close or namespace_types}"
            ) from error
        raise
    return utils._with_source(url, markdown)
