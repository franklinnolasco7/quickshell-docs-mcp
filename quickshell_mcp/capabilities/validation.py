"""The validation capability: statically validate QML against the docs and
check version compatibility.

Depends on: knowledge (validation builds on the type/guide indexes).
"""

from __future__ import annotations

from ..sources.compat import (  # noqa: F401
    _api_in_version,
    _changelog_hits,
    _changelog_sections,
    _check_compatibility,
    _compat_at,
    _compat_from_code,
    _incorporate_range,
    _parse_api_ref,
    _scan_versions,
)
from ..sources.validate import (  # noqa: F401
    _parse_members,
    _parse_structure,
    _tokenize,
    _validate,
)

CAPABILITY_NAME = "validation"
CAPABILITY_TOOLS = (
    "quickshell_validate_qml",
    "quickshell_check_compatibility",
)
CAPABILITY_DEPENDS_ON = ("knowledge",)
