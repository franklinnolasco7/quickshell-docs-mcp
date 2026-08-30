"""The knowledge2 capability: versioned API diffs, API dependency graphs,
ranked best practices, cross-project pattern comparison, and provenance.

All tools are read-only and grounded in the official docs, examples, and
indexed real-world shells. Provenance (source, version, URL, authority)
carries through every result.

Depends on: knowledge, validation (compat machinery).
"""

from __future__ import annotations

from ..sources.knowledge2 import (  # noqa: F401
    _api_diff,
    _api_graph,
    _best_practice,
    _pattern_compare,
    _provenance,
)

CAPABILITY_NAME = "knowledge2"
CAPABILITY_TOOLS = (
    "quickshell_api_diff",
    "quickshell_api_graph",
    "quickshell_best_practice",
    "quickshell_pattern_compare",
    "quickshell_provenance",
)
CAPABILITY_DEPENDS_ON = ("knowledge", "validation")
