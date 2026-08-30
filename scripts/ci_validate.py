#!/usr/bin/env python3
"""CI validation entrypoint: validate every QML file in a project and exit
with code 0 (no errors) or 1 (errors found). Outputs machine-readable JSON
to stdout and a human-readable summary to stderr.

Usage: ci_validate.py <project> [--version X.Y.Z]
"""

import argparse
import json
import sys
from typing import Any


def run(project: str, version: str = "latest") -> int:
    """Validate *project* and return the CI exit code (0 pass, 1 fail, 2 error).

    Exposed separately from ``main`` so tests can exercise the logic offline.
    """
    try:
        from quickshell_mcp.sources.project_validate import _validate_project
    except ImportError:
        print("ci_validate.py must be run from the quickshell-mcp package", file=sys.stderr)
        return 2

    result: dict[str, Any]
    try:
        result = _validate_project(project, version=version)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stdout)
        return 2

    summary = result.get("summary", {})
    errors = summary.get("errors", 0)
    warnings = summary.get("warnings", 0)
    files = result.get("files", {})

    output = {
        "project": project,
        "version": version,
        "errors": errors,
        "warnings": warnings,
        "files_validated": len(files),
        "diagnostics": result,
    }
    print(json.dumps(output, indent=2, default=str))

    if errors:
        print(
            f"[FAIL] {errors} error(s), {warnings} warning(s) in {len(files)} file(s)",
            file=sys.stderr,
        )
        return 1
    print(
        f"[PASS] {errors} error(s), {warnings} warning(s) in {len(files)} file(s)",
        file=sys.stderr,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate QML files in a project")
    parser.add_argument("project", help="Path to the Quickshell project root")
    parser.add_argument(
        "--version",
        default="latest",
        help="Quickshell version to validate against (default latest)",
    )
    args = parser.parse_args()
    return run(args.project, version=args.version)


if __name__ == "__main__":
    sys.exit(main())
