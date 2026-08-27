"""doc.qt.io: QtQuick base types and sibling modules that the Quickshell docs
link to but don't host themselves."""

import re
from typing import cast

import httpx

from .. import utils
from ..caches import _cache_get, _cache_set, _disk_get, _disk_set
from ..config import QT_DOCS_BASE
from ..extraction import _fetch_qt_page_markdown

_QT_TYPE_LINK_RE = re.compile(r"href=\"qml-([a-z0-9.-]+)\.html\"")
_QT_MODULE_LINK_RE = re.compile(r"href=\"([a-z0-9-]+)-qmlmodule\.html\"")
# Link text preserves the real CamelCase type name; slugs are all lowercase.
_QT_ANCHOR_RE = re.compile(r"href=\"qml-([a-z0-9.-]+)\.html\"[^>]*>([^<]+)<")

_VALUE_TYPES_BUCKET = "value-types"


def _qt_type_name(slug_rest: str) -> str:
    return "".join(part.capitalize() for part in slug_rest.split("-"))


def _qt_docs_base(qt_version: str | None) -> str:
    """doc.qt.io serves every minor (newest directly, older via /archives/
    redirects), so a pinned Qt version is just a different base path."""
    if not qt_version or qt_version.strip().lower() in ("latest", "6"):
        return QT_DOCS_BASE
    normalized = qt_version.strip().lower().removeprefix("qt-").removeprefix("v")
    if not re.fullmatch(r"6\.\d+", normalized):
        raise ValueError(
            f"Invalid Qt version '{qt_version}'. Use 'latest' or a minor like '6.8' or '6.7'."
        )
    return f"https://doc.qt.io/qt-{normalized}"


def _build_qt_index(refresh: bool = False, qt_version: str | None = None) -> dict:
    base = _qt_docs_base(qt_version)
    cache_key = f"qt_index:{base}"
    if not refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached
        disk_cached = _disk_get(cache_key)
        if disk_cached is not None:
            index = cast(dict, disk_cached)
            _cache_set(cache_key, index)
            return index

    # Pass 1 walks the QtQuick module page and every sibling *qmlmodule.html
    # it links to. Pass 2 splits slugs by longest matching known module prefix,
    # so qtquick-controls-abstractbutton lands under qtquick-controls, not qtquick.
    pages: dict[str, str] = {}
    raw_slugs: set[str] = set()
    display_names: dict[str, str] = {}
    seen_pages: set[str] = set()
    pending = ["qtquick-qmlmodule"]
    while pending:
        page = pending.pop(0)
        if page in seen_pages:
            continue
        seen_pages.add(page)
        html = utils._fetch_raw(f"{base}/{page}.html")
        pages[page.removesuffix("-qmlmodule")] = f"{base}/{page}.html"
        for module_slug in _QT_MODULE_LINK_RE.findall(html):
            if f"{module_slug}-qmlmodule" not in seen_pages:
                pending.append(f"{module_slug}-qmlmodule")
        raw_slugs.update(_QT_TYPE_LINK_RE.findall(html))
        for slug, link_text in _QT_ANCHOR_RE.findall(html):
            display_names.setdefault(slug, link_text.strip())

    known_modules = sorted(pages, key=len, reverse=True)
    type_slugs: dict[str, list[str]] = {}
    for slug in raw_slugs:
        owning_module = next((m for m in known_modules if slug.startswith(f"{m}-")), None)
        if owning_module is not None:
            type_slug = slug[len(owning_module) + 1 :]
        elif "-" not in slug:
            # Prefix-less slugs (color, vector3d...) are QML value types.
            owning_module, type_slug = _VALUE_TYPES_BUCKET, slug
        else:
            # A prefix whose module page was never linked (qtqml-component)
            # still gets its own bucket.
            owning_module, _, type_slug = slug.partition("-")
        bucket = type_slugs.setdefault(owning_module, [])
        if type_slug not in bucket:
            bucket.append(type_slug)

    modules = {
        m: sorted(display_names.get(f"{m}-{s}", _qt_type_name(s)) for s in slugs)
        for m, slugs in type_slugs.items()
        if m != _VALUE_TYPES_BUCKET
    }
    if _VALUE_TYPES_BUCKET in type_slugs:
        # Value-type link text is lowercase in Qt's docs (color, vector3d);
        # keep it verbatim rather than force-casing it.
        modules[_VALUE_TYPES_BUCKET] = sorted(
            display_names.get(s, _qt_type_name(s)) for s in type_slugs[_VALUE_TYPES_BUCKET]
        )
    index = {"modules": modules, "pages": pages}
    utils.log.info(
        "built Qt index: %d module(s), %d type(s)",
        len(modules),
        sum(len(names) for names in modules.values()),
    )
    _cache_set(cache_key, index)
    _disk_set(cache_key, index)
    return index


def _normalize_qt_module(module_name: str) -> str:
    # Users may write qtquick-controls or QtQuick.Controls.
    return module_name.strip().lower().replace(".", "-")


def _resolve_qt_slug(
    name: str, module: str | None, qt_version: str | None = None
) -> tuple[str, str]:
    """Map a type name (+ optional module) to (slug, module); raises a
    friendly ValueError with did-you-mean candidates on no/ambiguous match."""
    index = _build_qt_index(qt_version=qt_version)
    modules = index["modules"]
    wanted = _normalize_qt_module(module) if module else None
    if module and wanted not in {_normalize_qt_module(m) for m in modules}:
        known = sorted(modules, key=str.lower)
        raise ValueError(f"Unknown Qt module '{module}'. Known modules: {', '.join(known)}")

    def names_in_scope() -> list[tuple[str, str]]:
        return [
            (m, n)
            for m, names in modules.items()
            if not module or _normalize_qt_module(m) == wanted
            for n in names
        ]

    query_lower = name.lower().strip().removesuffix(".html").removeprefix("qml-")
    exact_matches = [(m, n) for m, n in names_in_scope() if n.lower() == query_lower]
    if len(exact_matches) > 1:
        pretty = ", ".join(sorted(f"{m}.{n}" for m, n in exact_matches))
        raise ValueError(f"'{name}' is ambiguous across Qt modules: {pretty}")
    if exact_matches:
        matched_module, matched_name = exact_matches[0]
        slug = (
            matched_name.lower()
            if matched_module == _VALUE_TYPES_BUCKET
            else f"{matched_module}-{matched_name.lower()}"
        )
        return slug, matched_module
    close = sorted({f"{m}.{n}" for m, n in names_in_scope() if query_lower in n.lower()})
    scope = f"in module '{module}' " if module else ""
    raise ValueError(
        f"No Qt type '{name}' {scope}in the doc.qt.io index. "
        f"Did you mean one of: {close or sorted(n for _, n in names_in_scope())}"
    )


def _qt_type_page(name: str, module: str | None, qt_version: str | None = None) -> str:
    slug, _ = _resolve_qt_slug(name, module, qt_version)
    url = f"{_qt_docs_base(qt_version)}/qml-{slug}.html"
    try:
        markdown = _fetch_qt_page_markdown(url)
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 404:
            raise ValueError(
                f"The doc.qt.io page for '{name}' ({url}) returned 404; "
                "that Qt version may not exist on doc.qt.io."
            ) from error
        raise
    return utils._with_source(url, markdown)
