"""Error diagnosis for Quickshell/QML errors.

Parses common QML error messages, verifies reported properties/methods/signals
against the Quickshell and Qt type indexes, and returns a structured diagnosis
grounded in the actual documentation rather than guesswork.
"""

from __future__ import annotations

import re
from difflib import get_close_matches

from ..versions import _resolve_version
from .docs import _build_index, _search_guide_content
from .qt_docs import _build_qt_index

_ERROR_PATTERNS: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(
            r"Cannot assign to non-existent property\s+'(?P<property>[^']+)'",
            re.IGNORECASE,
        ),
        "non_existent_property",
        "property",
    ),
    (
        re.compile(
            r"Cannot assign to non-existent default property on\s+(?P<type>\S+)",
            re.IGNORECASE,
        ),
        "non_existent_property",
        "type",
    ),
    (
        re.compile(
            r"Type\s+'(?P<type>[^']+)'\s+is not accessible",
            re.IGNORECASE,
        ),
        "unknown_type",
        "type",
    ),
    (
        re.compile(
            r"Could not find or load the component\s+(?P<type>\S+)",
            re.IGNORECASE,
        ),
        "component_not_found",
        "type",
    ),
    (
        re.compile(
            r"module\s+'(?P<module>[^']+)'\s+is not installed",
            re.IGNORECASE,
        ),
        "missing_import",
        "module",
    ),
    (
        re.compile(
            r"namespace\s+'(?P<module>[^']+)'\s+is not installed",
            re.IGNORECASE,
        ),
        "missing_import",
        "module",
    ),
    (
        re.compile(
            r"Cannot connect to non-existent signal\s+'(?P<signal>[^']+)'",
            re.IGNORECASE,
        ),
        "unknown_signal",
        "signal",
    ),
    (
        re.compile(
            r"(?P<method>\S+)\s+is not a function",
            re.IGNORECASE,
        ),
        "unknown_method",
        "method",
    ),
    (
        re.compile(
            r"Unknown method\s+(?P<method>\S+)",
            re.IGNORECASE,
        ),
        "unknown_method",
        "method",
    ),
    (
        re.compile(
            r"Invalid assignment\s+.*?Expected\s+'?(?P<expected>\S+?)['\"\s]",
            re.IGNORECASE,
        ),
        "type_mismatch",
        "expected",
    ),
    (
        re.compile(
            r"Cannot assign\s+\S+\s+to\s+(?P<expected>\S+)",
            re.IGNORECASE,
        ),
        "type_mismatch",
        "expected",
    ),
    (
        re.compile(
            r"Invalid binding\s+.*?property\s+'(?P<property>[^']+)'",
            re.IGNORECASE,
        ),
        "binding_error",
        "property",
    ),
    (
        re.compile(
            r"Cannot apply binding to value property\s+'(?P<property>[^']+)'",
            re.IGNORECASE,
        ),
        "binding_error",
        "property",
    ),
]

_QML_TYPE_RE = re.compile(r"^(\s*)([A-Z]\w+(?:\.\w+)*)\s*\{", re.MULTILINE)


def _categorize_error(error: str) -> tuple[str, dict[str, str | None]]:
    """Match an error string against known QML patterns.

    Returns ``(category, entities)`` where *entities* holds whatever named
    groups the matched pattern defined (``type``, ``property``, ``method``,
    ``signal``, ``module``, ``expected``).
    """
    for regex, category, _group in _ERROR_PATTERNS:
        match = regex.search(error)
        if match:
            return category, {k: v for k, v in match.groupdict().items() if v is not None}
    return "unknown", {}


def _extract_type_from_code(code: str) -> str | None:
    """Extract the root QML type name from a code snippet."""
    match = _QML_TYPE_RE.search(code)
    return match.group(2) if match else None


def _lookup_quickshell_type(type_name: str, version: str) -> dict | None:
    """Check whether *type_name* exists in the Quickshell index.

    Returns ``{"namespace": ..., "type_name": ...}`` or ``None``.
    """
    index = _build_index(version)
    for ns, names in index["types_by_namespace"].items():
        if type_name in names:
            return {"namespace": ns, "type_name": type_name}
    return None


def _lookup_qt_type(type_name: str) -> dict | None:
    """Check whether *type_name* exists in the Qt type index."""
    index = _build_qt_index()
    for module, names in index["modules"].items():
        if type_name in names:
            return {"module": module, "type_name": type_name}
    return None


def _find_similar_types(type_name: str, version: str) -> list[dict]:
    """Return up to 5 similar Quickshell type names for suggestion."""
    index = _build_index(version)
    all_names: list[str] = []
    for _ns, names in index["types_by_namespace"].items():
        for name in names:
            all_names.append(name)
    matches = get_close_matches(type_name, all_names, n=5, cutoff=0.4)
    if not matches:
        needle = type_name.lower()
        matches = [n for n in all_names if needle in n.lower() or n.lower() in needle][:5]
    results = []
    for ns, names in index["types_by_namespace"].items():
        for name in names:
            if name in matches:
                results.append({"namespace": ns, "type_name": name})
    results.sort(key=lambda r: matches.index(r["type_name"]) if r["type_name"] in matches else 99)
    return results


def _find_similar_qt_types(type_name: str) -> list[dict]:
    """Return up to 5 similar Qt type names for suggestion."""
    index = _build_qt_index()
    all_names: list[str] = []
    for _module, names in index["modules"].items():
        for name in names:
            all_names.append(name)
    matches = get_close_matches(type_name, all_names, n=5, cutoff=0.4)
    if not matches:
        needle = type_name.lower()
        matches = [n for n in all_names if needle in n.lower() or n.lower() in needle][:5]
    results = []
    for module, names in index["modules"].items():
        for name in names:
            if name in matches:
                results.append({"module": module, "type_name": name})
    results.sort(key=lambda r: matches.index(r["type_name"]) if r["type_name"] in matches else 99)
    return results


def _fetch_type_markdown(type_name: str, namespace: str, version: str) -> str | None:
    """Fetch a Quickshell type page as markdown. Returns ``None`` on failure."""
    url = f"https://quickshell.org/docs/{version}/types/{namespace}/{type_name}/"
    try:
        from ..extraction import _fetch_page_markdown

        return _fetch_page_markdown(url)
    except Exception:  # noqa: BLE001
        return None


def _fetch_qt_type_markdown(type_name: str, module: str | None = None) -> str | None:
    """Fetch a Qt type page as markdown. Returns ``None`` on failure."""
    try:
        from .qt_docs import _qt_type_page

        return _qt_type_page(type_name, module, "latest")
    except Exception:  # noqa: BLE001
        return None


def _search_type_page_for(markdown: str, name: str) -> bool:
    """Check whether *name* appears as a heading or bold term in a type page."""
    name_lower = name.lower()
    name_bound = re.compile(rf"(?<!\w){re.escape(name_lower)}(?!\w)")
    # markdownify may escape asterisks as \*\*
    for line in markdown.splitlines():
        line_stripped = line.strip()
        line_norm = line_stripped.replace("\\*", "*")
        if line_norm.lower().startswith("### ") and name_bound.search(line_norm.lower()):
            return True
        if name_bound.search(line_norm.lower()) and "**" in line_norm:
            return True
        if re.match(rf"^{re.escape(name)}\s*[:\(]", line_stripped, re.IGNORECASE):
            return True
    return False


def _find_similar_properties(markdown: str, prop_name: str) -> list[str]:
    """Find property-like names in *markdown* that are similar to *prop_name*."""
    candidates: list[str] = []
    for line in markdown.splitlines():
        line_stripped = line.strip()
        if line_stripped.lower().startswith("### "):
            heading = line_stripped[4:].strip()
            heading = re.sub(r"[*`\\]+", "", heading)
            word = heading.split()[0] if heading.split() else ""
            if word and word[0].islower():
                candidates.append(word)
        for bold in re.findall(r"[*\\]+\*+(\w+)[*\\]+\*+", line_stripped):
            if bold and bold[0].islower():
                candidates.append(bold)
        for bold in re.findall(r"\*\*(\w+)\*\*", line_stripped):
            if bold and bold[0].islower():
                candidates.append(bold)
    candidates = list(dict.fromkeys(candidates))  # dedupe preserving order
    return get_close_matches(prop_name, candidates, n=3, cutoff=0.4)


def _search_related_docs(
    type_name: str | None, category: str, version: str
) -> list[dict[str, str]]:
    """Find guide pages relevant to the error context."""
    results: list[dict[str, str]] = []
    query_terms: list[str] = []
    if type_name:
        query_terms.append(type_name)
    _CATEGORY_TERMS: dict[str, list[str]] = {
        "non_existent_property": ["properties", "qml-language"],
        "unknown_type": ["types", "qml-language", "introduction"],
        "type_mismatch": ["types", "qml-language"],
        "unknown_signal": ["signals", "qml-language"],
        "unknown_method": ["methods", "qml-language"],
        "missing_import": ["install-setup", "qml-language", "introduction"],
        "component_not_found": ["components", "types"],
        "binding_error": ["bindings", "qml-language", "size-position"],
    }
    query_terms.extend(_CATEGORY_TERMS.get(category, []))

    seen_slugs: set[str] = set()
    for term in query_terms:
        for match in _search_guide_content(term, version, limit=3):
            slug = match["slug"]
            if slug not in seen_slugs:
                seen_slugs.add(slug)
                results.append({"slug": slug, "url": match["url"], "snippet": match["snippet"]})
    return results[:5]


_MEANINGS: dict[str, str] = {
    "non_existent_property": (
        "The QML engine does not recognize the specified property on the "
        "target type. The property does not exist in the type's declared "
        "properties."
    ),
    "unknown_type": (
        "The QML engine cannot find a registered type with this name. Either "
        "the type does not exist, or the required import is missing."
    ),
    "component_not_found": (
        "The QML engine could not locate the specified component file or "
        "registered type. The component may not be installed or may be "
        "misspelled."
    ),
    "missing_import": (
        "A required QML module is not installed or not imported in the file. "
        "QML types live in modules that must be explicitly imported."
    ),
    "unknown_signal": ("The signal does not exist on the target type, or the type was misspelled."),
    "unknown_method": (
        "The method or function does not exist on the target type, or the call syntax is incorrect."
    ),
    "type_mismatch": (
        "A value of one type is being assigned where a different type is "
        "expected. QML is partially type-checked at load time."
    ),
    "binding_error": (
        "A binding expression is being assigned to a property that does not "
        "accept bindings, or there is a conflict between imperative and "
        "declarative assignments."
    ),
}

_LIKELY_CAUSES: dict[str, str] = {
    "non_existent_property": (
        "The property name is misspelled or the property belongs to a "
        "different type than the one being used."
    ),
    "unknown_type": (
        "The type name is misspelled, the wrong namespace is used, or the "
        "required module import is missing."
    ),
    "component_not_found": (
        "The component file path is wrong, the component is in a different "
        "directory, or the type is not registered."
    ),
    "missing_import": (
        "The QML file is missing an 'import' statement for the module that "
        "provides the type being used."
    ),
    "unknown_signal": (
        "The signal name is misspelled, or the signal belongs to a parent "
        "type that must be accessed differently."
    ),
    "unknown_method": (
        "The method name is misspelled, or the method is not available on "
        "this type. Check the type's documentation for available methods."
    ),
    "type_mismatch": (
        "The assigned value's type does not match the property's declared "
        "type. Common cases: assigning a string to an int property, or "
        "assigning a color string where an int is expected."
    ),
    "binding_error": (
        "An imperative assignment (e.g., in JavaScript) conflicts with a "
        "declarative binding, or the property is a value type that cannot "
        "receive bindings."
    ),
}


def _build_diagnosis(
    category: str,
    entities: dict[str, str | None],
    qs_type: dict | None,
    qt_type: dict | None,
    markdown: str | None,
    version: str,
    related_docs: list[dict],
    code: str | None,
    confidence: str,
) -> dict:
    type_name = entities.get("type")
    prop_name = entities.get("property")
    method_name = entities.get("method")
    signal_name = entities.get("signal")
    module_name = entities.get("module")

    relevant_type: dict | None = qs_type or qt_type
    api_exists: bool | None = None
    correct_api: str | None = None
    fix = ""

    if category == "non_existent_property" and prop_name and markdown:
        exists = _search_type_page_for(markdown, prop_name)
        api_exists = exists
        if not exists:
            similar = _find_similar_properties(markdown, prop_name)
            if similar:
                correct_api = similar[0]
                fix = f"Property '{prop_name}' does not exist. Did you mean '{similar[0]}'?"
                if len(similar) > 1:
                    fix += f" Other possibilities: {', '.join(similar[1:])}"
            else:
                fix = (
                    f"Property '{prop_name}' does not exist on "
                    f"{relevant_type and relevant_type.get('type_name', 'this type')}. "
                    "Check the type's documentation for available properties."
                )
        else:
            fix = f"Property '{prop_name}' exists. Check the value type and assignment syntax."

    elif category == "unknown_signal" and signal_name and markdown:
        exists = _search_type_page_for(markdown, signal_name)
        api_exists = exists
        if not exists:
            fix = (
                f"Signal '{signal_name}' does not exist on "
                f"{relevant_type and relevant_type.get('type_name', 'this type')}. "
                "Check the type's documentation for available signals."
            )
        else:
            fix = f"Signal '{signal_name}' exists. Check the connection syntax."

    elif category == "unknown_method" and method_name and markdown:
        exists = _search_type_page_for(markdown, method_name)
        api_exists = exists
        if not exists:
            fix = (
                f"Method '{method_name}' does not exist on "
                f"{relevant_type and relevant_type.get('type_name', 'this type')}. "
                "Check the type's documentation for available methods."
            )
        else:
            fix = f"Method '{method_name}' exists. Check the call arguments."

    elif category == "unknown_type" or category == "component_not_found":
        if not relevant_type:
            qs_similar = _find_similar_types(type_name or "", version) if type_name else []
            qt_similar = _find_similar_qt_types(type_name or "") if type_name else []
            all_similar = qs_similar + qt_similar
            if all_similar:
                names = [
                    f"{s.get('namespace', s.get('module', ''))}.{s['type_name']}"
                    for s in all_similar[:3]
                ]
                correct_api = all_similar[0]["type_name"]
                fix = f"Type '{type_name}' not found. Did you mean: {', '.join(names)}?"
            else:
                fix = (
                    f"Type '{type_name}' not found in Quickshell or Qt docs. "
                    "Check spelling and ensure the required module is imported."
                )
        else:
            fix = (
                f"Type '{type_name}' exists in "
                f"{relevant_type.get('namespace', relevant_type.get('module', ''))}. "
                "Check the import statement."
            )

    elif category == "missing_import":
        fix = f"Import the required module, e.g.: import {module_name or 'ModuleName'}"

    elif category == "type_mismatch":
        expected = entities.get("expected")
        if expected:
            fix = (
                f"The property expects a value of type '{expected}'. "
                "Cast or convert the assigned value."
            )
        else:
            fix = "Check the property's declared type and ensure the assigned value matches."

    elif category == "binding_error":
        prop = entities.get("property")
        if prop:
            fix = (
                f"Property '{prop}' may not accept bindings, or there is a "
                "conflict between imperative and declarative assignments. "
                "Use either a binding or an imperative assignment, not both."
            )
        else:
            fix = "Check for conflicts between declarative bindings and imperative assignments."

    elif category == "unknown":
        fix = "Could not determine a specific fix from this error message."

    version_notes = ""
    if version and version != "latest":
        version_notes = f"Results are for Quickshell version {version}."
    else:
        version_notes = "Results are for the latest Quickshell version."

    doc_refs = []
    for doc in related_docs:
        ref: dict[str, str] = {"title": doc["slug"], "url": doc["url"]}
        if "snippet" in doc:
            ref["snippet"] = doc["snippet"]
        doc_refs.append(ref)

    result: dict = {
        "error_category": category,
        "meaning": _MEANINGS.get(category, "Unable to classify this error."),
        "likely_cause": _LIKELY_CAUSES.get(category, "The cause could not be determined."),
        "relevant_type": relevant_type,
        "api_exists": api_exists,
        "correct_api": correct_api,
        "documentation": doc_refs,
        "fix": fix,
        "version_notes": version_notes,
        "confidence": confidence,
    }

    # Only include non-None entities to keep the response clean
    extracted = {k: v for k, v in entities.items() if v is not None}
    if extracted:
        result["extracted"] = extracted

    return result


def _explain_error(
    error: str,
    code: str | None = None,
    version: str = "latest",
    filename: str | None = None,
    line_number: int | None = None,
    component: str | None = None,
) -> dict:
    """Diagnose a Quickshell/QML error message.

    Returns a structured dict with the error category, explanation, relevant
    type/API info, documentation links, and a suggested fix.
    """
    resolved_version = _resolve_version(version)

    # Step 1: categorize and extract entities
    category, entities = _categorize_error(error)

    # Step 2: extract type from code if available
    code_type = _extract_type_from_code(code) if code else None

    # Step 3: determine the target type
    target_type: str | None = entities.get("type") or component or code_type

    # Step 4: look up type in Quickshell index
    qs_type: dict | None = None
    if target_type:
        qs_type = _lookup_quickshell_type(target_type, resolved_version)

    # Step 5: if not in Quickshell, try Qt
    qt_type: dict | None = None
    if not qs_type and target_type:
        qt_type = _lookup_qt_type(target_type)

    # Step 6: fetch type page markdown for property/signal/method verification
    markdown: str | None = None
    if qs_type:
        markdown = _fetch_type_markdown(
            qs_type["type_name"], qs_type["namespace"], resolved_version
        )
    elif qt_type:
        markdown = _fetch_qt_type_markdown(qt_type["type_name"], qt_type.get("module"))

    # Step 7: determine confidence
    _NO_TYPE_CONFIDENCE = ("missing_import", "binding_error", "type_mismatch")
    confidence = "high"
    if category == "unknown":
        confidence = "low"
    elif (
        (not target_type or markdown is None)
        and target_type is not None
        and category not in _NO_TYPE_CONFIDENCE
    ):
        confidence = "medium"

    # Step 8: search for related docs
    related_docs = _search_related_docs(target_type, category, resolved_version)

    # Step 9: build and return diagnosis
    return _build_diagnosis(
        category=category,
        entities=entities,
        qs_type=qs_type,
        qt_type=qt_type,
        markdown=markdown,
        version=resolved_version,
        related_docs=related_docs,
        code=code,
        confidence=confidence,
    )
