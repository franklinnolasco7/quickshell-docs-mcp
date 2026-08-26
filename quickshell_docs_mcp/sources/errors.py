# ruff: noqa: E501
"""Explain Quickshell/QML errors grounded in live doc indexes.

No API is invented: every existence check goes through _build_index or
_build_qt_index, and property checks fetch the real type page.
When uncertain the result is marked low confidence explicitly.
"""

from __future__ import annotations

import difflib
import re

from ..config import BASE
from ..extraction import _fetch_page_markdown, _fetch_qt_page_markdown
from ..versions import _resolve_version

try:
    from .docs import _build_index
except ImportError:
    _build_index = None  # type: ignore

try:
    from .qt_docs import _build_qt_index, _normalize_qt_module
except ImportError:
    _build_qt_index = None  # type: ignore
    _normalize_qt_module = None  # type: ignore

_QUOTED_RE = re.compile(r"[\"'`]([^\"'`]+)[\"'`]")
_CODE_TYPE_RE = re.compile(r"^\s*([A-Za-z_][\w\.]*)\s*\{", re.MULTILINE)


def _qt_module_uri(mod: str) -> str:
    """Convert internal module key (qtquick-controls) to QML URI (QtQuick.Controls)."""
    if mod == "value-types":
        return "QtQuick"
    # mapping for known segments
    segment_map = {
        "qtquick": "QtQuick",
        "controls": "Controls",
        "layouts": "Layouts",
        "effects": "Effects",
        "templates": "Templates",
        "shapes": "Shapes",
        "particles": "Particles",
        "test": "Test",
        "qml": "Qml",
        "quick": "Quick",
        "localstorage": "LocalStorage",
        "vectorimage": "VectorImage",
    }
    parts = mod.split("-")
    uri_parts: list[str] = []
    for part in parts:
        if part in segment_map:
            uri_parts.append(segment_map[part])
        elif part.startswith("qt"):
            uri_parts.append("Qt" + part[2:].capitalize())
        else:
            uri_parts.append(part.capitalize())
    return ".".join(uri_parts)


# Common QML/Qt base names — hint to check Qt index first.
_QT_HINT_NAMES = {
    "rectangle",
    "item",
    "text",
    "image",
    "mousearea",
    "rowlayout",
    "columnlayout",
    "gridlayout",
    "timer",
    "listview",
    "component",
    "color",
    "font",
    "vector3d",
    "vector2d",
    "rect",
    "point",
    "size",
}


def _extract_quoted(error: str) -> list[str]:
    return _QUOTED_RE.findall(error)


def _extract_type_from_code(code: str | None, component: str | None) -> str | None:
    if component and component.strip():
        return component.strip().split()[0].strip()
    if not code:
        return None
    match = _CODE_TYPE_RE.search(code)
    if match:
        # keep the raw type name (e.g. PanelWindow, Rectangle)
        return match.group(1).split(".")[-1].strip()
    return None


_UNQUOTED_TYPE_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s+is not a type\b", re.IGNORECASE)
_REFERENCE_ERROR_RE = re.compile(
    r"ReferenceError:\s*([A-Za-z_][A-Za-z0-9_]*)\s+is not defined", re.IGNORECASE
)


def _extract_unquoted_type(error: str) -> str | None:
    m = _UNQUOTED_TYPE_RE.search(error)
    if m:
        return m.group(1).strip()
    m = _REFERENCE_ERROR_RE.search(error)
    if m:
        return m.group(1).strip()
    return None


def _classify_error(error: str) -> tuple[str, list[str]]:
    lower = error.lower()
    quoted = _extract_quoted(error)

    if "non-existent property" in lower or "cannot assign to non-existent" in lower:
        return "non-existent property", quoted
    if "is not a" in lower and "property" in lower:
        return "non-existent property", quoted
    if "unknown type" in lower or "is not a type" in lower:
        return "unknown type", quoted
    if "referenceerror" in lower and "is not defined" in lower:
        return "unknown type", quoted
    if "module" in lower and "is not installed" in lower:
        return "missing import", quoted
    if "cannot import" in lower or "import" in lower and "not found" in lower:
        return "missing import", quoted
    if "is not a signal" in lower or "unknown signal" in lower:
        return "unknown signal", quoted
    if "is not a function" in lower or "unknown method" in lower:
        return "unknown method", quoted
    if "is not a function" in lower:
        return "unknown method", quoted
    if "binding loop" in lower:
        return "binding error", quoted
    if "cannot assign" in lower and " to " in lower:
        # already handled non-existent property above; remaining is type mismatch
        return "type mismatch", quoted
    if "type mismatch" in lower or "invalid assignment" in lower:
        return "type mismatch", quoted
    if "component" in lower and "not found" in lower:
        return "component not found", quoted
    if "is not a component" in lower:
        return "component not found", quoted
    if "unavailable" in lower and "property" in lower:
        return "unavailable property", quoted
    return "unknown", quoted


def _all_quickshell_types(version: str) -> dict[str, list[str]] | None:
    if _build_index is None:
        return {}
    try:
        index = _build_index(version)
    except Exception:
        return None
    return index.get("types_by_namespace", {})


def _find_quickshell_type(name: str, version: str) -> tuple[bool | None, str | None, list[str]]:
    """Return (found, namespace, close_matches). None means index unavailable."""
    types_by_ns = _all_quickshell_types(version)
    if types_by_ns is None:
        return None, None, []
    for ns, names in types_by_ns.items():
        for n in names:
            if n == name:
                return True, ns, []
    lower = name.lower()
    # not found — collect close matches
    all_names: list[str] = []
    ns_for_name: dict[str, str] = {}
    for ns, names in types_by_ns.items():
        for n in names:
            all_names.append(n)
            ns_for_name.setdefault(n.lower(), ns)
    # substring matches first, longest first for specificity
    substr = sorted(
        [n for n in all_names if lower in n.lower() or n.lower() in lower],
        key=len,
        reverse=True,
    )
    close = difflib.get_close_matches(name, all_names, n=5, cutoff=0.6)
    # merge, keep order, dedup
    merged: list[str] = []
    for cand in substr + close:
        if cand not in merged:
            merged.append(cand)
        if len(merged) >= 5:
            break
    return False, None, merged[:5]


def _find_qt_type(name: str) -> tuple[bool | None, str | None, list[str]]:
    if _build_qt_index is None:
        return False, None, []
    try:
        index = _build_qt_index()
    except Exception:
        return None, None, []
    modules = index.get("modules", {})
    for mod, names in modules.items():
        for n in names:
            if n == name:
                return True, mod, []
    lower = name.lower()
    all_names: list[str] = [n for names in modules.values() for n in names]
    substr = [n for n in all_names if lower in n.lower()]
    close = difflib.get_close_matches(name, all_names, n=5, cutoff=0.6)
    merged: list[str] = []
    for cand in substr + close:
        if cand not in merged:
            merged.append(cand)
        if len(merged) >= 5:
            break
    return False, None, merged[:5]


def _find_namespace(name: str, version: str) -> tuple[bool | None, list[str]]:
    types_by_ns = _all_quickshell_types(version)
    if types_by_ns is None:
        return None, []
    if name in types_by_ns:
        return True, []
    lower = name.lower()
    # exact case-insensitive
    for ns in types_by_ns:
        if ns.lower() == lower:
            return True, []
    substr = sorted(
        [ns for ns in types_by_ns if lower in ns.lower() or ns.lower() in lower],
        key=len,
        reverse=True,
    )
    close = difflib.get_close_matches(name, list(types_by_ns.keys()), n=5, cutoff=0.6)
    merged: list[str] = []
    for cand in substr + close:
        if cand not in merged:
            merged.append(cand)
        if len(merged) >= 5:
            break
    return False, merged[:5]


def _fetch_type_markdown(namespace: str, type_name: str, version: str) -> str | None:
    url = f"{BASE}/docs/{version}/types/{namespace}/{type_name}/"
    try:
        return _fetch_page_markdown(url)
    except Exception:
        return None


def _suggest_property_alternative(prop: str, markdown: str) -> str | None:
    tokens = set(re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", markdown))
    # filter noise
    filtered = [
        t
        for t in tokens
        if len(t) > 2 and t.lower() not in {"the", "and", "for", "this", "that", "with", "from"}
    ]
    close = difflib.get_close_matches(prop, filtered, n=3, cutoff=0.65)
    # prefer case-insensitive close that is not identical
    for cand in close:
        if cand.lower() != prop.lower():
            return cand
    return None


def _try_impl_examples(query: str) -> list[dict]:
    """Best-effort impl search; never fails the explain."""
    try:
        from .implementations import _search_implementations

        results: list[dict] = []
        for src in ("caelestia", "noctalia"):
            try:
                hits = _search_implementations(src, query, limit=2)
                for h in hits:
                    results.append({"source": src, **h})
            except Exception:
                continue
        return results[:3]
    except Exception:
        return []


def _explain_error(
    error: str,
    code: str | None = None,
    version: str = "latest",
    filename: str | None = None,
    line_number: int | None = None,
    component: str | None = None,
) -> dict:
    if not error or not error.strip():
        return {
            "error_type": "unknown",
            "meaning": "Empty error message provided.",
            "likely_cause": "No error to diagnose.",
            "relevant_api": None,
            "exists": None,
            "alternative": None,
            "documentation": [],
            "fix": "Provide the QML error message.",
            "version_notes": None,
            "confidence": "low",
            "code_context": None,
        }

    # resolve version
    resolved_version: str
    version_notes: str | None = None
    try:
        resolved_version = _resolve_version(version)
        if version and version.lower() != "latest":
            version_notes = f"Checked against {resolved_version} (requested {version})."
        else:
            version_notes = f"Checked against {resolved_version} (latest)."
    except Exception as exc:
        # fallback to latest discovery if possible
        try:
            from ..versions import list_versions

            vs = list_versions()
            resolved_version = vs[0] if vs else "v0.3.1"
        except Exception:
            resolved_version = "v0.3.1"
        version_notes = f"Version resolution failed for '{version}': {exc}. Used {resolved_version} as fallback."

    category, quoted = _classify_error(error)
    code_type = _extract_type_from_code(code, component)
    target = quoted[0] if quoted else None
    if target is None and category == "unknown type":
        unquoted = _extract_unquoted_type(error)
        if unquoted:
            target = unquoted

    # defaults
    meaning = ""
    likely_cause = ""
    relevant_api: str | None = None
    exists: bool | None = None
    alternative: str | None = None
    docs: list[dict] = []
    fix = ""
    confidence: str = "high"

    if category == "non-existent property":
        prop = target or ""
        relevant_api = f"{code_type}.{prop}" if code_type and prop else prop or code_type
        meaning = f"QML tried to assign to property '{prop}' which the engine does not recognize on that element."
        if not prop:
            meaning = (
                "QML reports a non-existent property but the property name could not be parsed."
            )
            likely_cause = "The snippet assigns an unknown key."
            fix = "Check the property name for typos and verify it on the type's reference page."
            confidence = "medium"
        else:
            # try to verify against the type from code
            if code_type:
                # check quickshell first
                qs_found, qs_ns, qs_suggest = _find_quickshell_type(code_type, resolved_version)
                qt_found, qt_mod, qt_suggest = _find_qt_type(code_type)
                # decide namespace
                if qs_found and qs_ns:
                    md = _fetch_type_markdown(qs_ns, code_type, resolved_version)
                    if md is not None:
                        has = re.search(rf"\b{re.escape(prop)}\b", md, re.IGNORECASE) is not None
                        exists = has
                        if has:
                            meaning = f"Property '{prop}' was found in {qs_ns}.{code_type} docs; it may be unavailable in this context or version."
                            likely_cause = "Property exists but is not available on this element instance, or requires a different parent/condition."
                            fix = f"Check {qs_ns}.{code_type} docs for when '{prop}' is available, or move the assignment."
                            docs.append(
                                {
                                    "url": f"{BASE}/docs/{resolved_version}/types/{qs_ns}/{code_type}/",
                                    "snippet": "type reference",
                                }
                            )
                        else:
                            exists = False
                            likely_cause = f"'{prop}' is not a property of {qs_ns}.{code_type}."
                            alt = _suggest_property_alternative(prop, md) if md else None
                            alternative = alt
                            fix = f"Remove or rename '{prop}' on {code_type}."
                            if alt:
                                fix += f" Did you mean '{alt}'?"
                            docs.append(
                                {
                                    "url": f"{BASE}/docs/{resolved_version}/types/{qs_ns}/{code_type}/",
                                    "snippet": "type reference",
                                }
                            )
                            # subtle impl hint
                            impls = _try_impl_examples(f"{code_type} {prop}")
                            if impls:
                                docs.extend(
                                    [
                                        {
                                            "url": h.get("path", ""),
                                            "snippet": f"implementation example ({h.get('source')})",
                                        }
                                        for h in impls[:1]
                                    ]
                                )
                    else:
                        exists = False
                        likely_cause = (
                            f"'{prop}' on {code_type}: could not fetch type page to verify."
                        )
                        confidence = "medium"
                elif qt_found and qt_mod:
                    relevant_api = f"{_qt_module_uri(qt_mod)}.{code_type}.{prop}"
                    # verify via Qt type page when possible
                    qt_md: str | None = None
                    try:
                        qt_url = f"https://doc.qt.io/qt-6/qml-{qt_mod}-{code_type.lower()}.html"
                        qt_md = _fetch_qt_page_markdown(qt_url)
                    except Exception:
                        qt_md = None
                    if qt_md is not None:
                        has = re.search(rf"\b{re.escape(prop)}\b", qt_md, re.IGNORECASE) is not None
                        exists = has
                        if has:
                            meaning = f"Property '{prop}' found on Qt type {_qt_module_uri(qt_mod)}.{code_type}."
                            likely_cause = (
                                "Property exists but may be unavailable in this context or version."
                            )
                            fix = f"Check {_qt_module_uri(qt_mod)}.{code_type} docs for when '{prop}' is available."
                            confidence = "high"
                        else:
                            likely_cause = f"'{prop}' not found on Qt type {_qt_module_uri(qt_mod)}.{code_type}."
                            alt = _suggest_property_alternative(prop, qt_md)
                            alternative = alt
                            fix = f"Remove or rename '{prop}' on {code_type}."
                            if alt:
                                fix += f" Did you mean '{alt}'?"
                            confidence = "high"
                    else:
                        exists = None
                        likely_cause = f"Could not verify property '{prop}' on Qt type {code_type}; docs unavailable."
                        confidence = "low"
                        fix = (
                            f"Check Qt docs for {code_type} properties; '{prop}' may be misspelled."
                        )
                    docs.append(
                        {
                            "url": f"https://doc.qt.io/qt-6/qml-{qt_mod}-{code_type.lower()}.html",
                            "snippet": "Qt type reference",
                        }
                    )
                else:
                    exists = None
                    likely_cause = f"Type '{code_type}' not found in Quickshell or Qt indexes, so property '{prop}' cannot be verified."
                    confidence = "low"
                    # suggest type
                    _, _, sugg = _find_quickshell_type(code_type, resolved_version)
                    if sugg:
                        alternative = sugg[0]
                        docs.append(
                            {
                                "url": f"{BASE}/docs/{resolved_version}/types/",
                                "snippet": f"did you mean type '{sugg[0]}'?",
                            }
                        )
                    fix = f"Verify type '{code_type}' exists and check its properties."
            else:
                likely_cause = f"Property '{prop}' does not exist on the inferred element. No surrounding type found in code/component."
                fix = f"Check spelling of '{prop}' or specify component via the 'component' parameter."
                confidence = "medium"
                # try to find types that mention this property
                try:
                    from .docs import _search_type_content

                    hits = _search_type_content(prop, resolved_version, limit=3)
                    for h in hits[:2]:
                        docs.append({"url": h["url"], "snippet": h["snippet"]})
                except Exception:
                    pass

    elif category == "unknown type":
        tname = target or (code_type or "")
        relevant_api = tname
        meaning = f"QML engine does not know type '{tname}'."
        qs_found, qs_ns, qs_suggest = (
            _find_quickshell_type(tname, resolved_version) if tname else (False, None, [])
        )
        qt_found, qt_mod, qt_suggest = _find_qt_type(tname) if tname else (False, None, [])
        if qs_found and qs_ns:
            exists = True
            likely_cause = f"Type '{tname}' exists as {qs_ns}.{tname} but may be missing an import."
            fix = f"Add 'import {qs_ns}' or use fully qualified {qs_ns}.{tname}."
            docs.append(
                {
                    "url": f"{BASE}/docs/{resolved_version}/types/{qs_ns}/{tname}/",
                    "snippet": "type exists",
                }
            )
        elif qt_found and qt_mod:
            exists = True
            likely_cause = (
                f"'{tname}' is a Qt type ({_qt_module_uri(qt_mod)}.{tname}); missing Qt import."
            )
            fix = f"Add 'import {_qt_module_uri(qt_mod)}' and check casing: '{tname}'."
            docs.append(
                {
                    "url": f"https://doc.qt.io/qt-6/qml-{qt_mod}-{tname.lower()}.html",
                    "snippet": "Qt type",
                }
            )
        elif qs_found is None and qt_found is None:
            exists = None
            likely_cause = f"Could not verify type '{tname}'; indexes unavailable."
            fix = "Check network and version, then verify spelling."
            confidence = "low"
        else:
            exists = False
            likely_cause = f"Type '{tname}' not found in Quickshell or Qt indexes."
            sugg = qs_suggest or qt_suggest
            if sugg:
                alternative = sugg[0]
                likely_cause += f" Did you mean '{sugg[0]}'?"
                fix = f"Replace '{tname}' with '{sugg[0]}' or check imports."
                # grounded suggestion doc
                # find namespace for suggested name if quickshell
                found_alt, alt_ns, _ = _find_quickshell_type(sugg[0], resolved_version)
                if found_alt and alt_ns:
                    docs.append(
                        {
                            "url": f"{BASE}/docs/{resolved_version}/types/{alt_ns}/{sugg[0]}/",
                            "snippet": f"did you mean '{sugg[0]}'?",
                        }
                    )
                else:
                    # try Qt
                    _, qt_mod2, _ = _find_qt_type(sugg[0])
                    if qt_mod2:
                        docs.append(
                            {
                                "url": f"https://doc.qt.io/qt-6/qml-{qt_mod2}-{sugg[0].lower()}.html",
                                "snippet": f"did you mean '{sugg[0]}'?",
                            }
                        )
            else:
                fix = f"Verify spelling of '{tname}' and add the required import."
            confidence = "high" if sugg else "medium"

    elif category == "missing import":
        mod = target or ""
        # target may be like Quickshell.Hyprland
        relevant_api = mod
        meaning = f"Import '{mod}' could not be resolved."
        exists = None
        if mod:
            # check if namespace exists
            found_ns, sugg = _find_namespace(mod, resolved_version)
            qt_found_imp: bool | None = False
            qt_unavailable = False
            if not found_ns:
                # also check qt modules
                try:
                    qt_index = _build_qt_index() if _build_qt_index is not None else None
                    if qt_index is None:
                        qt_unavailable = True
                    elif qt_index:
                        mods = qt_index.get("modules", {})
                        norm = (
                            _normalize_qt_module(mod)
                            if _normalize_qt_module is not None
                            else mod.lower()
                        )
                        qt_found_imp = (
                            any(_normalize_qt_module(m) == norm for m in mods)
                            if _normalize_qt_module is not None
                            else False
                        )
                except Exception:
                    qt_unavailable = True
                    qt_found_imp = None
            if found_ns:
                exists = True
                likely_cause = f"Namespace '{mod}' exists but import statement may be wrong."
                fix = f"Use 'import {mod}' with correct casing."
                docs.append(
                    {"url": f"{BASE}/docs/{resolved_version}/types/{mod}/", "snippet": "namespace"}
                )
            elif qt_found_imp:
                exists = True
                likely_cause = f"'{mod}' is a Qt module, not Quickshell."
                # canonical URI via normalized form
                try:
                    norm_uri = (
                        _normalize_qt_module(mod)
                        if _normalize_qt_module is not None
                        else mod.lower()
                    )
                    uri = _qt_module_uri(norm_uri)
                except Exception:
                    uri = "QtQuick"
                fix = f"Use Qt import, e.g. 'import {uri}'."
            elif found_ns is None or qt_unavailable:
                exists = None
                likely_cause = f"Could not verify import '{mod}'; indexes unavailable."
                fix = "Check network and version."
                confidence = "low"
            else:
                exists = False
                likely_cause = f"Module '{mod}' not found in Quickshell or Qt indexes."
                if sugg:
                    alternative = sugg[0]
                    fix = f"Did you mean 'import {sugg[0]}'?"
                else:
                    fix = "Check module name and Quickshell version."
                confidence = "medium"
        else:
            meaning = "Import failed but module name could not be parsed."
            likely_cause = "Missing or malformed import statement."
            fix = "Check 'import Quickshell' or 'import QtQuick' statements."
            confidence = "low"

    elif category in ("unknown signal", "unknown method"):
        name = target or ""
        relevant_api = f"{code_type}.{name}" if code_type and name else name or code_type
        kind = "signal" if "signal" in category else "method"
        meaning = f"QML reports unknown {kind} '{name}'."
        if code_type and name:
            qs_found, qs_ns, _ = _find_quickshell_type(code_type, resolved_version)
            if qs_found and qs_ns:
                md = _fetch_type_markdown(qs_ns, code_type, resolved_version)
                if md is not None:
                    has = re.search(rf"\b{re.escape(name)}\b", md, re.IGNORECASE) is not None
                    exists = has
                    if has:
                        likely_cause = f"'{name}' exists on {qs_ns}.{code_type} but may need correct signal syntax (e.g. onChanged)."
                        fix = f"Check {qs_ns}.{code_type} docs for {kind} signature."
                    else:
                        exists = False
                        likely_cause = f"'{name}' not found on {qs_ns}.{code_type}."
                        alt = _suggest_property_alternative(name, md)
                        alternative = alt
                        fix = (
                            f"Check spelling; did you mean '{alt}'?"
                            if alt
                            else f"Verify {kind} name on {code_type}."
                        )
                    docs.append(
                        {
                            "url": f"{BASE}/docs/{resolved_version}/types/{qs_ns}/{code_type}/",
                            "snippet": "type reference",
                        }
                    )
                else:
                    confidence = "medium"
                    likely_cause = f"Could not fetch {code_type} page to verify {kind}."
                    fix = f"Check docs for {code_type}."
            else:
                likely_cause = f"Type '{code_type}' not found, cannot verify {kind} '{name}'."
                confidence = "low"
                fix = f"Verify type '{code_type}' and {kind} name."
        else:
            likely_cause = f"{kind.capitalize()} '{name}' not recognized; no type context."
            fix = "Specify component or include code with the enclosing type."
            confidence = "medium"

    elif category == "type mismatch":
        meaning = "Value of one type was assigned to a property expecting another type."
        likely_cause = error.strip()
        relevant_api = code_type
        # try to extract two types from quoted
        if len(quoted) >= 2:
            likely_cause = f"Cannot assign '{quoted[0]}' to '{quoted[1]}'."
            fix = f"Convert '{quoted[0]}' to expected type '{quoted[1]}' or use a compatible property."
        else:
            # try regex for Cannot assign X to Y
            m = re.search(r"Cannot assign\s+(.+?)\s+to\s+(.+)", error, re.IGNORECASE)
            if m:
                likely_cause = f"Cannot assign {m.group(1).strip()} to {m.group(2).strip()}."
                fix = "Coerce the value or choose a property with matching type."
            else:
                fix = "Check property type in docs and match the assigned value."
        exists = None
        confidence = "medium"
        if code_type:
            qs_found, qs_ns, _ = _find_quickshell_type(code_type, resolved_version)
            if qs_found and qs_ns:
                docs.append(
                    {
                        "url": f"{BASE}/docs/{resolved_version}/types/{qs_ns}/{code_type}/",
                        "snippet": "type reference",
                    }
                )

    elif category == "binding error":
        meaning = "QML binding loop or invalid binding detected."
        likely_cause = "Circular or recursive property binding."
        relevant_api = code_type
        fix = "Break the cycle with an explicit property or avoid binding a property to itself."
        exists = None
        confidence = "medium"
        # guide search
        try:
            from .docs import _search_guide_content

            hits = _search_guide_content("binding", resolved_version, limit=2)
            for h in hits:
                docs.append({"url": h["url"], "snippet": h["snippet"]})
        except Exception:
            pass

    elif category == "component not found":
        comp = target or code_type or ""
        relevant_api = comp
        meaning = f"Component '{comp}' could not be resolved."
        qs_found, qs_ns, qs_suggest = (
            _find_quickshell_type(comp, resolved_version) if comp else (False, None, [])
        )
        qt_found, _, qt_suggest = _find_qt_type(comp) if comp else (False, None, [])
        if qs_found or qt_found:
            exists = True
            likely_cause = f"Component '{comp}' exists but may be missing import or file path."
            fix = f"Add import or check file path for '{comp}'."
            if qs_found and qs_ns:
                docs.append(
                    {
                        "url": f"{BASE}/docs/{resolved_version}/types/{qs_ns}/{comp}/",
                        "snippet": "component",
                    }
                )
        else:
            exists = False
            sugg = qs_suggest or qt_suggest
            if sugg:
                alternative = sugg[0]
                likely_cause = f"Component '{comp}' not found. Did you mean '{sugg[0]}'?"
                fix = f"Replace '{comp}' with '{sugg[0]}'."
            else:
                likely_cause = f"Component '{comp}' not found in indexes."
                fix = "Verify component name and import/file location."
                confidence = "medium"

    elif category == "unavailable property":
        prop = target or ""
        relevant_api = f"{code_type}.{prop}" if code_type and prop else prop
        meaning = f"Property '{prop}' exists but is not available in this context."
        likely_cause = "Property may be version-gated or requires specific parent/type."
        fix = f"Check {code_type or 'the type'} docs for availability of '{prop}'."
        exists = None
        confidence = "medium"
        if code_type:
            qs_found, qs_ns, _ = _find_quickshell_type(code_type, resolved_version)
            if qs_found and qs_ns:
                docs.append(
                    {
                        "url": f"{BASE}/docs/{resolved_version}/types/{qs_ns}/{code_type}/",
                        "snippet": "type reference",
                    }
                )

    else:  # unknown
        meaning = "Error could not be classified into a known QML category."
        likely_cause = "Unrecognized error format; may be tooling or JS error inside QML."
        relevant_api = target or code_type
        exists = None
        confidence = "low"
        fix = "Check the full message and surrounding QML; verify type and property names via quickshell_search."
        # still try to surface docs for any quoted token
        if target:
            qs_found, qs_ns, qs_suggest = _find_quickshell_type(target, resolved_version)
            if qs_found and qs_ns:
                docs.append(
                    {
                        "url": f"{BASE}/docs/{resolved_version}/types/{qs_ns}/{target}/",
                        "snippet": "possible type",
                    }
                )
                exists = True
            elif qs_suggest:
                alternative = qs_suggest[0]

    # generic version note already set
    # if error mentions version-like string, add note

    # truncate docs to keep concise (max 3)
    docs = docs[:3]

    result: dict = {
        "error_type": category,
        "meaning": meaning,
        "likely_cause": likely_cause,
        "relevant_api": relevant_api,
        "exists": exists,
        "alternative": alternative,
        "documentation": docs,
        "fix": fix,
        "version_notes": version_notes,
        "confidence": confidence,
    }
    # optional context echo
    if filename or line_number is not None or code_type:
        result["code_context"] = {
            "filename": filename,
            "line_number": line_number,
            "component": code_type,
            "snippet": (code[:400] + "...") if code and len(code) > 400 else code,
        }
    return result
