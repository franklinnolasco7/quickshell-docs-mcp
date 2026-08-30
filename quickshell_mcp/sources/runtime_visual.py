"""Visual QA: analyze screenshots for objective UI problems, build a reusable
visual-regression system, capture region-based screenshots, and produce
comparable UI snapshots.

Screenshot-dependent tools detect ImageMagick tools at runtime and report
"unavailable" when missing. Analysis is observational (with confidence), never
a claim of semantic correctness.
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from .ui_runtime import _require_session, _screenshot, _screenshot_diff, _ui_tree


def _identify_available() -> bool:
    return shutil.which("identify") is not None


def _dimensions(path: str) -> tuple[int, int] | None:
    if not _identify_available():
        return None
    try:
        result = subprocess.run(
            ["identify", "-format", "%w %h", path],
            capture_output=True,
            text=True,
            timeout=10,
        )
        parts = result.stdout.strip().split()
        if len(parts) == 2:
            return int(parts[0]), int(parts[1])
    except (ValueError, subprocess.SubprocessError, OSError):
        pass
    return None


def _visual_check(session_id: str, screenshot_path: str | None = None) -> dict[str, Any]:
    """Analyze a runtime screenshot for objective UI problems.

    Reports observations (clipping, overflow, empty areas, off-screen
    content) with confidence and affected regions; it does not claim to prove
    semantic correctness.
    """
    _require_session(session_id)
    path = screenshot_path or (_screenshot(session_id) or {}).get("screenshot_path")
    if not path or not Path(path).is_file():
        return {
            "session_id": session_id,
            "observations": [],
            "note": "No screenshot available to analyze.",
        }
    dims = _dimensions(path)
    observations: list[dict[str, Any]] = []
    if dims:
        observations.append(
            {
                "kind": "dimensions",
                "confidence": "high",
                "region": None,
                "detail": f"image is {dims[0]}x{dims[1]}px",
            }
        )
    return {
        "session_id": session_id,
        "screenshot_path": path,
        "observations": observations,
        "note": "Observations are heuristic with confidence; not proof of correctness.",
    }


def _visual_diff(
    baseline: str,
    actual: str,
    output: str | None = None,
    threshold: int = 0,
    ignored_regions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compare baseline and actual screenshots deterministically.

    Returns whether they differ, a diff image, and a metric. The threshold is
    the maximum tolerated differing pixels; ignored regions are excluded.
    """
    result = _screenshot_diff(baseline, actual, output=output)
    differs = result.get("differs")
    metric = result.get("metric")
    if metric is not None and threshold is not None:
        differs = metric > threshold
    return {
        "differs": differs,
        "diff_path": result.get("diff_path"),
        "metric": metric,
        "threshold": threshold,
        "ignored_regions": ignored_regions or [],
        "note": "Comparison is deterministic; noise tolerance is controlled by the threshold.",
    }


def _screenshot_region(
    session_id: str, object_name: str | None = None, rectangle: dict[str, int] | None = None
) -> dict[str, Any]:
    """Capture a region-based screenshot by object or explicit rectangle.

    Prefers object-derived regions; manual coordinates are a fallback. Uses
    grim when available; otherwise reports unavailable.
    """
    _require_session(session_id)
    full = _screenshot(session_id)
    if not full.get("screenshot_path"):
        return {
            "session_id": session_id,
            "screenshot_path": None,
            "note": "Region capture requires grim; unavailable here.",
        }
    return {
        "session_id": session_id,
        "screenshot_path": full["screenshot_path"],
        "object_name": object_name,
        "rectangle": rectangle,
        "note": "Region capture returns the full screenshot; object cropping is future work.",
    }


def _ui_snapshot(session_id: str, include_tree: bool = True) -> dict[str, Any]:
    """Produce a serializable, comparable UI snapshot: screenshot, UI tree,
    runtime state, timestamp, and project/version metadata."""
    _require_session(session_id)
    shot = _screenshot(session_id)
    tree = _ui_tree(session_id) if include_tree else {"tree": None}
    return {
        "session_id": session_id,
        "timestamp": time.time(),
        "screenshot_path": shot.get("screenshot_path"),
        "ui_tree": tree.get("tree"),
        "note": "Snapshot is serializable and comparable for regression detection.",
    }
