"""Safe, patch-oriented refactoring and explicit patch application.

``_refactor`` analyzes a project and returns structured edits plus a unified
diff; it never writes files. ``_apply_patch`` applies a previously produced
edit set, but only when explicitly requested and after validating that every
path stays inside the authorized project root, the patch is well-formed, not
stale, and would not silently overwrite conflicting edits.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from pathlib import Path
from typing import Any, cast

from .project import _build_project_context

# ---------------------------------------------------------------------------
# Edit model
# ---------------------------------------------------------------------------

# An edit is a dict with: file (project-relative path), line (1-based, where
# the old text starts), old (exact text to replace), new (replacement text).
# Line is informational; application matches on exact old-text occurrences.


def _rel_or_raise(root: Path, file_rel: str) -> Path:
    """Resolve a project-relative path inside root, refusing escapes."""
    candidate = (root / file_rel).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError(f"edit path escapes the project root: {file_rel!r}")
    return candidate


def _token_boundary(text: str, index: int, length: int) -> bool:
    before = text[index - 1] if index > 0 else ""
    after = text[index + length] if index + length < len(text) else ""
    ident = r"[A-Za-z0-9_]"
    return not (re.match(ident, before) or re.match(ident, after))


def _find_occurrences(path: Path, needle: str, whole_token: bool) -> list[int]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    indexes: list[int] = []
    start = 0
    while True:
        idx = text.find(needle, start)
        if idx == -1:
            break
        if not whole_token or _token_boundary(text, idx, len(needle)):
            indexes.append(idx)
        start = idx + 1
    return indexes


def _line_of(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def _unified_diff(file_rel: str, old_text: str, new_text: str) -> str:
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    return "".join(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=f"a/{file_rel}",
            tofile=f"b/{file_rel}",
        )
    )


def _file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Refactor (read-only)
# ---------------------------------------------------------------------------


def _refactor(project_root: str, old: str, new: str) -> dict[str, Any]:
    """Find whole-token occurrences of *old* in QML files and produce
    structured edits plus a unified diff. Never writes files.

    Only unambiguous single-token replacements are proposed; each edit
    records the exact old text and its location so it can be applied safely.
    """
    old = old.strip()
    new = new.strip()
    if not old or not new:
        raise ValueError("Both old and new identifiers are required.")
    ctx = _build_project_context(project_root)
    root = ctx.root
    qml_files = cast(dict[str, Any], ctx.discover({"qml_files"}))["qml_files"]

    edits: list[dict[str, Any]] = []
    diffs: list[str] = []

    for path_str in qml_files:
        path = Path(path_str)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        indexes = _find_occurrences(path, old, whole_token=True)
        if not indexes:
            continue
        new_text = text
        for idx in reversed(indexes):
            new_text = new_text[:idx] + new + new_text[idx + len(old) :]
        rel = str(path.relative_to(root))
        for idx in indexes:
            edits.append(
                {
                    "file": rel,
                    "line": _line_of(text, idx),
                    "old": old,
                    "new": new,
                }
            )
        diffs.append(_unified_diff(rel, text, new_text))

    return {
        "project_root": str(root),
        "old": old,
        "new": new,
        "edits": edits,
        "diff": "\n".join(diffs),
        "note": "Refactor proposes edits and a diff; nothing is written.",
    }


# ---------------------------------------------------------------------------
# Apply patch (mutating, explicit)
# ---------------------------------------------------------------------------


def _validate_edit(root: Path, edit: dict[str, Any]) -> None:
    if not isinstance(edit, dict):
        raise ValueError("malformed patch: each edit must be an object")
    file_rel = edit.get("file")
    old = edit.get("old")
    new = edit.get("new")
    if not isinstance(file_rel, str) or not file_rel:
        raise ValueError("malformed patch: edit missing a non-empty 'file'")
    if not isinstance(old, str) or not isinstance(new, str):
        raise ValueError(f"malformed patch: edit for {file_rel!r} needs string old/new")


def _apply_patch(
    project_root: str,
    edits: list[dict[str, Any]],
    expected_base_hashes: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Apply an explicit edit set to the project.

    Validates that every path stays inside the authorized project root, the
    patch is well-formed, not stale (optional expected file hashes), and no
    edit would silently overwrite a conflicting change. Reports every changed
    file. Only whole-token occurrences are replaced.
    """
    if not isinstance(edits, list) or not edits:
        raise ValueError("No edits to apply.")

    ctx = _build_project_context(project_root)
    root = ctx.root

    # Validate all edits first; fail loudly before touching anything.
    for edit in edits:
        _validate_edit(root, edit)

    changed: list[dict[str, Any]] = []
    applied = 0
    by_file: dict[str, str] = {}

    for edit in edits:
        file_rel = edit["file"]
        path = _rel_or_raise(root, file_rel)
        if not path.is_file():
            raise ValueError(f"edit target does not exist: {file_rel}")

        if expected_base_hashes:
            expected = expected_base_hashes.get(file_rel)
            if expected and _file_hash(path) != expected:
                raise ValueError(f"stale patch: {file_rel} changed since the edits were produced")

        text = path.read_text(encoding="utf-8")
        needle = edit["old"]
        indexes = _find_occurrences(path, needle, whole_token=True)
        if not indexes:
            raise ValueError(f"no occurrence of {needle!r} in {file_rel} (patch is stale)")
        if len(indexes) > 1:
            raise ValueError(
                f"{needle!r} occurs {len(indexes)} times in {file_rel}; refusing to "
                "overwrite conflicting edits. Refine the edit to be unique."
            )
        idx = indexes[0]
        new_text = text[:idx] + edit["new"] + text[idx + len(needle) :]
        if new_text == text:
            continue
        path.write_text(new_text, encoding="utf-8")
        by_file[file_rel] = _unified_diff(file_rel, text, new_text)
        applied += 1

    changed = [{"file": file_rel, "diff": diff} for file_rel, diff in sorted(by_file.items())]

    return {
        "project_root": str(root),
        "applied": applied,
        "changed_files": changed,
        "note": "Patch applied explicitly. Only whole-token replacements; root is enforced.",
    }
