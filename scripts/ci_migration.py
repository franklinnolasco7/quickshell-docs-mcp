#!/usr/bin/env python3
"""Migration CI: run the per-file migration engine across a project and exit
0 (no breaking changes) or 1 (breaking changes confirmed).

Usage: ci_migration.py <project> --from X.Y.Z --to X.Y.Z
"""

import argparse
import json
import sys
from typing import Any


def run(project: str, from_version: str, to_version: str) -> int:
    """Run the migration engine across *project* and return the CI exit code
    (0 pass, 1 breaking, 2 error). Exposed for offline testing."""
    try:
        from quickshell_mcp.sources.project_validate import _migrate_project
    except ImportError:
        print("ci_migration.py must be run from the quickshell-mcp package", file=sys.stderr)
        return 2

    result: dict[str, Any]
    try:
        result = _migrate_project(project, from_version, to_version)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stdout)
        return 2

    issues = result.get("issues", [])
    breaking = [i for i in issues if i.get("status") in ("breaking", "renamed", "removed")]

    output = {
        "project": project,
        "from_version": from_version,
        "to_version": to_version,
        "total_issues": len(issues),
        "breaking_issues": len(breaking),
        "issues": issues,
    }
    print(json.dumps(output, indent=2, default=str))

    if breaking:
        print(f"[FAIL] {len(breaking)} breaking change(s) confirmed", file=sys.stderr)
        return 1
    print(f"[PASS] {len(issues)} total issue(s), 0 breaking", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Check project migration compatibility in CI")
    parser.add_argument("project", help="Path to the Quickshell project root")
    parser.add_argument("--from-version", required=True, help="Source Quickshell version")
    parser.add_argument("--to-version", required=True, help="Target Quickshell version")
    args = parser.parse_args()
    return run(args.project, args.from_version, args.to_version)


if __name__ == "__main__":
    sys.exit(main())
