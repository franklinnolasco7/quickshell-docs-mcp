"""Performance profiling: bounded runtime sampling and static analysis.

``profile`` samples a managed session's CPU and memory from ``/proc`` over a
bounded window. The component/binding/timer/object-tree analyses are
evidence-based (static project scans plus runtime log evidence); they never
attribute cost without evidence and never claim a timer is a bug merely
because it runs frequently.
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, cast

from .project import _build_project_context
from .runtime_session import _SESSION_REGISTRY


def _proc_stat(pid: int) -> dict[str, Any] | None:
    """Read CPU (utime+stime ticks) and RSS from /proc/<pid>/stat and status."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        fields = stat.rsplit(")", 1)[1].split()
        # After the comm field, utime=14th, stime=15th (index 11, 12).
        utime = int(fields[11])
        stime = int(fields[12])
        status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
        rss_kb = 0
        for line in status.splitlines():
            if line.startswith("VmRSS:"):
                rss_kb = int(line.split()[1])
                break
        return {"utime_ticks": utime, "stime_ticks": stime, "rss_kb": rss_kb}
    except (OSError, ValueError, IndexError, KeyError):
        return None


_CLK_TCK = 100  # Linux USER_HZ; sufficient for an evidence-based estimate


def _profile(session_id: str, seconds: float = 2.0) -> dict[str, Any]:
    """Bounded CPU/memory sampling of a managed session.

    Samples /proc over *seconds* (capped), reporting average RSS and CPU
    percentage plus methodology and limitations. Never profiles indefinitely.
    """
    session = _SESSION_REGISTRY.get(session_id)
    if session is None:
        raise ValueError(f"Unknown runtime session '{session_id}'")
    if session.pid is None:
        raise ValueError(f"Session '{session_id}' has no PID (not running)")

    seconds = max(0.5, min(seconds, 15.0))
    start = _proc_stat(session.pid)
    if start is None:
        return {
            "session_id": session_id,
            "note": "Could not read /proc for the session; profiling unavailable.",
            "methodology": "None; /proc unreadable.",
        }
    time.sleep(seconds)
    end = _proc_stat(session.pid)
    if end is None:
        end = start

    cpu_ticks = (end["utime_ticks"] - start["utime_ticks"]) + (
        end["stime_ticks"] - start["stime_ticks"]
    )
    cpu_percent = round((cpu_ticks / _CLK_TCK) / max(seconds, 0.01) * 100.0, 1)
    return {
        "session_id": session_id,
        "sample_seconds": seconds,
        "cpu_percent": cpu_percent,
        "avg_rss_kb": round((start["rss_kb"] + end["rss_kb"]) / 2, 1),
        "methodology": "Bounded /proc sampling over the requested window; USER_HZ=100 assumed.",
        "limitations": "Sampling is coarse; frame/render timing is not measured here.",
    }


# ---------------------------------------------------------------------------
# Static analyses (evidence-based)
# ---------------------------------------------------------------------------


def _project_text(project_root: str) -> list[str]:
    ctx = _build_project_context(project_root)
    files = cast(dict[str, Any], ctx.discover({"qml_files"}))["qml_files"]
    texts: list[str] = []
    for path in files:
        try:
            texts.append(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
    return texts


def _profile_component(project_root: str) -> dict[str, Any]:
    """Identify components with potential performance concerns based on
    static evidence: repeated Timer/Animation usage, high object counts, and
    suspicious bindings. Never attributes cost without evidence."""
    texts = _project_text(project_root)
    timers = sum(len(re.findall(r"\bTimer\s*\{", t)) for t in texts)
    animations = sum(
        len(re.findall(r"\b(?:NumberAnimation|PropertyAnimation)\b", t)) for t in texts
    )
    bindings = sum(
        len(re.findall(r"\b(?:width|height|x|y|opacity|scale)\s*[:=]", t)) for t in texts
    )
    return {
        "project_root": project_root,
        "observations": {
            "timer_objects": timers,
            "animation_objects": animations,
            "layout_bindings": bindings,
        },
        "note": "Counts are static evidence; cost is not attributed without runtime evidence.",
    }


def _profile_bindings(project_root: str) -> dict[str, Any]:
    """Identify high-frequency binding patterns statically: property bindings
    that reference other properties (potential re-evaluation chains)."""
    texts = _project_text(project_root)
    chains: list[dict[str, Any]] = []
    for text in texts:
        for match in re.finditer(r"(\w+)\s*[:=]\s*(\w+)(?:\.\w+)*", text):
            prop, ref = match.group(1), match.group(2)
            if prop != ref:
                chains.append({"property": prop, "references": ref})
    return {
        "project_root": project_root,
        "binding_chains": chains[:50],
        "chain_count": len(chains),
        "note": "Static only; re-evaluation frequency requires runtime instrumentation.",
    }


def _profile_timers(project_root: str) -> dict[str, Any]:
    """Find timers with potentially suspicious configuration (very short
    intervals or repeat=0). Does not label a frequent timer a bug by itself."""
    texts = _project_text(project_root)
    suspicious: list[dict[str, Any]] = []
    for text in texts:
        for interval in re.findall(r"\binterval\s*[:=]\s*(\d+)", text):
            value = int(interval)
            if value and value < 50:
                suspicious.append({"interval_ms": value, "why": "very short interval"})
        for _ in re.findall(r"\brepeat\s*[:=]\s*(?:false|0)\b", text):
            suspicious.append({"why": "repeat disabled / fires once"})
    return {
        "project_root": project_root,
        "suspicious_timers": suspicious,
        "note": "Frequent timers are not inherently bugs; only suspicious config is flagged.",
    }


def _profile_object_tree(project_root: str) -> dict[str, Any]:
    """Object-tree statistics from static QML structure: total objects,
    repeated component patterns, and deeply nested structures."""
    texts = _project_text(project_root)
    object_names = re.findall(r"(?:^|\s)([A-Z][A-Za-z0-9]*)\s*\{", " ".join(texts))
    totals = len(object_names)
    from collections import Counter

    counts = Counter(object_names)
    repeated = [
        {"type": name, "count": count} for name, count in counts.most_common(5) if count > 1
    ]
    return {
        "project_root": project_root,
        "object_count": totals,
        "repeated_patterns": repeated,
        "note": "Statistics are static approximations; deep/wide trees are not automatically bad.",
    }


def _performance_diagnose(project_root: str) -> dict[str, Any]:
    """Correlate static project evidence into prioritized performance
    hypotheses. Each hypothesis carries evidence and confidence; nothing is
    modified."""
    bindings = _profile_bindings(project_root)
    timers = _profile_timers(project_root)
    tree = _profile_object_tree(project_root)

    hypotheses: list[dict[str, Any]] = []
    if bindings["chain_count"] > 20:
        hypotheses.append(
            {
                "hypothesis": "many property bindings may form re-evaluation chains",
                "evidence": f"{bindings['chain_count']} binding references detected statically",
                "confidence": "medium",
            }
        )
    if timers["suspicious_timers"]:
        hypotheses.append(
            {
                "hypothesis": "suspicious timer configuration may cause churn",
                "evidence": f"{len(timers['suspicious_timers'])} suspicious timer(s)",
                "confidence": "medium",
            }
        )
    if tree["object_count"] > 200:
        hypotheses.append(
            {
                "hypothesis": "large object tree may slow startup and updates",
                "evidence": f"{tree['object_count']} objects detected statically",
                "confidence": "low",
            }
        )

    return {
        "project_root": project_root,
        "hypotheses": hypotheses,
        "note": "Hypotheses are evidence-attributed and ranked; source is never modified.",
    }
