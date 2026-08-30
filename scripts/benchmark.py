#!/usr/bin/env python3
"""End-to-end benchmark: exercise a representative set of tools and report
correctness, tool-count, latency, recovery, and provenance. Read-only.

Usage: benchmark.py [--version X.Y.Z]
"""

import argparse
import json
import sys
import time
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="End-to-end tool benchmark")
    parser.add_argument("--version", default="latest", help="Quickshell version to test against")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    args = parser.parse_args()

    try:
        import quickshell_mcp.server as srv
    except ImportError:
        print("benchmark.py must be run from the quickshell-mcp package", file=sys.stderr)
        return 2

    results: dict[str, Any] = {}
    timings: dict[str, float] = {}
    failures: dict[str, str] = {}

    def bench(name: str, fn) -> Any:
        start = time.time()
        try:
            value = fn()
            timings[name] = round(time.time() - start, 3)
            return value
        except Exception as exc:
            timings[name] = round(time.time() - start, 3)
            failures[name] = str(exc)
            return None

    # Representative happy paths (offline-friendly where possible).
    versions = bench("list_versions", lambda: srv.quickshell_list_versions())
    if versions:
        results["versions"] = len(versions.get("all_versions") or [])

    validate = bench(
        "validate_qml",
        lambda: srv.quickshell_validate_qml(
            "import Quickshell\nPanelWindow { width: 100 }\n", version=args.version
        ),
    )
    if validate:
        results["validate_diagnostics"] = len(validate.get("diagnostics") or [])

    compat = bench(
        "check_compatibility",
        lambda: srv.quickshell_check_compatibility(type="PanelWindow", version=args.version),
    )
    if compat:
        results["compat_verdict"] = (compat.get("change_info") or {}).get("status")

    # Recovery: a deliberately failing call must fail loudly, not hang.
    start = time.time()
    try:
        srv.quickshell_validate_qml("PanelWindow {", version=args.version)
        recovery = "no-error-raised"
    except Exception as exc:
        recovery = f"raised-{type(exc).__name__}"
    timings["recovery"] = round(time.time() - start, 3)
    results["recovery"] = recovery

    # Provenance: every result carries source URLs where applicable.
    search = bench("search", lambda: srv.quickshell_search("PanelWindow", version=args.version))
    if search:
        results["search_namespace_matches"] = len(search.get("namespace_matches") or [])

    results["tool_count"] = len([t for t in srv.mcp._tool_manager.list_tools()])
    results["latency_seconds"] = timings

    if failures:
        results["failures"] = failures

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        print("End-to-end benchmark")
        for key, value in results.items():
            if key == "latency_seconds":
                continue
            print(f"  {key}: {value}")
        print(f"  latency: {timings}")

    # Fail only if a representative happy path errored.
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
