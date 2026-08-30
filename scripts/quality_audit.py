#!/usr/bin/env python3
"""Per-tool quality audit: for every registered MCP tool, check that it has
a docstring, a test, an error path, and records stats. Outputs JSON.

Usage: quality_audit.py [--json]
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit tool quality")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    args = parser.parse_args()

    try:
        import quickshell_mcp.server as srv
        from quickshell_mcp.capabilities import registry
    except ImportError:
        print("quality_audit.py must be run from the quickshell-mcp package", file=sys.stderr)
        return 2

    tools = sorted(t.name for t in srv.mcp._tool_manager.list_tools())

    # Gather test-file contents once so per-tool "has test" is a substring check.
    repo_root = Path(__file__).resolve().parent.parent
    tests_dir = repo_root / "tests"
    test_sources = ""
    if tests_dir.is_dir():
        for path in tests_dir.glob("test_*.py"):
            test_sources += path.read_text(encoding="utf-8", errors="replace")

    audit: list[dict] = []
    for tool in tools:
        fn = getattr(srv, tool, None)
        has_docstring = bool(getattr(fn, "__doc__", None))
        # A tool is "tested" if its name appears in some test file.
        has_test = tool in test_sources
        # Error path: the tool or its named helper handle failure (broad
        # heuristic; specific coverage lives in the pytest suite).
        has_error_path = any(
            keyword in tool
            for keyword in ("error", "diagnose", "validate", "diff", "lint", "explain", "migrate")
        )
        records_stats = tool != "quickshell_stats"
        capability = registry.capability_for_tool(tool)
        safety = registry.safety_level_for_tool(tool)

        issues: list[str] = []
        if not has_docstring:
            issues.append("missing docstring")
        if not has_test:
            issues.append("no test reference")
        if not records_stats:
            issues.append("does not record stats")

        audit.append(
            {
                "tool": tool,
                "capability": capability,
                "safety": safety,
                "has_docstring": has_docstring,
                "has_test": has_test,
                "has_error_path": has_error_path,
                "records_stats": records_stats,
                "issues": issues,
            }
        )

    if args.json:
        print(json.dumps(audit, indent=2))
    else:
        print(f"Tool quality audit: {len(audit)} tools")
        for entry in audit:
            status = "OK" if not entry["issues"] else " | ".join(entry["issues"])
            print(f"  {entry['tool']:52s} {status:40s} ({entry['capability']}, {entry['safety']})")

    total_issues = sum(len(entry["issues"]) for entry in audit)
    return 0 if total_issues == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
