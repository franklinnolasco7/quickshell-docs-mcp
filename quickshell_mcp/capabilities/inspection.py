"""The inspection capability: read and drive the live UI of a managed runtime
session.

Read-only by default (windows, screenshots, ui_tree, ui_find, ui_get_property,
screenshot_diff). ui_set_property and ui_invoke are mutating; ui_eval is
high-risk. All operate on a managed runtime session, never on unrelated
user processes.

Depends on: knowledge, project, runtime.
"""

from __future__ import annotations

from ..sources.ui_runtime import (  # noqa: F401
    _screenshot,
    _screenshot_diff,
    _ui_eval,
    _ui_find,
    _ui_get_property,
    _ui_invoke,
    _ui_set_property,
    _ui_tree,
    _ui_windows,
)

CAPABILITY_NAME = "inspection"
CAPABILITY_TOOLS = (
    "quickshell_windows",
    "quickshell_screenshot",
    "quickshell_screenshot_diff",
    "quickshell_ui_tree",
    "quickshell_ui_find",
    "quickshell_ui_get_property",
    "quickshell_ui_set_property",
    "quickshell_ui_invoke",
    "quickshell_ui_eval",
)
CAPABILITY_DEPENDS_ON = ("knowledge", "project", "runtime")
