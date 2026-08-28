"""High-level coding assistant that routes a request through a tool pipeline.

``quickshell_coding_assistant`` is an orchestration layer, not a replacement
for the lower-level tools. It classifies the intent of a plain-language
request, then runs a fixed pipeline of stages - search, verify, generate,
validate, migrate, orchestrate - where each stage activates only the tools the
request needs, so a failing source never sinks the whole response and
redundant searches are avoided.

The pipeline is a dispatch with a fixed stage ordering, acyclic by
construction: no stage re-invokes an earlier one, and the assistant never
schedules itself. Every step delegates to an existing helper, so caching and
URL construction stay in one place. No new fetching, indexing, or generation
lives here, and the module writes nothing to disk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..config import BASE, EXAMPLES_REPO_WEB
from ..versions import _latest_version, _resolve_version, list_versions
from .compat import _changelog_sections, _check_compatibility
from .docs import _guide_page, _type_page
from .explain_error import _explain_error
from .find_pattern import _find_pattern
from .generate import _generate_component
from .implementations import _impl_file
from .migrate import _breaking_lines, _migrate
from .search_all import _search_everything
from .validate import _validate

# Safety bounds. The static pipelines fit comfortably under these; the caps
# exist so a future change cannot fan out unboundedly.
_MAX_STEPS = 12
_MAX_RELEVANT_APIS = 8
_MAX_TYPE_PAGES = 3
_MAX_IMPL_EXCERPT_CHARS = 2000

# Only hyprland has a dedicated Quickshell namespace; the rest are recognized
# so the assistant can say "use WLR types" instead of guessing.
_COMPOSITOR_TOKENS = {"hyprland", "sway", "niri", "i3", "wayfire", "river", "kwin", "weston"}

_VERSION_HINT_RE = re.compile(r"\bv?(\d+\.\d+(?:\.\d+)?(?:-[0-9A-Za-z.-]+)?)\b")
# A lone version introduced by "to <version>" wording is the migration target,
# not the source (e.g. "upgrade to v0.3").
_TO_VERSION_RE = re.compile(r"\bto\s+(?:v?\d+\.\d+)", re.IGNORECASE)

_MIGRATE_RE = re.compile(r"\b(migrat\w*|upgrad\w*|port(?:ing)?\s+to)\b", re.IGNORECASE)
_DEBUG_RE = re.compile(
    r"\b(?:fail\w*|crash\w*|error\w*|broken|not\s+working|doesn'?t\s+work|"
    r"fix(?:es|ed|ing)?|invalid\w*|warning\w*|bug\w*)\b",
    re.IGNORECASE,
)
_PATTERN_RE = re.compile(
    r"\b(find|search|locate|adapt|reuse|reference|existing)\b.{0,40}"
    r"\b(implement|pattern|code|example)\w*\b"
    r"|\b(implement|pattern)\w*\b.{0,40}\b(find|search|adapt)\b",
    re.IGNORECASE,
)
_BUILD_RE = re.compile(
    r"\b(?:build(?:s|ing|er)?|creat(?:e|es|ed|ing)?|mak(?:e|es|ing)?|"
    r"generat(?:e|es|ed|ing)?|add(?:ed|ing|s)?|writ(?:e|es|ing|ten)?|"
    r"compos(?:e|es|ed|ing)?|assembl(?:e|es|ed|ing|y)?|implement(?:s|ed|ing)?)\b",
    re.IGNORECASE,
)


def _detect_compositor(request: str, compositor: str | None) -> str | None:
    if compositor:
        return compositor.strip().lower()
    lowered = request.lower()
    best: tuple[str, int] | None = None
    for token in _COMPOSITOR_TOKENS:
        match = re.search(rf"\b{re.escape(token)}\b", lowered)
        if match and (best is None or match.start() < best[1]):
            best = (token, match.start())
    return best[0] if best else None


def _extract_version_hints(request: str) -> list[str]:
    """Version-looking strings (`0.2`, `v0.3.1`) in order of appearance."""
    return [match.group(1) for match in _VERSION_HINT_RE.finditer(request)]


def _resolve_version_hint(hint: str | None) -> str | None:
    """Resolve a loose version hint (`0.2`, `v0.3`) to a published version.

    Exact versions win; a partial hint prefix-matches the newest published
    version with that prefix (`0.2` -> `v0.2.1`). Resolves against the live
    version list, so nothing here is hardcoded.
    """
    if not hint:
        return None
    hint = hint.strip().lower()
    if hint == "latest":
        return _latest_version()
    normalized = hint if hint.startswith("v") else f"v{hint}"
    known = list_versions()
    if normalized in known:
        return normalized
    prefix = normalized.split("-")[0]
    matches = [
        version for version in known if version.startswith(prefix + ".") or version == prefix
    ]
    return matches[0] if matches else None


def _classify_intent(
    request: str,
    *,
    code: str | None,
    error: str | None,
    from_version: str | None,
    to_version: str | None,
) -> dict[str, Any]:
    """Map a request onto one intent kind plus context the routing needs."""
    hints = _extract_version_hints(request)
    intent_type = "research"
    reason = "no explicit verb matched; treating as a general question"
    if from_version or to_version or _MIGRATE_RE.search(request):
        intent_type = "migrate"
        reason = "explicit version range or migration wording"
    elif error is not None or _DEBUG_RE.search(request):
        intent_type = "debug"
        reason = "error string or failure wording present"
    elif _PATTERN_RE.search(request):
        intent_type = "pattern"
        reason = "request asks to find and adapt an existing implementation"
    elif _BUILD_RE.search(request):
        intent_type = "build"
        reason = "request asks to create or add a component"

    summary = {
        "build": "You want to build or add a component.",
        "debug": "You want to diagnose a failure or error.",
        "migrate": "You want to move code between Quickshell versions.",
        "pattern": "You want to find and adapt an existing implementation.",
        "research": "You want to understand an API or how something works.",
    }[intent_type]

    from_hint: str | None
    to_hint: str | None
    if from_version:
        from_hint = from_version
    elif hints and not (len(hints) == 1 and _TO_VERSION_RE.search(request)):
        from_hint = hints[0]
    else:
        from_hint = None
    if to_version:
        to_hint = to_version
    elif len(hints) == 1 and _TO_VERSION_RE.search(request):
        to_hint = hints[0]
    else:
        to_hint = hints[1] if len(hints) > 1 else None
    return {
        "type": intent_type,
        "reason": reason,
        "summary": summary,
        "compositor": _detect_compositor(request, None),
        "from_version_hint": from_hint,
        "to_version_hint": to_hint,
    }


def _add_source(sources: list[dict[str, str]], title: str, url: str | None) -> None:
    if not url or any(existing["url"] == url for existing in sources):
        return
    sources.append({"title": title, "url": url})


def _safe_step(
    trace: list[dict[str, Any]],
    errors: dict[str, str],
    tool: str,
    reason: str,
    fn,
    expected_kind: str,
) -> Any:
    """Run one pipeline step; record its outcome and isolate failures.

    A step that raises, or returns a shape the caller cannot consume, is
    recorded as ``error``/``malformed`` and the pipeline continues with
    ``None``. Steps are never retried, and the budget cap prevents any future
    pipeline from scheduling more than ``_MAX_STEPS`` steps.
    """
    if len(trace) >= _MAX_STEPS:
        trace.append(
            {
                "step": len(trace) + 1,
                "tool": "step-budget",
                "reason": "refusing to schedule beyond the step budget",
                "status": "error",
                "detail": f"at most {_MAX_STEPS} orchestration steps per request",
            }
        )
        return None
    entry: dict[str, Any] = {"step": len(trace) + 1, "tool": tool, "reason": reason}
    try:
        value = fn()
    except Exception as exc:  # noqa: BLE001 - one failing step must not sink the response
        errors[tool] = str(exc)
        entry["status"] = "error"
        entry["detail"] = str(exc)
        trace.append(entry)
        return None
    if expected_kind == "dict" and not isinstance(value, dict):
        entry["status"] = "malformed"
        entry["detail"] = f"expected dict, got {type(value).__name__}"
        trace.append(entry)
        return None
    if expected_kind == "str" and not isinstance(value, str):
        entry["status"] = "malformed"
        entry["detail"] = f"expected str, got {type(value).__name__}"
        trace.append(entry)
        return None
    entry["status"] = "ok"
    trace.append(entry)
    return value


def _base_result(
    request: str,
    intent: dict[str, Any],
    resolved_version: str,
    trace: list[dict[str, Any]],
    errors: dict[str, str],
) -> dict[str, Any]:
    return {
        "request": request,
        "intent": {
            "type": intent["type"],
            "reason": intent["reason"],
            "summary": intent["summary"],
            "version": resolved_version,
            "compositor": intent["compositor"],
        },
        "understanding": [],
        "relevant_apis": [],
        "recommended_approach": [],
        "implementation_references": [],
        "compatibility": None,
        "validation": None,
        "remaining_issues": [],
        "sources": [],
        "grounded_result": None,
        "orchestration": trace,
        "errors": errors,
        "note": "",
    }


def _validation_issues(validation: dict[str, Any] | None) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for diag in (validation or {}).get("diagnostics", []):
        if diag.get("severity") not in ("error", "warning"):
            continue
        source = diag.get("source")
        issues.append(
            {
                "severity": diag.get("severity"),
                "message": diag.get("message"),
                "line": diag.get("line"),
                "api": diag.get("api"),
                "source": {"text": source.get("text"), "url": source.get("url")}
                if source
                else None,
            }
        )
    return issues


def _assemble(
    result: dict[str, Any],
    *,
    understanding: list[str] | None = None,
    relevant_apis: list[dict[str, Any]] | None = None,
    approach: list[dict[str, str]] | None = None,
    references: list[dict[str, Any]] | None = None,
    compatibility: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
    remaining: list[dict[str, Any]] | None = None,
    sources: list[dict[str, str]] | None = None,
    note: str = "",
) -> dict[str, Any]:
    if understanding is not None:
        result["understanding"] = understanding
    if relevant_apis is not None:
        result["relevant_apis"] = relevant_apis
    if approach is not None:
        result["recommended_approach"] = approach
    if references is not None:
        result["implementation_references"] = references
    if compatibility is not None:
        result["compatibility"] = compatibility
    if validation is not None:
        result["validation"] = validation
    if remaining is not None:
        result["remaining_issues"] = remaining
    if sources is not None:
        result["sources"] = sources
    if note:
        result["note"] = note
    return result


def _append_approach(approach: list[dict[str, str]], step: str, basis: str) -> None:
    if step:
        approach.append({"step": step, "basis": basis})


def _compat_documentation_url(compat: dict[str, Any]) -> str | None:
    for doc in compat.get("documentation") or []:
        if doc.get("url"):
            return doc["url"]
    return None


def _verified(compatibility: str | None) -> bool:
    return compatibility == "compatible"


def _per_api_compatibility(
    per_api: list[dict[str, Any]], namespace: str | None, name: str
) -> str | None:
    for entry in per_api:
        api = entry.get("api") or ""
        if api == name or api.endswith(f".{name}") or api == f"{namespace}.{name}":
            return entry.get("compatibility")
    return None


def _references_from_generate(
    generated: dict[str, Any], sources: list[dict[str, str]]
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    refs = generated.get("references") or {}
    for entry in refs.get("implementations") or []:
        url = entry.get("url")
        _add_source(sources, f"{entry.get('source')} implementation: {entry.get('path')}", url)
        references.append(
            {
                "source": entry.get("source"),
                "path": entry.get("path"),
                "url": url,
                "kind": "real-world implementation",
            }
        )
    for entry in refs.get("examples") or []:
        _add_source(sources, f"official example: {entry.get('path')}", EXAMPLES_REPO_WEB)
        references.append(
            {
                "source": "quickshell-examples",
                "path": entry.get("path"),
                "url": EXAMPLES_REPO_WEB,
                "kind": "official example",
            }
        )
    return references


def _changelog_delta(from_version: str, to_version: str) -> dict[str, Any]:
    """Breaking-change bullets for every published version in the range."""
    sections = _changelog_sections()
    url = sections[0]["url"] if sections else f"{BASE}/changelog/"
    delta: list[dict[str, Any]] = []
    for section in sections:
        version = section["version"]
        if _version_leq(from_version, version) and _version_leq(version, to_version):
            delta.append(
                {
                    "version": version,
                    "url": section["url"],
                    "breaking": _breaking_lines(section["text"]),
                }
            )
    return {"url": url, "sections": delta}


def _version_leq(a: str, b: str) -> bool:
    parts_a = [int(part) for part in re.findall(r"\d+", a.split("-")[0])]
    parts_b = [int(part) for part in re.findall(r"\d+", b.split("-")[0])]
    return parts_a <= parts_b


def _resolve_migration_range(hint_from: str | None, hint_to: str | None) -> dict[str, str | None]:
    """Resolve a migration range to published versions, newest-first tie-break.

    The target defaults to the latest published version when the request does
    not name one; an unresolvable source hint stays ``None`` so the caller can
    ask for explicit versions instead of guessing.
    """
    return {
        "from_version": _resolve_version_hint(hint_from),
        "to_version": _resolve_version_hint(hint_to) or _resolve_version("latest"),
    }


@dataclass
class _PipelineState:
    """Everything the pipeline collects as it walks the stages."""

    request: str
    intent: dict[str, Any]
    trace: list[dict[str, Any]]
    errors: dict[str, str]
    code: str | None = None
    error: str | None = None
    filename: str | None = None
    context: str | None = None
    from_version: str | None = None
    to_version: str | None = None
    resolved_version: str | None = None
    resolved_from: str | None = None
    resolved_to: str | None = None
    # Discovery output.
    search: dict[str, Any] | None = None
    pattern: dict[str, Any] | None = None
    explained: dict[str, Any] | None = None
    generated: dict[str, Any] | None = None
    migration: dict[str, Any] | None = None
    delta: dict[str, Any] | None = None
    type_entries: list[Any] = field(default_factory=list)
    guide_entries: list[Any] = field(default_factory=list)
    pages: list[Any] = field(default_factory=list)
    excerpt: str = ""
    # Verification and synthesis output.
    compat_checks: list[dict[str, Any]] = field(default_factory=list)
    validation: dict[str, Any] | None = None
    compatibility_verdict: str | None = None
    # Assembly output, appended by stages as discovered.
    understanding: list[str] = field(default_factory=list)
    relevant_apis: list[dict[str, Any]] = field(default_factory=list)
    approach: list[dict[str, str]] = field(default_factory=list)
    references: list[dict[str, Any]] = field(default_factory=list)
    remaining: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, str]] = field(default_factory=list)
    note_parts: list[str] = field(default_factory=list)
    note: str = ""


def _stage_search(state: _PipelineState) -> None:
    """Discovery: the collectors the intent needs. Build delegates to the
    generate stage, so its search stages run inside ``_generate_component``."""
    intent_type = state.intent["type"]
    version = state.resolved_version or "latest"

    if intent_type == "build":
        return

    if intent_type == "research":
        search = _safe_step(
            state.trace,
            state.errors,
            "quickshell_search_all",
            "search every source for the request",
            lambda: _search_everything(
                state.request, version, include_content=True, limit_per_source=4
            ),
            "dict",
        )
        if search is None:
            state.understanding.append(f"Search failed for Quickshell {version}.")
            state.note_parts.append("No source could be searched; see errors.")
            return
        state.search = search
        state.type_entries = [
            entry
            for entry in (search.get("results") or {}).get("quickshell_types", [])
            if entry.get("kind") == "api reference"
        ][:_MAX_TYPE_PAGES]
        state.guide_entries = (search.get("results") or {}).get("quickshell_guide_pages", [])[:1]
        state.understanding.append(f"Targeting Quickshell {version}.")
        if state.intent["compositor"]:
            state.understanding.append(
                f"Compositor detected ({state.intent['compositor']}); workspace-type answers "
                "may be compositor-specific."
            )
        section_order = search.get("section_order") or []
        if section_order:
            top_section = section_order[0]
            state.understanding.append(
                f"Best-matching source: {top_section} "
                f"({len((search.get('results') or {}).get(top_section, []))} hit(s))."
            )
        for entry in state.type_entries:
            state.understanding.append(
                f"Type hit: {entry.get('type_name')} in {entry.get('namespace')}."
            )
            _add_source(
                state.sources,
                f"quickshell.org type: {entry.get('type_name')}",
                entry.get("url"),
            )
        return

    if intent_type == "pattern":
        pattern = _safe_step(
            state.trace,
            state.errors,
            "quickshell_find_pattern",
            "find real implementations of the feature",
            lambda: _find_pattern(state.request, version, limit=5),
            "dict",
        )
        if pattern is None:
            state.understanding.append(f"Pattern search failed for Quickshell {version}.")
            state.note_parts.append("No implementation source could be searched; see errors.")
            return
        state.pattern = pattern
        implementations = pattern.get("implementations") or []
        for entry in implementations:
            url = entry.get("url")
            _add_source(
                state.sources, f"{entry.get('source')} implementation: {entry.get('path')}", url
            )
            state.references.append(
                {
                    "source": entry.get("source"),
                    "path": entry.get("path"),
                    "url": url,
                    "topics": entry.get("topics") or [],
                    "kind": "real-world implementation",
                }
            )
        for entry in pattern.get("examples") or []:
            _add_source(state.sources, f"official example: {entry.get('path')}", EXAMPLES_REPO_WEB)
            state.references.append(
                {
                    "source": "quickshell-examples",
                    "path": entry.get("path"),
                    "url": EXAMPLES_REPO_WEB,
                    "kind": "official example",
                }
            )
        if implementations:
            best = implementations[0]
            excerpt = (
                _safe_step(
                    state.trace,
                    state.errors,
                    "quickshell_get_implementation",
                    f"read top implementation: {best.get('path')}",
                    lambda: _impl_file(
                        best.get("source"), best.get("path"), None, _MAX_IMPL_EXCERPT_CHARS
                    ),
                    "str",
                )
                or ""
            )
            if excerpt:
                state.excerpt = excerpt[:_MAX_IMPL_EXCERPT_CHARS]
                state.references[0]["excerpt"] = state.excerpt
        state.understanding.append(f"Targeting Quickshell {version}.")
        interpreted = pattern.get("interpreted_as") or []
        if interpreted:
            state.understanding.append(
                "Request interpreted as: "
                + "; ".join(f"{entry['pattern']} ({entry['why']})" for entry in interpreted)
            )
        else:
            state.understanding.append(
                "No known pattern matched; treating tokens as feature keywords."
            )
        if implementations:
            state.understanding.append(
                f"{len(implementations)} implementation(s) found across "
                f"{sorted({entry.get('source') for entry in implementations})}."
            )
        return

    if intent_type == "debug":
        state.understanding.append(f"Targeting Quickshell {version}.")
        if state.error:
            state.explained = _safe_step(
                state.trace,
                state.errors,
                "quickshell_explain_error",
                "diagnose the reported error",
                lambda: _explain_error(
                    error=state.error,
                    code=state.code,
                    version=version,
                    filename=state.filename,
                ),
                "dict",
            )
            if state.explained:
                category = state.explained.get("error_category")
                state.understanding.append(
                    f"Error categorized as '{category}': {state.explained.get('meaning', '')}"
                )
                fix = state.explained.get("fix")
                if fix:
                    _append_approach(state.approach, fix, "docs")
                for doc in state.explained.get("documentation") or []:
                    _add_source(
                        state.sources,
                        f"quickshell.org guide: {doc.get('title')}",
                        doc.get("url"),
                    )
        return

    if intent_type == "migrate":
        if state.resolved_from is None or state.resolved_to is None:
            return
        state.understanding.append(f"Migrating from {state.resolved_from} to {state.resolved_to}.")
        if not state.code:
            state.delta = _safe_step(
                state.trace,
                state.errors,
                "quickshell_changelog",
                "read breaking changes between the versions",
                lambda: _changelog_delta(state.resolved_from, state.resolved_to),
                "dict",
            )
            if state.delta is not None:
                _add_source(state.sources, "quickshell.org changelog", state.delta.get("url"))
        return


def _stage_verify(state: _PipelineState) -> None:
    """Resolve discovered APIs against the docs and check compatibility.
    Build and migrate check compatibility inside their own synthesis, so this
    stage only serves research, pattern, and debug intents."""
    intent_type = state.intent["type"]
    version = state.resolved_version or "latest"

    if intent_type == "research":
        if state.search is None:
            return
        for entry in state.type_entries:
            namespace = entry.get("namespace") or ""
            type_name = entry.get("type_name")
            if not namespace.startswith("Quickshell") or not type_name:
                continue
            page = _safe_step(
                state.trace,
                state.errors,
                "quickshell_get_type",
                f"resolve API: {namespace}.{type_name}",
                lambda ns=namespace, name=type_name: _type_page(name, ns, version),
                "str",
            )
            if page is not None:
                state.pages.append(
                    {"namespace": namespace, "type_name": type_name, "url": entry.get("url")}
                )
                _add_source(state.sources, f"quickshell.org type: {type_name}", entry.get("url"))
        if state.guide_entries:
            slug = state.guide_entries[0].get("slug")
            guide_page = _safe_step(
                state.trace,
                state.errors,
                "quickshell_get_guide_page",
                f"resolve guide page: {slug}",
                lambda: _guide_page(slug, version),
                "str",
            )
            if guide_page is not None:
                _add_source(
                    state.sources,
                    f"quickshell.org guide: {slug}",
                    state.guide_entries[0].get("url"),
                )
        for entry in state.pages[:_MAX_RELEVANT_APIS]:
            name = entry["type_name"]
            compat = _safe_step(
                state.trace,
                state.errors,
                "quickshell_check_compatibility",
                f"check compatibility of {name}",
                lambda n=name: _check_compatibility(type=n, version=version),
                "dict",
            )
            if compat is None:
                continue
            state.compat_checks.append(compat)
            state.relevant_apis.append(
                {
                    "name": name,
                    "namespace": entry["namespace"],
                    "url": entry["url"],
                    "verified": _verified(compat.get("compatibility")),
                    "compatibility": compat.get("compatibility"),
                }
            )
            _add_source(
                state.sources,
                f"quickshell.org compatibility evidence: {name}",
                _compat_documentation_url(compat),
            )
        content_matches = (state.search.get("results") or {}).get("guide_content", [])
        for match in content_matches[:3]:
            _append_approach(
                state.approach,
                f"Guide '{match.get('slug')}' explains this: "
                f"{match.get('snippet', '').strip()[:240]}",
                "docs",
            )
            _add_source(
                state.sources, f"quickshell.org guide: {match.get('slug')}", match.get("url")
            )
        if not state.approach:
            if state.pages:
                _append_approach(
                    state.approach,
                    f"Read the type pages above "
                    f"({', '.join(p['type_name'] for p in state.pages)}) for properties, "
                    "signals, and methods.",
                    "docs",
                )
            else:
                _append_approach(
                    state.approach,
                    "No documentation matched; try a shorter keyword or a type name.",
                    "inferred",
                )
        if state.guide_entries:
            _append_approach(
                state.approach,
                f"Read the full guide page '{state.guide_entries[0].get('slug')}' for context.",
                "docs",
            )
        return

    if intent_type == "pattern":
        hints: list[str] = []
        for entry in (state.pattern or {}).get("interpreted_as") or []:
            hints.extend(entry.get("apis") or [])
        for group in (state.pattern or {}).get("cross_project_patterns") or []:
            hints.extend(group.get("api_hints") or [])
        unique_hints = list(dict.fromkeys(hints))
        for hint in unique_hints[:_MAX_RELEVANT_APIS]:
            compat = _safe_step(
                state.trace,
                state.errors,
                "quickshell_check_compatibility",
                f"verify hinted API {hint}",
                lambda h=hint: (
                    _check_compatibility(api=h, version=version)
                    if "." in h
                    else _check_compatibility(type=h, version=version)
                ),
                "dict",
            )
            if compat is None:
                continue
            state.compat_checks.append(compat)
            state.relevant_apis.append(
                {
                    "name": hint,
                    "namespace": None,
                    "url": _compat_documentation_url(compat),
                    "verified": _verified(compat.get("compatibility")),
                    "compatibility": compat.get("compatibility"),
                }
            )
            _add_source(
                state.sources,
                f"quickshell.org compatibility evidence: {hint}",
                _compat_documentation_url(compat),
            )
        if state.excerpt:
            _append_approach(
                state.approach,
                f"Adapt the top implementation "
                f"({state.references[0].get('source')} / {state.references[0].get('path')}); "
                "its excerpt is included above.",
                "implementation",
            )
        for group in (state.pattern or {}).get("cross_project_patterns") or []:
            projects = ", ".join(group.get("projects") or {})
            _append_approach(
                state.approach,
                f"Pattern '{group.get('pattern')}' is built by {projects}; compare how each "
                "wires it.",
                "implementation",
            )
        if not state.approach:
            _append_approach(
                state.approach,
                "No implementations matched; research the APIs with quickshell_search_all first.",
                "inferred",
            )
        _append_approach(
            state.approach,
            "Verify every hinted API above against the target version before writing QML.",
            "docs",
        )
        return

    if intent_type == "debug":
        if state.explained:
            relevant_type = state.explained.get("relevant_type") or {}
            type_name = relevant_type.get("type_name")
            namespace = relevant_type.get("namespace")
            if type_name and namespace and namespace.startswith("Quickshell"):
                type_page = _safe_step(
                    state.trace,
                    state.errors,
                    "quickshell_get_type",
                    f"resolve API: {namespace}.{type_name}",
                    lambda ns=namespace, name=type_name: _type_page(name, ns, version),
                    "str",
                )
                if type_page is not None:
                    url = f"{BASE}/docs/{version}/types/{namespace}/{type_name}/"
                    _add_source(state.sources, f"quickshell.org type: {type_name}", url)
                    compat = _safe_step(
                        state.trace,
                        state.errors,
                        "quickshell_check_compatibility",
                        f"check compatibility of {type_name}",
                        lambda n=type_name: _check_compatibility(type=n, version=version),
                        "dict",
                    )
                    if compat is not None:
                        state.compat_checks.append(compat)
                        state.relevant_apis.append(
                            {
                                "name": type_name,
                                "namespace": namespace,
                                "url": url,
                                "verified": _verified(compat.get("compatibility")),
                                "compatibility": compat.get("compatibility"),
                            }
                        )
                        _add_source(
                            state.sources,
                            f"quickshell.org compatibility evidence: {type_name}",
                            _compat_documentation_url(compat),
                        )
            elif type_name:
                state.relevant_apis.append(
                    {
                        "name": type_name,
                        "namespace": namespace,
                        "url": None,
                        "verified": None,
                        "compatibility": None,
                    }
                )
        return


def _stage_generate(state: _PipelineState) -> None:
    """Build requests delegate the whole search/verify/validate pipeline to
    the component generator; nothing else needs generation."""
    if state.intent["type"] != "build":
        return
    version = state.resolved_version or "latest"
    state.generated = _safe_step(
        state.trace,
        state.errors,
        "quickshell_generate_component",
        "generate a component from the request",
        lambda: _generate_component(
            description=state.request,
            version=version,
            compositor=state.intent["compositor"],
            filename=state.filename,
            context=state.context,
        ),
        "dict",
    )
    if state.generated is None:
        state.understanding.append(f"Component generation failed for Quickshell {version}.")
        state.note_parts.append("Generation could not run; see errors for the failed step.")
        return

    generated = state.generated
    state.understanding.append(f"Targeting Quickshell {version}.")
    if state.intent["compositor"]:
        state.understanding.append(f"Compositor detected: {state.intent['compositor']}.")
    interpreted = generated.get("interpreted_as") or []
    if interpreted:
        state.understanding.append(
            "Request interpreted as: "
            + "; ".join(f"{entry['pattern']} ({entry['why']})" for entry in interpreted)
        )
    else:
        state.understanding.append(
            "No curated template matched; returning verified building blocks."
        )
    if generated.get("component"):
        state.understanding.append(
            f"Generated {generated['component']['filename']} "
            f"({'verified' if generated['component'].get('verified') else 'unverified'})."
        )

    verification = generated.get("verification") or {}
    per_api = verification.get("per_api") or []
    state.compat_checks = per_api
    state.compatibility_verdict = verification.get("verdict")
    surface = (generated.get("verified_surface") or {}).get("types") or []
    for entry in surface[:_MAX_RELEVANT_APIS]:
        name = entry.get("type_name")
        namespace = entry.get("namespace")
        verdict = _per_api_compatibility(per_api, namespace, name)
        state.relevant_apis.append(
            {
                "name": name,
                "namespace": namespace,
                "url": entry.get("url"),
                "verified": _verified(verdict),
                "compatibility": verdict,
            }
        )

    component = generated.get("component")
    if component:
        _append_approach(
            state.approach,
            f"Start from the generated {component.get('filename', 'component')}; read the "
            "references below before extending it.",
            "generator",
        )
    for assumption in generated.get("assumptions") or []:
        _append_approach(state.approach, assumption, "inferred")
    _append_approach(
        state.approach,
        "Validate the file with quickshell_validate_qml and fix diagnostics.",
        "validator",
    )

    state.references = _references_from_generate(generated, state.sources)
    for finding in per_api:
        _add_source(state.sources, "quickshell.org compatibility evidence", finding.get("url"))
    for type_entry in surface:
        _add_source(
            state.sources,
            f"quickshell.org type: {type_entry.get('type_name')}",
            type_entry.get("url"),
        )

    state.validation = generated.get("validation")
    state.remaining = _validation_issues(state.validation)
    state.note = generated.get("note") or ""
    if state.context:
        suffix = "existing project context noted but not read"
        state.note = f"{state.note}; {suffix}" if state.note else suffix


def _stage_validate(state: _PipelineState) -> None:
    """Validate QML source against the target version. Build skips this stage
    because the generator already validated its output."""
    intent_type = state.intent["type"]
    if intent_type == "build" or intent_type == "research" or intent_type == "pattern":
        return

    if intent_type == "debug":
        if not state.code:
            return
        version = state.resolved_version or "latest"
        state.validation = _safe_step(
            state.trace,
            state.errors,
            "quickshell_validate_qml",
            "validate the provided QML",
            lambda: _validate(state.code, version=version, filename=state.filename),
            "dict",
        )
        if state.validation is None:
            return
        for diag in state.validation.get("diagnostics", [])[:4]:
            if diag.get("severity") not in ("error", "warning"):
                continue
            source = diag.get("source")
            if source:
                _add_source(
                    state.sources, f"{source.get('text')}: {diag.get('api')}", source.get("url")
                )
            _append_approach(state.approach, diag.get("message"), "validator")
        state.remaining = _validation_issues(state.validation)
        if state.remaining and not state.explained:
            state.understanding.append(f"{len(state.remaining)} validation issue(s) found.")
        if state.explained and not state.remaining:
            state.understanding.append(
                "No validation diagnostics were produced alongside the diagnosis."
            )
        if not state.explained:
            state.understanding.append(
                "No error string given; validation diagnostics drive the diagnosis."
            )
        return

    if intent_type == "migrate":
        if not state.code:
            return
        resolved_to = state.resolved_to or "latest"
        state.validation = _safe_step(
            state.trace,
            state.errors,
            "quickshell_validate_qml",
            f"validate the code against {resolved_to}",
            lambda: _validate(state.code, version=resolved_to, filename=state.filename),
            "dict",
        )
        if state.validation is not None:
            validation_issues = _validation_issues(state.validation)
            state.remaining.extend(validation_issues)
            if validation_issues:
                state.understanding.append(
                    f"{len(validation_issues)} validation issue(s) against {resolved_to}."
                )
        return


def _stage_migrate(state: _PipelineState) -> None:
    if state.intent["type"] != "migrate":
        return
    resolved_from = state.resolved_from or ""
    resolved_to = state.resolved_to or ""
    if state.code:
        state.migration = _safe_step(
            state.trace,
            state.errors,
            "quickshell_migrate",
            "analyze what the code must change",
            lambda: _migrate(
                from_version=resolved_from,
                to_version=resolved_to,
                code=state.code,
                filename=state.filename,
            ),
            "dict",
        )

    if state.migration is not None:
        summary = state.migration.get("summary") or {}
        state.understanding.append(f"Migration verdict: {summary.get('verdict')}.")
        for issue in state.migration.get("issues") or []:
            old = issue.get("old_api") or ""
            new = issue.get("new_api") or ""
            label = new or old
            if label:
                state.relevant_apis.append(
                    {
                        "name": label,
                        "namespace": None,
                        "url": (issue.get("source") or {}).get("url"),
                        "verified": issue.get("classification") in ("definite", "likely"),
                        "compatibility": None,
                    }
                )
            if issue.get("severity") in ("error", "warning"):
                state.remaining.append(
                    {
                        "severity": issue.get("severity"),
                        "message": (
                            f"{issue.get('status')}: {old}"
                            + (f" -> {new}" if new else "")
                            + f" ({issue.get('reason', '')})"
                        ),
                        "line": (issue.get("location") or {}).get("line"),
                        "source": issue.get("source"),
                    }
                )
            source = issue.get("source")
            if source and source.get("url"):
                _add_source(state.sources, "migration evidence", source["url"])
            _append_approach(
                state.approach,
                issue.get("suggestion") or issue.get("reason", ""),
                "changelog"
                if issue.get("classification") in ("definite", "likely")
                else "inferred",
            )
        for plan_step in state.migration.get("migration_plan") or []:
            _append_approach(state.approach, plan_step, "changelog")
        if not state.migration.get("issues"):
            _append_approach(
                state.approach, "No breaking changes were found for this range.", "changelog"
            )
    else:
        for section in (state.delta or {}).get("sections") or []:
            for line in section.get("breaking") or []:
                _append_approach(
                    state.approach, f"[{section['version']}] {line.strip(' -')}", "changelog"
                )
        if not state.approach:
            _append_approach(
                state.approach, "No breaking changes were found for this range.", "changelog"
            )

    if not state.approach:
        _append_approach(
            state.approach,
            "Pass QML code (or an API/type) to get per-symbol migration findings.",
            "inferred",
        )
    state.note_parts.append("migration analysis recommends changes; it never rewrites files")


def _stage_orchestrate(state: _PipelineState) -> dict[str, Any]:
    """Assemble the final structured result, including the grounded terminal
    output the pipeline produced."""
    intent_type = state.intent["type"]
    version = state.resolved_version or "latest"

    verdict = state.compatibility_verdict
    if intent_type == "research" or intent_type == "pattern":
        verdicts = {check.get("compatibility") for check in state.compat_checks}
        if verdicts and verdicts <= {"compatible"}:
            verdict = "compatible"
        elif "incompatible" in verdicts:
            verdict = "incompatible"
        else:
            verdict = None

    result = _base_result(state.request, state.intent, version, state.trace, state.errors)
    note = state.note or "; ".join(part for part in state.note_parts if part)

    grounded = _grounded_result(state)
    return _assemble(
        result,
        understanding=state.understanding,
        relevant_apis=state.relevant_apis,
        approach=state.approach,
        references=state.references,
        compatibility={
            "target_version": version,
            "verdict": verdict,
            "checks": state.compat_checks,
        },
        validation=state.validation,
        remaining=state.remaining,
        sources=state.sources,
        note=note,
    ) | {"grounded_result": grounded}


def _grounded_result(state: _PipelineState) -> dict[str, Any] | None:
    """The pipeline's terminal output: the most useful concrete answer."""
    intent_type = state.intent["type"]
    if intent_type == "build" and state.generated:
        component = state.generated.get("component") or {}
        return {
            "kind": "qml_component",
            "qml": component.get("qml"),
            "filename": component.get("filename"),
            "verified": component.get("verified"),
        }
    if intent_type == "migrate":
        if state.migration:
            return {
                "kind": "migration_plan",
                "from_version": state.resolved_from,
                "to_version": state.resolved_to,
                "verdict": (state.migration.get("summary") or {}).get("verdict"),
                "plan": state.migration.get("migration_plan") or [],
            }
        return {
            "kind": "migration_guidance",
            "from_version": state.resolved_from,
            "to_version": state.resolved_to,
            "breaking": [
                {"version": section.get("version"), "changes": section.get("breaking") or []}
                for section in (state.delta or {}).get("sections") or []
            ],
        }
    if intent_type == "pattern":
        top = state.references[0] if state.references else {}
        return {
            "kind": "implementation_pattern",
            "source": top.get("source"),
            "path": top.get("path"),
            "excerpt": state.excerpt or None,
            "verified_apis": [api["name"] for api in state.relevant_apis if api.get("verified")],
        }
    if intent_type == "research":
        return {
            "kind": "reference",
            "types": state.pages,
            "guides": [
                {"slug": entry.get("slug"), "url": entry.get("url")}
                for entry in state.guide_entries
            ],
        }
    if intent_type == "debug":
        if state.explained:
            return {
                "kind": "diagnosis",
                "category": state.explained.get("error_category"),
                "fix": state.explained.get("fix"),
                "confidence": state.explained.get("confidence"),
                "relevant_type": state.explained.get("relevant_type"),
            }
        return {
            "kind": "validation_report",
            "summary": (state.validation or {}).get("summary"),
        }
    return None


def _coding_assistant(
    request: str,
    version: str = "latest",
    compositor: str | None = None,
    code: str | None = None,
    error: str | None = None,
    filename: str | None = None,
    from_version: str | None = None,
    to_version: str | None = None,
    context: str | None = None,
) -> dict[str, Any]:
    """Route a development request through the pipeline and return a grounded
    result. See the ``quickshell_coding_assistant`` tool docstring."""
    request = (request or "").strip()
    intent = _classify_intent(
        request, code=code, error=error, from_version=from_version, to_version=to_version
    )
    if compositor:
        intent["compositor"] = compositor.strip().lower()

    if not request:
        result = _base_result(request, intent, version, [], {})
        result["intent"]["type"] = None
        result["note"] = "Empty request. Describe the development task in plain words."
        return result

    state = _PipelineState(
        request=request,
        intent=intent,
        trace=[],
        errors={},
        code=code,
        error=error,
        filename=filename,
        context=context,
        from_version=from_version,
        to_version=to_version,
    )

    # Understand: classify (done above), then resolve the version(s). The
    # migrate intent resolves its own range; the rest resolve one target.
    if intent["type"] == "migrate":
        hint_from = from_version or intent.get("from_version_hint")
        hint_to = to_version or intent.get("to_version_hint")
        range_info = _safe_step(
            state.trace,
            state.errors,
            "quickshell_list_versions",
            "resolve the migration range",
            lambda: _resolve_migration_range(hint_from, hint_to),
            "dict",
        )
        state.resolved_from = range_info.get("from_version") if range_info else None
        state.resolved_to = range_info.get("to_version") if range_info else None
        state.resolved_version = state.resolved_to
        if state.resolved_from is None or state.resolved_to is None:
            return {
                **_base_result(
                    state.request,
                    intent,
                    state.resolved_to or state.resolved_from or "latest",
                    state.trace,
                    state.errors,
                ),
                "understanding": [
                    "Could not resolve the migration range from the request text.",
                    "Pass from_version and to_version explicitly, e.g. "
                    "from_version='v0.2.0', to_version='v0.3.1'.",
                ],
                "note": "Version resolution failed; see errors.",
            }
    else:
        resolved_version = _safe_step(
            state.trace,
            state.errors,
            "quickshell_list_versions",
            "resolve the target Quickshell version",
            lambda: _resolve_version(version),
            "str",
        )
        if resolved_version is None:
            return {
                **_base_result(state.request, intent, version, state.trace, state.errors),
                "understanding": [f"Could not resolve Quickshell version '{version}'."],
                "note": "Version resolution failed; see errors.",
            }
        state.resolved_version = resolved_version

    # Pipeline: search -> verify -> generate -> validate -> migrate -> orchestrate.
    _stage_search(state)
    _stage_verify(state)
    _stage_generate(state)
    _stage_validate(state)
    _stage_migrate(state)
    return _stage_orchestrate(state)
