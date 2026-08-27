"""Code-quality gates exposed as pytest tests, so `pytest` alone verifies
lint + formatting + types. CI additionally runs the tools directly; this
suite makes local runs one-stop.

Tools are probed rather than assumed: environments without them (or with
broken wheels, e.g. glibc-ruff on NixOS) skip instead of failing.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PKG = "quickshell_mcp"
TIMEOUT_SECS = 180


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=TIMEOUT_SECS)


def _tool_works(module: str) -> bool:
    """True if `<module> --version` runs via interpreter or PATH binary."""
    if _run([sys.executable, "-m", module, "--version"]).returncode == 0:
        return True
    binary = shutil.which(module)
    return bool(binary) and _run([binary, "--version"]).returncode == 0


def _invoke(module: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run the tool through the interpreter if possible, else PATH."""
    via_module = [sys.executable, "-m", module, *args]
    result = _run(via_module)
    if not (
        result.returncode != 0
        and "No module named" in (result.stderr or "")
        and shutil.which(module)
    ):
        return result
    return _run([shutil.which(module) or module, *args])


RUFF_AVAILABLE = _tool_works("ruff")
MYPY_AVAILABLE = _tool_works("mypy")


@pytest.mark.skipif(not RUFF_AVAILABLE, reason="ruff unavailable in this environment")
def test_ruff_lint_clean():
    result = _invoke("ruff", ["check", "."])
    assert result.returncode == 0, f"ruff check failed:\n{result.stdout}\n{result.stderr}"


@pytest.mark.skipif(not RUFF_AVAILABLE, reason="ruff unavailable in this environment")
def test_ruff_format_clean():
    result = _invoke("ruff", ["format", "--check", "."])
    assert result.returncode == 0, (
        f"ruff format --check failed (run 'ruff format .'):\n{result.stdout}\n{result.stderr}"
    )


@pytest.mark.skipif(not MYPY_AVAILABLE, reason="mypy unavailable in this environment")
def test_mypy_clean():
    result = _invoke("mypy", [PKG])
    assert result.returncode == 0, f"mypy failed:\n{result.stdout}\n{result.stderr}"
