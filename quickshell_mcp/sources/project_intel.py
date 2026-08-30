"""Project intelligence: structured overview, static relationship map,
project-scoped search, dependency classification, and config conventions.

Every tool here is read-only and builds on ``ProjectContext`` — no tool
re-discovers project state independently and none modifies the project.

Relationship statuses:

* **confirmed** — directly observed (an import statement, a type that matches
  a local file stem)
* **inferred** — derived (a reference we cannot prove resolves locally)
* **unknown** — no data could be found
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, cast

from .project import _build_project_context

# Known namespaces the map/search can resolve without local files. Anything
# else is either a local component or a missing reference.
_KNOWN_NAMESPACES = re.compile(
    r"^(?:Quickshell(?:\.[A-Za-z]+)*|Qt(?:Quick(?:\.[A-Za-z]+)*|Qml|Test|Multimedia|"
    r"GraphicalEffects))$"
)

# How many raw file paths to inline in an overview before summarizing the rest.
_MAX_FILE_LIST = 20
# Context window (lines) around a match in project search results.
_MATCH_CONTEXT = 2


def _rel(project_root: Path, path: str) -> str:
    try:
        return str(Path(path).relative_to(project_root))
    except ValueError:
        return path


def _first_n(items: list[str], limit: int = _MAX_FILE_LIST) -> dict:
    return {"count": len(items), "sample": items[:limit], "truncated": len(items) > limit}


def _analyze_project(project_root: str) -> dict:
    """Structured overview of a Quickshell project, unknown values marked.

    Returns detected/inferred values grouped by concern; nothing is invented
    and no field is silently dropped — absent data is reported as unknown.
    """
    ctx = _build_project_context(project_root)
    info = cast(
        dict[str, Any],
        ctx.discover(
            {
                "qml_files",
                "js_files",
                "entrypoints",
                "imports",
                "quickshell_modules",
                "quickshell_version",
                "qt_version",
                "compositor",
                "config_paths",
                "dependencies",
                "conventions",
                "components",
                "services",
                "runtime_dependencies",
                "environment",
            }
        ),
    )
    root = ctx.root

    imports = info["imports"]
    modules = sorted({imp["module"] for imp in imports})

    def status(name: str) -> str:
        return ctx.detection_status(name)

    def optional(name: str, value) -> dict:
        return {"value": value, "status": status(name)}

    overview: dict[str, dict[str, Any]] = {
        "project_root": {"value": str(root), "status": "detected"},
        "quickshell_version": optional("quickshell_version", info["quickshell_version"]),
        "qt_version": optional("qt_version", info["qt_version"]),
        "compositor": optional("compositor", info["compositor"]),
        "entrypoints": optional("entrypoints", info["entrypoints"]),
        "qml_files": optional("qml_files", _first_n(info["qml_files"])),
        "js_files": optional("js_files", _first_n(info["js_files"])),
        "imports": optional("imports", _first_n(modules)),
        "quickshell_modules": optional("quickshell_modules", info["quickshell_modules"]),
        "dependencies": optional("dependencies", _first_n(info["dependencies"])),
        "config_paths": optional("config_paths", _first_n(info["config_paths"])),
        "components": optional("components", info["components"]),
        "services": optional("services", info["services"]),
        "runtime_dependencies": optional("runtime_dependencies", info["runtime_dependencies"]),
        "environment": optional("environment", info["environment"]),
        "conventions": optional("conventions", info["conventions"]),
    }

    # Keep absolute paths out of the overview; report them relative to root.
    for key in ("entrypoints",):
        if isinstance(overview[key]["value"], list):
            overview[key]["value"] = [_rel(root, p) for p in overview[key]["value"]]

    import_count = len(imports)
    file_count = len(info["qml_files"])
    detected = sum(1 for f in overview.values() if isinstance(f, dict) and f["status"] != "unknown")
    note = (
        f"Detected {file_count} QML file(s) with {import_count} import statement(s); "
        f"{detected} of {len(overview)} overview sections carry data."
    )
    return {
        "project_root": str(root),
        "overview": overview,
        "note": note,
    }


# ---------------------------------------------------------------------------
# Static relationship map
# ---------------------------------------------------------------------------


def _local_stem_index(ctx) -> dict[str, str]:
    """Map a QML file stem to its path (first match wins)."""
    index: dict[str, str] = {}
    for path in cast(dict[str, Any], ctx.discover({"qml_files"}))["qml_files"]:
        stem = Path(path).stem
        index.setdefault(stem, path)
    return index


def _map_project(project_root: str) -> dict:
    """Static project graph: files, imports, component usage, and entrypoints.

    Edges are marked ``confirmed`` (an import statement or a type that matches
    a local file stem) or ``inferred`` (a reference we cannot prove resolves
    locally). Cyclic component usage and references that match no local file
    and no known namespace are reported explicitly.
    """
    ctx = _build_project_context(project_root)
    scan = ctx._scan()
    root = ctx.root
    local_stems = _local_stem_index(ctx)

    nodes: set[str] = set()
    edges: list[dict] = []
    unresolved: list[dict] = []
    usage_edges: list[tuple[str, str]] = []

    def add_node(name: str) -> None:
        nodes.add(name)

    # Nodes: files, modules, entrypoints.
    for path in scan["qml_files"]:
        add_node(_rel(root, path))
    for path in scan["js_files"]:
        add_node(_rel(root, path))
    for imp in scan["imports"]:
        add_node(imp["module"])

    # Confirmed: import statements.
    for imp in scan["imports"]:
        edges.append(
            {
                "from": _rel(root, imp["file"]),
                "to": imp["module"],
                "kind": "import",
                "status": "confirmed",
                "detail": "import statement",
            }
        )

    # Confirmed: object type matches a local file stem -> component usage.
    for obj in scan["objects"]:
        target = local_stems.get(obj["base_name"])
        if target and target != obj["file"]:
            usage_edges.append((obj["file"], target))
            edges.append(
                {
                    "from": _rel(root, obj["file"]),
                    "to": _rel(root, target),
                    "kind": "component_usage",
                    "status": "confirmed",
                    "detail": f"type {obj['base_name']} matches local file",
                }
            )
        elif not target and not _KNOWN_NAMESPACES.match(obj["base_name"]):
            unresolved.append(
                {
                    "type": obj["base_name"],
                    "file": _rel(root, obj["file"]),
                    "detail": "no local component and no known namespace matches",
                }
            )

    # Confirmed: entrypoints.
    for path in scan["entrypoints"]:
        edges.append(
            {
                "from": _rel(root, path),
                "to": None,
                "kind": "entrypoint",
                "status": "confirmed",
                "detail": "root object is a window type",
            }
        )

    # Inferred: a module imported but not resolvable to a local file.
    for imp in scan["imports"]:
        if not _KNOWN_NAMESPACES.match(imp["module"]):
            stem = imp["module"].split(".")[-1]
            if stem not in local_stems and not _KNOWN_NAMESPACES.match(stem):
                edges.append(
                    {
                        "from": _rel(root, imp["file"]),
                        "to": imp["module"],
                        "kind": "import",
                        "status": "inferred",
                        "detail": "module not resolvable to a local component",
                    }
                )

    cycles = _find_cycles(usage_edges)

    return {
        "project_root": str(root),
        "nodes": sorted(nodes),
        "edges": edges,
        "cycles": [
            {
                "files": [_rel(root, path) for path in cycle],
                "status": "confirmed",
            }
            for cycle in cycles
        ],
        "unresolved": unresolved,
        "note": (
            "Edges marked confirmed are directly observed; inferred edges are "
            "references that could not be proven local. Cycles are component "
            "usage cycles between project files."
        ),
    }


def _find_cycles(edges: list[tuple[str, str]]) -> list[list[str]]:
    """Detect simple cycles in a file->file usage graph (each node visited once)."""
    adjacency: dict[str, list[str]] = {}
    for src, dst in edges:
        adjacency.setdefault(src, []).append(dst)

    cycles: list[list[str]] = []
    visited: set[str] = set()
    path: list[str] = []
    on_stack: set[str] = set()

    def dfs(node: str) -> None:
        visited.add(node)
        path.append(node)
        on_stack.add(node)
        for neighbor in adjacency.get(node, []):
            if neighbor in on_stack:
                start = path.index(neighbor)
                cycle = path[start:] + [neighbor]
                if not any(set(cycle) == set(existing) for existing in cycles):
                    cycles.append(cycle)
            elif neighbor not in visited:
                dfs(neighbor)
        on_stack.remove(node)
        path.pop()

    for node in adjacency:
        if node not in visited:
            dfs(node)
    return cycles


# ---------------------------------------------------------------------------
# Project-scoped search
# ---------------------------------------------------------------------------


def _tokenize_query(query: str) -> list[str]:
    return [t for t in re.split(r"[^a-z0-9]+", query.lower()) if len(t) > 1]


def _match_context(text: str, line_index: int) -> str:
    lines = text.splitlines()
    start = max(0, line_index - _MATCH_CONTEXT)
    end = min(len(lines), line_index + _MATCH_CONTEXT + 1)
    return "\n".join(lines[start:end])


def _search_project(project_root: str, query: str) -> dict:
    """Search a Quickshell project for a concept, API, type, or property.

    Returns file, location, match context, and why the result matched. Exact
    textual matches are reported alongside semantic matches (type/property/
    import names), so exact text search remains available.
    """
    ctx = _build_project_context(project_root)
    scan = ctx._scan()
    root = ctx.root
    query_lower = query.lower()
    tokens = _tokenize_query(query)
    results: list[dict] = []

    for path in scan["qml_files"] + scan["js_files"]:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        # Exact textual match.
        exact_match: tuple[int, int] | None = None
        for i, line in enumerate(text.splitlines()):
            col = line.lower().find(query_lower)
            if col != -1:
                exact_match = (i, col)
                break
        if exact_match is not None:
            exact_line, exact_col = exact_match
            results.append(
                {
                    "file": _rel(root, path),
                    "line": exact_line + 1,
                    "column": exact_col + 1,
                    "context": _match_context(text, exact_line),
                    "why": "exact text match",
                    "kind": "exact_text",
                }
            )

        # Semantic match: query tokens against the file's parsed surface. A
        # file may be reported as both exact_text and semantic.
        matched: set[str] = set()
        for obj in scan["objects"]:
            if obj["file"] != path:
                continue
            if any(token in obj["base_name"].lower() for token in tokens):
                matched.add(f"type {obj['base_name']}")
        for imp in scan["imports"]:
            if imp["file"] != path:
                continue
            if any(token in imp["module"].lower() for token in tokens):
                matched.add(f"import {imp['module']}")
        if matched:
            results.append(
                {
                    "file": _rel(root, path),
                    "line": None,
                    "column": None,
                    "context": None,
                    "why": "semantic match: " + ", ".join(sorted(matched)),
                    "kind": "semantic",
                }
            )

    # Rank: exact matches first, then by file path.
    results.sort(key=lambda r: (0 if r["kind"] == "exact_text" else 1, r["file"]))

    return {
        "project_root": str(root),
        "query": query,
        "results": results,
        "note": (
            "Exact text matches come first; semantic matches (types, properties, "
            "imports) follow. A file is reported once per kind."
        ),
    }


# ---------------------------------------------------------------------------
# Dependency classification
# ---------------------------------------------------------------------------


def _classify_module(module: str, local_stems: set[str]) -> str:
    if module.startswith("Quickshell"):
        return "required"
    if module.startswith("Qt"):
        return "required"
    stem = module.split(".")[-1]
    if stem in local_stems:
        return "detected"
    if _KNOWN_NAMESPACES.match(module):
        return "optional"
    return "missing"


def _project_dependencies(project_root: str) -> dict:
    """Classify a project's dependencies without executing anything.

    Categories: required (imported Quickshell/Qt modules), optional (known
    modules without local files), detected (local components, runtime hooks,
    services, config keywords), and missing (imports that resolve to neither a
    known namespace nor a local file).
    """
    ctx = _build_project_context(project_root)
    info = cast(
        dict[str, Any],
        ctx.discover(
            {
                "qml_files",
                "imports",
                "dependencies",
                "components",
                "services",
                "runtime_dependencies",
                "environment",
            }
        ),
    )
    root = ctx.root
    local_stems = {Path(p).stem for p in info["qml_files"]}

    buckets: dict[str, list[str]] = {"required": [], "optional": [], "detected": [], "missing": []}
    for module in sorted(info["dependencies"]):
        buckets[_classify_module(module, local_stems)].append(module)

    runtime = info["runtime_dependencies"] or {}
    for qml_type in runtime.get("qml_types") or []:
        buckets["detected"].append(f"runtime type: {qml_type}")
    for keyword in runtime.get("config") or []:
        buckets["detected"].append(f"config hint: {keyword}")
    services = info["services"] or {}
    for service in services.get("modules") or []:
        buckets["detected"].append(service)
    for service in services.get("objects") or []:
        buckets["detected"].append(f"service object: {service}")
    for env_var in info["environment"] or []:
        buckets["detected"].append(f"env var: {env_var}")

    return {
        "project_root": str(root),
        "dependencies": buckets,
        "note": (
            "Classification is static and evidence-based; nothing is executed "
            "to probe dependencies. 'missing' means an import resolves to "
            "neither a known namespace nor a local component."
        ),
    }


# ---------------------------------------------------------------------------
# Config conventions
# ---------------------------------------------------------------------------


def _config_conventions(project_root: str) -> dict:
    """Detect the project's configuration conventions with confidence levels.

    Reports entrypoints, config files, environment variables, and structural
    conventions. Inferred values carry a confidence; directly observed values
    are reported with high confidence.
    """
    ctx = _build_project_context(project_root)
    info = cast(
        dict[str, Any],
        ctx.discover(
            {
                "entrypoints",
                "config_paths",
                "conventions",
                "environment",
                "runtime_dependencies",
            }
        ),
    )
    root = ctx.root

    conventions = info["conventions"] or {}
    config_files = [
        {"path": _rel(root, p), "extension": Path(p).suffix} for p in info["config_paths"]
    ]

    def with_confidence(name: str, default=None) -> dict:
        value = conventions.get(name, default)
        if value in (None, "unknown"):
            return {"value": None, "confidence": None, "status": "unknown"}
        return {"value": value, "confidence": "high", "status": "detected"}

    runtime = info["runtime_dependencies"] or {}

    return {
        "project_root": str(root),
        "conventions": {
            "file_naming": with_confidence("file_naming"),
            "entrypoint_naming": with_confidence("entrypoint_naming"),
            "directory_layout": with_confidence("directory_layout"),
            "component_dirs": {
                "value": conventions.get("component_dirs", []),
                "confidence": "high" if conventions.get("component_dirs") else None,
                "status": "detected" if conventions.get("component_dirs") else "unknown",
            },
        },
        "entrypoints": {
            "value": [_rel(root, p) for p in info["entrypoints"]],
            "confidence": "high" if info["entrypoints"] else None,
            "status": "detected" if info["entrypoints"] else "unknown",
        },
        "config_files": {
            "value": config_files,
            "confidence": "high" if config_files else None,
            "status": "detected" if config_files else "unknown",
        },
        "environment": {
            "value": info["environment"],
            "confidence": "medium",
            "status": "inferred" if info["environment"] else "unknown",
        },
        "runtime_hints": {
            "value": runtime,
            "confidence": "high" if runtime else None,
            "status": "detected" if runtime else "unknown",
        },
        "note": (
            "Observed values carry high confidence; environment variables are "
            "inferred from source references and marked medium confidence."
        ),
    }
