"""Project intelligence: scoped project memory, architecture recommendations,
and regression detection.

Memory (13.1) is explicit and evidence-backed: each entry records who/what
observed it (``evidence``), a scope tag, and timestamps, and is inspectable
and resettable. Nothing is persisted to disk; the registry is session-scoped
like the runtime profile registry. Architecture recommendations (13.2) cite
their evidence and docs; regression detection (13.3) compares validated state
and screenshots against stored baselines.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, cast

from ..versions import _resolve_version
from .project_intel import _map_project
from .search_all import _search_everything
from .ui_runtime import _screenshot_diff
from .validate import _validate

_MEMORY_SCHEMA_VERSION = 1

# Registry mutations are guarded because the MCP server can dispatch
# concurrent requests; a torn read must never hand out a half-written entry.
_MEMORY_LOCK = threading.RLock()

# In-memory, session-scoped: project_root -> key -> entry.
_PROJECT_MEMORIES: dict[str, dict[str, dict[str, Any]]] = {}


# ---------------------------------------------------------------------------
# Project memory (13.1)
# ---------------------------------------------------------------------------


def _canonical(project: str) -> str:
    return str(Path(project).expanduser().resolve())


def _memory_save(
    project: str,
    key: str,
    content: str,
    evidence: list[str] | None = None,
    scope: str = "general",
) -> dict[str, Any]:
    """Save an explicit, evidence-backed memory entry for a project."""
    root = _canonical(project)
    now = time.time()
    entry = {
        "key": key,
        "content": content,
        "evidence": evidence or [],
        "scope": scope,
        "schema_version": _MEMORY_SCHEMA_VERSION,
        "created_at": now,
        "updated_at": now,
    }
    with _MEMORY_LOCK:
        _PROJECT_MEMORIES.setdefault(root, {})[key] = entry
    return {"project": root, "memory": entry}


def _memory_list(project: str) -> dict[str, Any]:
    """List memory entries for a project with summary metadata."""
    root = _canonical(project)
    entries = []
    with _MEMORY_LOCK:
        for entry in sorted(
            _PROJECT_MEMORIES.get(root, {}).values(), key=lambda e: e["updated_at"]
        ):
            entries.append(
                {
                    "key": entry["key"],
                    "content": entry["content"],
                    "scope": entry["scope"],
                    "evidence_count": len(entry["evidence"]),
                    "updated_at": entry["updated_at"],
                }
            )
    return {"project": root, "count": len(entries), "memories": entries}


def _memory_get(project: str, key: str) -> dict[str, Any]:
    """Get a single memory entry, or raise with the available keys."""
    root = _canonical(project)
    with _MEMORY_LOCK:
        entry = (_PROJECT_MEMORIES.get(root) or {}).get(key)
        if entry is None:
            available = sorted(_PROJECT_MEMORIES.get(root) or {})
            raise ValueError(f"Memory '{key}' not found for {root}. Available: {available}")
        return {"project": root, "memory": entry}


def _memory_clear(project: str, key: str) -> dict[str, Any]:
    """Clear one memory entry from the registry."""
    root = _canonical(project)
    with _MEMORY_LOCK:
        if key not in (_PROJECT_MEMORIES.get(root) or {}):
            available = sorted(_PROJECT_MEMORIES.get(root) or {})
            raise ValueError(f"Memory '{key}' not found for {root}. Available: {available}")
        del _PROJECT_MEMORIES[root][key]
        if not _PROJECT_MEMORIES[root]:
            del _PROJECT_MEMORIES[root]
        return {"project": root, "cleared": key, "remaining": len(_PROJECT_MEMORIES.get(root, {}))}


def _memory_reset(project: str) -> dict[str, Any]:
    """Reset all memory for a project (inspectable, explicit reset)."""
    root = _canonical(project)
    with _MEMORY_LOCK:
        count = len(_PROJECT_MEMORIES.pop(root, {}))
    return {"project": root, "cleared": count, "remaining": 0}


# ---------------------------------------------------------------------------
# Architecture recommendations (13.2)
# ---------------------------------------------------------------------------


def _architecture(project: str, version: str = "latest") -> dict[str, Any]:
    """Produce evidence-backed architecture recommendations for a project.

    Every recommendation cites its evidence (a project observation) and its
    basis (docs/examples/real-world via search_all). Recommendations are
    suggestions, never verdicts.
    """
    resolved = _resolve_version(version)
    graph = _map_project(project)

    recommendations: list[dict[str, Any]] = []
    evidence_notes: list[str] = []

    # Cycles are a concrete, confirmed problem worth flagging.
    cycles = graph.get("cycles") or []
    if cycles:
        evidence_notes.append(f"component usage cycle(s): {len(cycles)} confirmed")
        recommendations.append(
            {
                "concern": "cyclic component usage",
                "recommendation": (
                    "break the cycle by extracting the shared piece into its own component"
                ),
                "evidence": "; ".join(" -> ".join(c.get("files") or []) for c in cycles[:3]),
                "basis": "project structure",
            }
        )

    # Unresolved references that match no local file and no known namespace.
    unresolved = graph.get("unresolved") or []
    if unresolved:
        evidence_notes.append(f"{len(unresolved)} unresolved reference(s)")
        recommendations.append(
            {
                "concern": "unresolved references",
                "recommendation": "check imports/typos or add the missing local component",
                "evidence": "; ".join(
                    f"{u.get('type')} in {u.get('file')}" for u in unresolved[:3]
                ),
                "basis": "project structure",
            }
        )

    # Docs-grounded guidance for the project's entrypoint/style.
    # Best-effort: a failed search must not sink the recommendations.
    try:
        search = _search_everything(
            "Quickshell architecture best practice", resolved, limit_per_source=2
        )
    except (ValueError, RuntimeError):
        search = None
    top = None
    for section in (search or {}).get("section_order") or []:
        entries = ((search or {}).get("results") or {}).get(section) or []
        if entries:
            top = entries[0]
            break
    if top:
        recommendations.append(
            {
                "concern": "entrypoint structure",
                "recommendation": "keep the root window minimal and push logic into components",
                "evidence": "documented guidance",
                "basis": f"quickshell docs ({top.get('url')})",
            }
        )

    return {
        "project": _canonical(project),
        "version": resolved,
        "recommendations": recommendations,
        "evidence": evidence_notes,
        "note": "Recommendations are suggestions citing their evidence; they are not verdicts.",
    }


# ---------------------------------------------------------------------------
# Regression detection (13.3)
# ---------------------------------------------------------------------------


def _regression(
    project: str,
    baseline_screenshot: str | None = None,
    actual_screenshot: str | None = None,
    version: str = "latest",
    threshold: int = 0,
) -> dict[str, Any]:
    """Detect regressions by comparing the current state against a baseline.

    Compares screenshots (when both are given) and validates the current QML
    against the version. Returns confirmed changes and validation issues;
    absent baselines are reported, not fabricated.
    """
    resolved = _resolve_version(version)
    issues: list[dict[str, Any]] = []

    # Validation against the current docs.
    qml_files = _qml_files(project)
    validation_summary = {"files": len(qml_files), "errors": 0, "warnings": 0}
    for path in qml_files:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        result = _validate(text, version=resolved, filename=path)
        errors = [d for d in (result.get("diagnostics") or []) if d.get("severity") == "error"]
        warnings = [d for d in (result.get("diagnostics") or []) if d.get("severity") == "warning"]
        validation_summary["errors"] += len(errors)
        validation_summary["warnings"] += len(warnings)
        for diag in errors[:5]:
            issues.append(
                {
                    "kind": "validation_error",
                    "file": str(path),
                    "message": diag.get("message"),
                    "line": diag.get("line"),
                }
            )

    # Screenshot comparison when a baseline exists.
    screenshot: dict[str, Any] | None = None
    if baseline_screenshot and actual_screenshot:
        screenshot = _screenshot_diff(baseline_screenshot, actual_screenshot)
        if screenshot.get("differs"):
            issues.append(
                {
                    "kind": "visual_regression",
                    "message": "screenshots differ beyond threshold",
                    "metric": screenshot.get("metric"),
                    "threshold": threshold,
                }
            )
    elif baseline_screenshot or actual_screenshot:
        issues.append(
            {
                "kind": "missing_baseline",
                "message": "both baseline and actual screenshots are required for a visual check",
            }
        )

    return {
        "project": _canonical(project),
        "version": resolved,
        "validation": validation_summary,
        "screenshot_diff": screenshot,
        "issues": issues,
        "regression": bool(issues),
        "note": (
            "Only confirmed changes (validation errors, visual diffs) are reported as regressions."
        ),
    }


def _qml_files(project: str) -> list[str]:
    from .project import _build_project_context

    ctx = _build_project_context(project)
    info = cast(dict[str, Any], ctx.discover({"qml_files"}))
    return cast(list[str], info["qml_files"])
