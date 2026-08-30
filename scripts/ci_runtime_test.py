#!/usr/bin/env python3
"""Runtime test CI: start an isolated Quickshell session, run a machine-readable
test suite, and exit 0 (all pass) or 1 (failures). Requires a working `qs`
binary and a headless display (e.g. Weston under XDG_RUNTIME_DIR).

Usage: ci_runtime_test.py <project> <suite.json> [--entrypoint E] [--compositor C]
"""

import argparse
import json
import sys
from typing import Any


def run(
    project: str,
    tests: list[dict[str, Any]],
    entrypoint: str | None = None,
    compositor: str | None = None,
) -> int:
    """Run a test suite against an isolated session and return the CI exit
    code (0 all pass, 1 failures, 2 error). Exposed for offline testing."""
    try:
        from quickshell_mcp.sources.runtime_profile import _RuntimeProfile
        from quickshell_mcp.sources.runtime_session import _start_session, _stop_session
        from quickshell_mcp.sources.runtime_test import _run_test_suite
    except ImportError:
        print("ci_runtime_test.py must be run from the quickshell-mcp package", file=sys.stderr)
        return 2

    profile = _RuntimeProfile(project_root=project, entrypoint=entrypoint, compositor=compositor)
    session = _start_session(profile)
    if session.status == "error":
        print(
            json.dumps({"error": "session failed to start", "session": session.to_dict()}),
            file=sys.stdout,
        )
        return 2

    try:
        result = _run_test_suite(session.session_id, tests)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stdout)
        return 2
    finally:
        _stop_session(session)

    output = {
        "session_id": session.session_id,
        "total": result.get("total", 0),
        "passed": result.get("passed", 0),
        "failed": result.get("failed", 0),
        "results": result.get("results", []),
    }
    print(json.dumps(output, indent=2, default=str))

    if result.get("failed"):
        print(
            f"[FAIL] {result.get('failed')} of {result.get('total')} tests failed",
            file=sys.stderr,
        )
        return 1
    print(f"[PASS] {result.get('passed')} of {result.get('total')} tests passed", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a Quickshell test suite in CI")
    parser.add_argument("project", help="Path to the Quickshell project root")
    parser.add_argument("suite", help="Path to a JSON test suite file")
    parser.add_argument("--entrypoint", help="QML entrypoint relative to the project root")
    parser.add_argument("--compositor", help="Compositor backend (e.g. hyprland)")
    args = parser.parse_args()

    try:
        with open(args.suite, encoding="utf-8") as fh:
            tests = json.load(fh)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": f"suite read failed: {exc}"}), file=sys.stdout)
        return 2
    return run(args.project, tests, entrypoint=args.entrypoint, compositor=args.compositor)


if __name__ == "__main__":
    sys.exit(main())
