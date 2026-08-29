"""The knowledge capability: read and search Quickshell docs, Qt types,
official examples, and real-world implementations.

Depends on: (none in the capability layer — pulls directly from shared services).
"""

from __future__ import annotations

from ..sources.docs import (  # noqa: F401
    GUIDE_LINK_RE,
    TYPE_LINK_RE,
    _build_index,
    _guide_content_index,
    _guide_page,
    _resolve_version,
    _search_guide_content,
    _search_type_content,
    _type_page,
)
from ..sources.examples import (  # noqa: F401
    _example_file,
    _examples_branch,
    _examples_known_paths,
    _examples_listing,
)
from ..sources.find_pattern import _find_pattern, _interpret_query  # noqa: F401
from ..sources.implementations import (  # noqa: F401
    _GITHUB_API,
    _IMPL_QUERY_STOPWORDS,
    _IMPL_TOPICS,
    _impl_branch,
    _impl_component,
    _impl_entry_meta,
    _impl_file,
    _impl_repo_config,
    _impl_topics_for_query,
    _norm_source,
    _search_implementations,
)
from ..sources.qt_docs import (  # noqa: F401
    _QT_ANCHOR_RE,
    _QT_MODULE_LINK_RE,
    _QT_TYPE_LINK_RE,
    _VALUE_TYPES_BUCKET,
    _build_qt_index,
    _normalize_qt_module,
    _qt_type_page,
    _resolve_qt_slug,
)
from ..sources.search_all import _search_everything  # noqa: F401

CAPABILITY_NAME = "knowledge"
CAPABILITY_TOOLS = (
    "quickshell_list_versions",
    "quickshell_about",
    "quickshell_changelog",
    "quickshell_list_guide_pages",
    "quickshell_get_guide_page",
    "quickshell_list_types",
    "quickshell_get_type",
    "quickshell_search",
    "quickshell_search_all",
    "quickshell_find_pattern",
    "quickshell_list_qt_types",
    "quickshell_get_qt_type",
    "quickshell_list_examples",
    "quickshell_get_example",
    "quickshell_search_implementations",
    "quickshell_get_implementation",
)
CAPABILITY_DEPENDS_ON: tuple[str, ...] = ()
