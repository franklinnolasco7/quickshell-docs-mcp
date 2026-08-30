"""Project style detection: infer reusable UI conventions from existing code.

Evidence-backed only: spacing, typography, colors, corner radius, animation
conventions, component structure, and naming patterns are reported with the
values actually found in the project, never invented.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any, cast

from .project import _build_project_context


def _hex_colors(text: str) -> list[str]:
    return re.findall(r"#(?:[0-9A-Fa-f]{3,8})\b", text)


def _radius_values(text: str) -> list[str]:
    return re.findall(r"\bradius\s*[:=]\s*([0-9.]+)", text)


def _font_sizes(text: str) -> list[str]:
    return re.findall(r"\bpixelSize\s*[:=]\s*([0-9.]+)", text)


def _spacing_values(text: str) -> list[str]:
    return re.findall(r"\b(?:spacing|margins?)\s*[:=]\s*([0-9.]+)", text)


def _animation_ms(text: str) -> list[str]:
    return re.findall(r"\bduration\s*[:=]\s*([0-9.]+)", text)


def _top_values(values: list[str], limit: int = 6) -> list[dict[str, Any]]:
    counted = Counter(values)
    total = sum(counted.values()) or 1
    return [
        {"value": value, "count": count, "share": round(count / total, 2)}
        for value, count in counted.most_common(limit)
    ]


def _style_match(project_root: str) -> dict[str, Any]:
    """Infer reusable UI conventions from a project's existing QML files.

    Reports evidence-backed findings (colors, corner radius, font sizes,
    spacing, animation durations, naming, structure) — no design opinions.
    Each finding lists the values actually present and how common they are.
    """
    ctx = _build_project_context(project_root)
    root = ctx.root
    info = cast(
        dict[str, Any], ctx.discover({"qml_files", "conventions", "components", "environment"})
    )

    colors: list[str] = []
    radii: list[str] = []
    font_sizes: list[str] = []
    spacings: list[str] = []
    durations: list[str] = []
    anim_imports = 0

    for path_str in info["qml_files"]:
        try:
            text = Path(path_str).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        colors.extend(_hex_colors(text))
        radii.extend(_radius_values(text))
        font_sizes.extend(_font_sizes(text))
        spacings.extend(_spacing_values(text))
        durations.extend(_animation_ms(text))
        if "Behavior" in text or "NumberAnimation" in text or "PropertyAnimation" in text:
            anim_imports += 1

    conventions = info["conventions"] or {}

    return {
        "project_root": str(root),
        "findings": {
            "colors": _top_values(colors),
            "corner_radius": _top_values(radii),
            "font_sizes": _top_values(font_sizes),
            "spacing": _top_values(spacings),
            "animation_duration_ms": _top_values(durations),
            "animation_usage": {
                "files_using_animations": anim_imports,
                "status": "detected" if anim_imports else "unknown",
            },
            "naming": {
                "value": conventions.get("file_naming"),
                "status": (
                    "detected"
                    if conventions.get("file_naming") not in (None, "unknown")
                    else "unknown"
                ),
            },
            "structure": {
                "components": len(info["components"] or []),
                "status": "detected" if info["components"] else "unknown",
            },
        },
        "note": "Style findings are evidence-backed from observed values.",
    }
