#!/usr/bin/env python3
"""Screenshot regression CI: compare a baseline against an actual screenshot
and exit 0 (within threshold) or 1 (regression detected).

Usage: ci_screenshot.py <baseline> <actual> [--threshold N] [--output O]
"""

import argparse
import json
import sys
from typing import Any


def run(baseline: str, actual: str, threshold: int = 0, output: str | None = None) -> int:
    """Compare screenshots and return the CI exit code (0 pass, 1 regression,
    2 error). Exposed separately from ``main`` for offline testing."""
    try:
        from quickshell_mcp.sources.ui_runtime import _screenshot_diff
    except ImportError:
        print("ci_screenshot.py must be run from the quickshell-mcp package", file=sys.stderr)
        return 2

    diff: dict[str, Any]
    try:
        diff = _screenshot_diff(baseline, actual, output=output)
    except Exception as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stdout)
        return 2

    differs = diff.get("differs")
    metric = diff.get("metric")
    regression = differs is True and (metric or 0) > threshold

    output_dict = {
        "baseline": baseline,
        "actual": actual,
        "threshold": threshold,
        "differs": differs,
        "metric": metric,
        "regression": regression,
        "diff_path": diff.get("diff_path"),
    }
    print(json.dumps(output_dict, indent=2, default=str))

    if diff.get("note"):
        print(f"[NOTE] {diff['note']}", file=sys.stderr)

    if regression:
        print(
            f"[FAIL] Visual regression: {metric or 0} differing pixels (threshold {threshold})",
            file=sys.stderr,
        )
        return 1
    print(
        f"[PASS] No visual regression (metric: {metric}, threshold: {threshold})", file=sys.stderr
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare screenshots for regression")
    parser.add_argument("baseline", help="Path to the baseline screenshot")
    parser.add_argument("actual", help="Path to the actual screenshot")
    parser.add_argument(
        "--threshold", type=int, default=0, help="Maximum tolerated differing pixels"
    )
    parser.add_argument("--output", help="Path for the diff image (default temp)")
    args = parser.parse_args()
    return run(args.baseline, args.actual, threshold=args.threshold, output=args.output)


if __name__ == "__main__":
    sys.exit(main())
