"""HTML -> Markdown extraction, with per-source strip rules."""

import re

from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_md

from . import utils
from .config import _QT_STRIP_SELECTORS, _STRIP_SELECTORS


def _extract_main_content(html: str, strip: list[str] | None = None) -> str:
    soup = BeautifulSoup(html, "html.parser")

    for selector in strip if strip is not None else _STRIP_SELECTORS:
        for tag in soup.select(selector):
            tag.decompose()

    main = soup.find("main") or soup.find("article") or soup.body or soup
    markdown = html_to_md(str(main), heading_style="ATX", bullets="-")
    # Collapse excessive blank lines left over from stripped nav junk.
    markdown = re.sub(r"\n{3,}", "\n\n", markdown).strip()
    return markdown


def _fetch_page_markdown(url: str) -> str:
    return _extract_main_content(utils._fetch_raw(url))


def _fetch_qt_page_markdown(url: str) -> str:
    return _extract_main_content(utils._fetch_raw(url), strip=_QT_STRIP_SELECTORS)
