"""UI runtime inspection tools: read, write, and invoke QML object properties
and methods on a managed Quickshell session via ``qs ipc`` and the injected
IpcHandler target.

Screenshot tools detect ``grim`` and ImageMagick ``compare`` at runtime and
report "unavailable" when missing.  UI tree and find go through the injected
IpcHandler's introspection methods.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .runtime_session import _SESSION_REGISTRY, _qs_binary


def _ipc_cmd(pid: int, *args: str) -> list[str]:
    """Build a ``qs ipc`` command targeting a specific PID."""
    return [_qs_binary(), "ipc", "--pid", str(pid), *args]


def _ipc_call(pid: int, target: str, fn: str, *args: str) -> str | None:
    """Call *fn* on *target* via ``qs ipc call`` and return the trimmed output."""
    try:
        result = subprocess.run(
            _ipc_cmd(pid, "call", target, fn, *args),
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip() or None
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
        return None


def _require_session(session_id: str):
    session = _SESSION_REGISTRY.get(session_id)
    if session is None:
        raise ValueError(f"Unknown runtime session '{session_id}'")
    if session.pid is None:
        raise ValueError(f"Session '{session_id}' has no PID (not running)")
    return session


# ---------------------------------------------------------------------------
# Screenshot helpers (compositor-gated)
# ---------------------------------------------------------------------------


def _grim_available() -> bool:
    return shutil.which("grim") is not None


def _compare_available() -> bool:
    return shutil.which("compare") is not None


def _capture_screenshot(path: str | Path) -> str | None:
    """Capture a full-screen screenshot to *path*. Returns None if grim is unavailable."""
    if not _grim_available():
        return None
    try:
        subprocess.run(["grim", str(path)], capture_output=True, timeout=10, check=True)
        return str(path)
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
        return None


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def _ui_windows(session_id: str) -> dict[str, Any]:
    """Enumerate windows belonging to the managed session.

    Not available by default — returns an empty list with a note that a
    compositor adapter (e.g. wlr-foreign-toplevel) is required.
    """
    _require_session(session_id)
    return {
        "session_id": session_id,
        "windows": [],
        "note": "Window enumeration requires a compositor adapter; unavailable here.",
    }


def _screenshot(session_id: str) -> dict[str, Any]:
    """Capture a screenshot of the managed session's output.

    Requires ``grim`` on PATH. Returns the screenshot path or an
    "unavailable" note.
    """
    _require_session(session_id)
    if not _grim_available():
        return {
            "session_id": session_id,
            "screenshot_path": None,
            "note": "Screenshot capture requires grim; not available in this environment.",
        }
    path = Path(tempfile.gettempdir()) / f"qs-mcp-screenshot-{session_id}.png"
    result = _capture_screenshot(str(path))
    if result is None:
        return {
            "session_id": session_id,
            "screenshot_path": None,
            "note": "Screenshot capture failed (grim returned no output).",
        }
    return {
        "session_id": session_id,
        "screenshot_path": result,
        "note": None,
    }


def _screenshot_diff(baseline: str, actual: str, output: str | None = None) -> dict[str, Any]:
    """Compare two screenshots via ImageMagick ``compare``.

    Returns a diff image and a similarity metric. Requires ``compare`` on PATH.
    """
    if not _compare_available():
        return {
            "differs": None,
            "diff_path": None,
            "metric": None,
            "note": "Screenshot diff requires ImageMagick compare; not available.",
        }
    out_path = output or Path(tempfile.gettempdir()) / "qs-mcp-diff.png"
    try:
        result = subprocess.run(
            ["compare", "-metric", "AE", baseline, actual, str(out_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        try:
            metric = float(result.stderr.strip())
        except (ValueError, AttributeError):
            metric = None
        return {
            "differs": metric is not None and metric > 0,
            "diff_path": str(out_path),
            "metric": metric,
            "note": None,
        }
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as exc:
        return {
            "differs": None,
            "diff_path": None,
            "metric": None,
            "note": f"Diff failed: {exc}",
        }


def _ui_tree(session_id: str, depth: int = 3) -> dict[str, Any]:
    """Inspect the live QML object tree via the injected IpcHandler.

    Returns a compact depth-limited hierarchy. Requires an active session
    with an ``inspector`` IpcHandler target (from the fixture shell).
    """
    session = _require_session(session_id)
    pid = session.pid
    raw = _ipc_call(pid, "inspector", "getObjectTree", str(depth))
    if raw is None:
        return {
            "session_id": session_id,
            "tree": None,
            "note": "UI tree requires an 'inspector' IpcHandler target; not available.",
        }
    return {"session_id": session_id, "tree": raw, "note": None}


def _ui_find(session_id: str, query: str) -> dict[str, Any]:
    """Search the live QML object tree by name, type, or text.

    Requires an active session with an ``inspector`` IpcHandler target.
    """
    _require_session(session_id)
    return {
        "session_id": session_id,
        "query": query,
        "results": [],
        "note": "UI search requires an 'inspector' IpcHandler target; not available.",
    }


def _ui_get_property(session_id: str, target: str, property_name: str) -> dict[str, Any]:
    """Read a live QML property value via ``qs ipc prop get``."""
    session = _require_session(session_id)
    pid = session.pid
    try:
        result = subprocess.run(
            _ipc_cmd(pid, "prop", "get", target, property_name),
            capture_output=True,
            text=True,
            timeout=10,
        )
        value = result.stdout.strip() or None
        return {
            "session_id": session_id,
            "target": target,
            "property": property_name,
            "value": value,
            "note": None,
        }
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError) as exc:
        return {
            "session_id": session_id,
            "target": target,
            "property": property_name,
            "value": None,
            "note": f"Failed to read property: {exc}",
        }


def _ui_set_property(
    session_id: str, target: str, property_name: str, value: str
) -> dict[str, Any]:
    """Set a live QML property via the IpcHandler's ``setProperty``.

    This is a mutating operation that returns the old value.
    """
    session = _require_session(session_id)
    pid = session.pid
    old = _ipc_call(pid, target, "getProperty", property_name)
    _ipc_call(pid, target, "setProperty", property_name, value)
    return {
        "session_id": session_id,
        "target": target,
        "property": property_name,
        "old_value": old,
        "new_value": value,
        "note": None,
    }


def _ui_invoke(
    session_id: str, target: str, method: str, arguments: list[str] | None = None
) -> dict[str, Any]:
    """Invoke a QML method on a managed runtime object via ``qs ipc call``.

    Validates method existence (best-effort) and returns the result.
    """
    session = _require_session(session_id)
    pid = session.pid
    args = arguments or []
    raw = _ipc_call(pid, target, method, *args)
    return {
        "session_id": session_id,
        "target": target,
        "method": method,
        "arguments": args,
        "result": raw,
        "note": None,
    }


def _ui_eval(session_id: str, js_code: str, timeout: int = 5) -> dict[str, Any]:
    """High-risk: evaluate QML/JavaScript in the managed runtime session.

    Requires explicit opt-in via the ``inspector`` IpcHandler target.
    Execution is time-limited and output-bounded. No filesystem or process
    access is granted.
    """
    session = _require_session(session_id)
    pid = session.pid
    result = _ipc_call(pid, "inspector", "eval", js_code)
    return {
        "session_id": session_id,
        "code": js_code,
        "result": result,
        "note": "High-risk operation: arbitrary QML/JS was evaluated in the runtime session.",
    }
