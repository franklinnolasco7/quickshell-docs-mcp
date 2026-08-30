#!/usr/bin/env python3
"""API compatibility CI: check a set of APIs against a Quickshell version and
fail only on confirmed incompatibilities.

Usage: ci_api_compat.py <apis.json> [--version X.Y.Z]
where apis.json is a JSON array of API references, e.g. ["PanelWindow", "Quickshell.shellDir"].
"""

import argparse
import json
import sys
from typing import Any


def run(apis: list[str], version: str = "latest") -> int:
    """Check *apis* against *version* and return the CI exit code (0 pass,
    1 incompatible, 2 error). Exposed for offline testing."""
    try:
        from quickshell_mcp.sources.compat import _check_compatibility
    except ImportError:
        print("ci_api_compat.py must be run from the quickshell-mcp package", file=sys.stderr)
        return 2

    confirmed: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    for api in apis:
        try:
            result = _check_compatibility(api=api, version=version)
        except Exception as exc:
            unknown.append({"api": api, "error": str(exc)})
            continue
        verdict = (result.get("change_info") or {}).get("status")
        if verdict in ("removed", "renamed", "deprecated"):
            confirmed.append(
                {
                    "api": api,
                    "status": verdict,
                    "detail": (result.get("change_info") or {}).get("detail"),
                    "url": ((result.get("change_info") or {}).get("documentation") or [{}])[0].get(
                        "url"
                    ),
                }
            )
        elif verdict == "not_found":
            unknown.append({"api": api, "status": "not_found", "detail": "not found in docs"})
        elif verdict != "compatible":
            unknown.append({"api": api, "status": verdict})

    output = {"version": version, "confirmed": confirmed, "unknown": unknown}
    print(json.dumps(output, indent=2, default=str))

    if confirmed:
        print(f"[FAIL] {len(confirmed)} confirmed incompatible API(s)", file=sys.stderr)
        return 1
    print(f"[PASS] no confirmed incompatible APIs ({len(unknown)} unverifiable)", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Check API compatibility in CI")
    parser.add_argument("apis", help="Path to a JSON array of API references")
    parser.add_argument("--version", default="latest", help="Quickshell version to check against")
    args = parser.parse_args()

    try:
        with open(args.apis, encoding="utf-8") as fh:
            apis = json.load(fh)
    except (OSError, ValueError) as exc:
        print(json.dumps({"error": f"apis file read failed: {exc}"}), file=sys.stdout)
        return 2
    return run(apis, version=args.version)


if __name__ == "__main__":
    sys.exit(main())
