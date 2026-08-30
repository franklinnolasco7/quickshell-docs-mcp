"""Static validation of Quickshell/QML source.

A conservative, lightweight structural analyzer: it tokenizes QML, walks the
object/brace structure, and checks the used types, properties, signals, and
imports against the Quickshell and Qt type indexes the other sources already
build. It is deliberately heuristic: it only reports what it is confident
about, and anything ambiguous degrades to a ``cannot_verify`` info diagnostic
instead of a false error. It complements qmlls; it does not replace it.

The analyzer is intentionally not a full QML compiler. JS blocks (function
bodies, handler blocks, object literals) are treated as opaque and skipped, so
properties are only validated when they sit in the direct body of a known QML
object.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from difflib import get_close_matches
from pathlib import Path

from ..extraction import _fetch_page_markdown, _fetch_qt_page_markdown
from ..versions import _latest_version, _resolve_version
from .docs import _build_index
from .qt_docs import _build_qt_index, _qt_docs_base, _resolve_qt_slug

# Member pages are resolved concurrently; the bound is generous enough for a
# large pasted config while keeping one hostile call from fanning out unbounded.
_MAX_MEMBER_FETCHES = 15

# How far up the base-class chain members are unioned before giving up. Two
# levels covers the common `Type : Base -> QtObject` shape without fetching the
# whole inheritance tree.
_MAX_BASE_DEPTH = 3

# QML object bodies only contain bindings and declarations, so `ident :` at the
# direct body level is a property binding. These tokens are declarations or
# control flow, never property names.
_DECLARATION_KEYWORDS = {
    "property",
    "readonly",
    "required",
    "default",
    "signal",
    "function",
    "import",
    "pragma",
    "as",
}

# JS statements that open a `{` block; never a QML object or property.
_JAVASCRIPT_KEYWORDS = {
    "if",
    "for",
    "while",
    "switch",
    "catch",
    "with",
    "do",
    "else",
    "return",
    "case",
    "typeof",
    "delete",
    "throw",
    "try",
    "finally",
    "new",
    "var",
    "let",
    "const",
    "class",
    "yield",
    "await",
    "in",
    "instanceof",
    "void",
}

# Properties every QObject/QQuickItem-derived type inherits from Qt itself, so
# they are valid on any object and must never be flagged. Kept conservative:
# anything genuinely type-specific is expected to come from the fetched docs.
_COMMON_QML_MEMBERS = {
    "id",
    "objectName",
    "parent",
    "data",
    "children",
    "resources",
    "x",
    "y",
    "z",
    "width",
    "height",
    "implicitWidth",
    "implicitHeight",
    "visible",
    "enabled",
    "opacity",
    "scale",
    "rotation",
    "transformOrigin",
    "clip",
    "focus",
    "activeFocus",
    "activeFocusOnTab",
    "state",
    "states",
    "transitions",
    "anchors",
    "transform",
    "childrenRect",
    "baselineOffset",
    "antialiasing",
    "smooth",
    "cache",
    "opaque",
    "layer",
    "hoverEnabled",
    "acceptHoverEvents",
    "acceptedButtons",
    "containsMouse",
    "keys",
    "contentItem",
    "background",
    "foreground",
    "padding",
    "leftPadding",
    "rightPadding",
    "topPadding",
    "bottomPadding",
    "Binding",
    "Component",
    "Connections",
    "Timer",
    "Behavior",
    "NumberAnimation",
    "SequentialAnimation",
    "ParallelAnimation",
    "PropertyAnimation",
    "AnimatedImage",
}

# Lowercase names that open a grouped-property block (`anchors { top: ... }`).
# Sub-properties of a group are validated against the group's own type, which
# is not resolved, so only the group name itself is checked.
_GROUP_PROPERTY_NAMES = {
    "anchors",
    "states",
    "transitions",
    "transform",
    "contentItem",
    "background",
    "foreground",
    "header",
    "footer",
    "padding",
    "layer",
    "dropShadow",
    "keys",
    "range",
}

# Valid QML built-in scalar/type names that never need an import and are not
# in the docs index; flagging them in a property declaration is a false positive.
_BUILTIN_QML_TYPES = {
    "var",
    "variant",
    "alias",
    "bool",
    "int",
    "uint",
    "double",
    "real",
    "qreal",
    "string",
    "url",
    "color",
    "list",
    "point",
    "rect",
    "size",
    "font",
    "date",
    "time",
    "enumeration",
    "object",
    "QtObject",
    "Item",
}

# Narrow, high-confidence assignment mismatches. QML coerces a surprising
# amount at runtime (numbers to strings, strings to colors), so anything the
# engine might accept is left alone. Keys are the documented property scalar
# types; values are literal kinds that cannot be assigned to them.
_MISMATCH_TABLE: dict[str, set[str]] = {
    "int": {"string", "bool"},
    "real": {"string", "bool"},
    "double": {"string", "bool"},
    "bool": {"number", "string"},
}

_LITERAL_KIND_OF_IDENT = {"true": "bool", "false": "bool"}

_PROPERTY_TYPE_HINT_RE = re.compile(r"\b(int|real|double|bool|string|color|var|url)\b")

_SECTION_NAME_TO_KIND = {
    "properties": "properties",
    "property": "properties",
    "signals": "signals",
    "signal": "signals",
    "methods": "methods",
    "method": "methods",
    "functions": "methods",
    "function": "methods",
    "slots": "methods",
}

# A member bullet is `- name  :` (property) or `- name (args)  :` / `- name ()`
# (function/signal). Description bullets like ``- `window` - ...`` start with a
# backtick and are deliberately not matched.
_MEMBER_BULLET_RE = re.compile(r"^-\s+(?P<name>[A-Za-z_]\w*)\s*(?::|\()")
_H3_MEMBER_RE = re.compile(r"^###\s+[`*]*\s*(?P<name>[A-Za-z_]\w*)")
_SECTION_HEADING_RE = re.compile(r"^##\s+(?P<title>[^\n]+)")


@dataclass
class _Token:
    kind: str  # ident | number | string | punct
    value: str
    line: int
    col: int


@dataclass
class _TypeRef:
    """A type mentioned in the source and its resolution against real docs."""

    raw: str  # exactly as written, e.g. "Hyprland.HyprlandMonitor"
    base_name: str  # last dotted component
    line: int
    col: int
    namespace: str | None = None  # Quickshell namespace
    module: str | None = None  # Qt module
    source_url: str | None = None
    local: bool = False  # matches the filename stem, so it is a sibling component
    members: _Members | None = None
    members_available: bool = False


@dataclass
class _PropertyBinding:
    object_type: str
    name: str
    line: int
    col: int
    literal_kind: str | None  # "number" | "string" | "bool" | None (non-literal)


@dataclass
class _SignalHandler:
    object_type: str
    signal_name: str
    line: int
    col: int


@dataclass
class _CustomDecl:
    kind: str  # "property" | "signal" | "function"
    name: str
    type_name: str | None  # declared property type, when the declaration has one
    line: int
    col: int


@dataclass
class _Import:
    module: str
    alias: str | None
    version: str | None
    line: int
    col: int


@dataclass
class _ParsedCode:
    imports: list[_Import] = field(default_factory=list)
    objects: list[_TypeRef] = field(default_factory=list)
    bindings: list[_PropertyBinding] = field(default_factory=list)
    handlers: list[_SignalHandler] = field(default_factory=list)
    declarations: list[_CustomDecl] = field(default_factory=list)
    malformed: str | None = None  # set when the source is structurally invalid


@dataclass
class _Members:
    properties: dict[str, str]  # name -> documented type
    signals: set[str]
    methods: set[str]
    base: str | None  # documented base class name, when the page says so
    source_url: str | None

    def is_empty(self) -> bool:
        return not (self.properties or self.signals or self.methods)


@dataclass
class _Diagnostic:
    severity: str  # error | warning | info
    code: str
    message: str
    line: int | None
    column: int | None
    type: str | None
    api: str | None
    alternatives: list[str]
    source: dict | None
    confidence: str  # high | medium | low
    could_not_verify: bool
    suggestion: str | None = None

    def to_dict(self) -> dict:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "line": self.line,
            "column": self.column,
            "type": self.type,
            "api": self.api,
            "alternatives": self.alternatives,
            "source": self.source,
            "confidence": self.confidence,
            "could_not_verify": self.could_not_verify,
            "suggestion": self.suggestion,
        }


def _tokenize(source: str) -> list[_Token]:
    """Split QML/JS source into tokens with 1-based positions.

    Strings and comments are consumed whole (their contents, including braces,
    are ignored), which keeps the brace-stack walk honest.
    """
    tokens: list[_Token] = []
    i = 0
    line = 1
    col = 1
    length = len(source)

    def advance(count: int) -> None:
        nonlocal i, line, col
        chunk = source[i : i + count]
        i += count
        newlines = chunk.count("\n")
        if newlines:
            line += newlines
            col = len(chunk.rsplit("\n", 1)[-1]) + 1
        else:
            col += count

    while i < length:
        char = source[i]
        if char in " \t\r\n":
            advance(1)
            continue
        start_line, start_col = line, col
        if char == "/" and i + 1 < length:
            if source[i + 1] == "/":
                end = source.find("\n", i)
                advance((end - i) if end != -1 else length - i)
                continue
            if source[i + 1] == "*":
                end = source.find("*/", i + 2)
                advance((end - i + 2) if end != -1 else length - i)
                continue
        if char in "\"'`":
            quote = char
            j = i + 1
            while j < length:
                if source[j] == "\\":
                    j += 2
                    continue
                if source[j] == quote:
                    break
                j += 1
            val = source[i : j + 1]
            advance(j + 1 - i)
            tokens.append(_Token("string", val, start_line, start_col))
            continue
        if char.isalpha() or char in "_$":
            j = i
            while j < length and (source[j].isalnum() or source[j] in "_$"):
                j += 1
            value = source[i:j]
            kind = "keyword" if value in _JAVASCRIPT_KEYWORDS else "ident"
            advance(j - i)
            tokens.append(_Token(kind, value, start_line, start_col))
            continue
        if char.isdigit() or (char == "." and i + 1 < length and source[i + 1].isdigit()):
            j = i
            while j < length and (source[j].isalnum() or source[j] in "._-"):
                j += 1
            val = source[i:j]
            advance(j - i)
            tokens.append(_Token("number", val, start_line, start_col))
            continue
        # A #-prefixed value is a color literal; opaque to validation.
        if char == "#":
            j = i + 1
            while j < length and (source[j].isalnum() or source[j] in "#_"):
                j += 1
            val = source[i:j]
            advance(j - i)
            tokens.append(_Token("string", val, start_line, start_col))
            continue
        if char in "{}()[]:;,.":
            advance(1)
            tokens.append(_Token("punct", char, start_line, start_col))
            continue
        if char == "=" and i + 1 < length and source[i + 1] == ">":
            advance(2)
            tokens.append(_Token("punct", "=>", start_line, start_col))
            continue
        advance(1)
        tokens.append(_Token("punct", char, start_line, start_col))
    return tokens


def _qualified_ident(tokens: list[_Token], index: int) -> tuple[str, int]:
    """Collect an identifier possibly qualified with dots: ``Quickshell.Panel``.

    Returns ``(qualified, next_index)`` where *next_index* is the first token
    after the qualified name.
    """
    name = tokens[index].value
    index += 1
    while (
        index + 1 < len(tokens)
        and tokens[index].kind == "punct"
        and tokens[index].value == "."
        and tokens[index + 1].kind == "ident"
    ):
        name += "." + tokens[index + 1].value
        index += 2
    return name, index


def _qualified_name_ending_at(tokens: list[_Token], index: int) -> tuple[str, int]:
    """Collect the dotted identifier ending at tokens[index] (walks backwards).

    Returns ``(qualified, start_index)``.
    """
    parts = [tokens[index].value]
    start = index
    j = index
    while (
        j - 2 >= 0
        and tokens[j - 1].kind == "punct"
        and tokens[j - 1].value == "."
        and tokens[j - 2].kind == "ident"
    ):
        parts.insert(0, tokens[j - 2].value)
        start = j - 2
        j -= 2
    return ".".join(parts), start


def _parse_import(tokens: list[_Token], index: int) -> tuple[_Import, int] | None:
    """Parse an import starting at its module-path token (after ``import``)."""
    if index >= len(tokens) or tokens[index].kind != "ident":
        return None
    module, end = _qualified_ident(tokens, index)
    line, col = tokens[index].line, tokens[index].col
    alias: str | None = None
    version: str | None = None
    i = end
    while i < len(tokens):
        tok = tokens[i]
        if tok.kind == "punct" and tok.value in (";", ","):
            i += 1
            break
        if tok.kind == "ident" and tok.value == "as" and i + 1 < len(tokens):
            alias = tokens[i + 1].value
            i += 2
            continue
        if tok.kind == "number":
            version = tok.value
            i += 1
            continue
        break
    return _Import(module=module, alias=alias, version=version, line=line, col=col), i


def _is_handler_name(name: str) -> bool:
    return name.startswith("on") and len(name) > 2 and name[2].isupper()


def _classify_open(prev: _Token | None) -> str:
    """Classify the ``{`` that follows *prev*: qml, group, or js."""
    if prev is None:
        return "js"
    if prev.kind == "punct":
        return "js"
    if prev.kind in ("keyword", "string", "number"):
        return "js"
    if prev.value == "function" or prev.value in _DECLARATION_KEYWORDS:
        return "js"
    if prev.value in _GROUP_PROPERTY_NAMES and not prev.value[0].isupper():
        return "group"
    # A bare identifier: uppercase starts a type instantiation, lowercase a
    # grouped property.
    return "qml" if prev.value[0].isupper() else "group"


def _literal_kind_of_value(tokens: list[_Token], index: int) -> str | None:
    """Classify a value as a literal kind only when it is a standalone literal.

    ``foo: 1 + 2`` is a JS binding expression, not a literal, so it must not be
    treated as a plain number.
    """
    if index >= len(tokens):
        return None
    tok = tokens[index]
    if tok.kind == "string":
        kind = "string"
    elif tok.kind == "number":
        kind = "number"
    elif tok.kind == "ident" and tok.value in _LITERAL_KIND_OF_IDENT:
        kind = _LITERAL_KIND_OF_IDENT[tok.value]
    else:
        return None
    if index + 1 < len(tokens):
        nxt = tokens[index + 1]
        if (nxt.kind == "ident" and nxt.line == tok.line) or (
            nxt.kind == "punct" and nxt.value not in (",", ";", ")", "]", "}")
        ):
            return None
    return kind


def _skip_array(tokens: list[_Token], index: int) -> int:
    """Return the index just past the closing ``]`` of the array opener at
    ``tokens[index]``.  Nested ``[]``, ``{}`` and ``()`` are matched so array
    contents are never interpreted as direct QML bindings.  Returns ``len`` if
    the array is unbalanced."""
    depth = 1
    i = index + 1
    n = len(tokens)
    while i < n:
        v = tokens[i].value
        if v in ("[", "{", "("):
            depth += 1
        elif v in ("]", "}", ")"):
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _consume_binding_value(tokens: list[_Token], index: int) -> int:
    """Scan past a binding's value expression, stopping before the first token
    that begins a new sibling binding or a ``{`` / ``}`` block (the main
    brace-stack walker handles those).  Parenthesised and bracketed expressions
    are consumed whole (``_skip_array``), and ternary ``?`` / ``:`` pairs are
    counted so a value colon - including one inside a nested ternary - is not
    misread as a binding colon.
    """
    depth = 0
    i = index
    n = len(tokens)
    ternary_depth = 0
    while i < n:
        tok = tokens[i]
        if depth == 0 and tok.value == "[":
            i = _skip_array(tokens, i)
            continue
        if depth == 0 and tok.value in ("{", "}"):
            break
        if tok.value == "(":
            depth += 1
            i += 1
            continue
        if tok.value == ")":
            depth = max(0, depth - 1)
            i += 1
            continue
        if depth == 0 and tok.kind == "punct" and tok.value == "?":
            ternary_depth += 1
            i += 1
            continue
        if depth == 0 and tok.kind == "punct" and tok.value == ":" and ternary_depth > 0:
            ternary_depth -= 1
            i += 1
            continue
        if (
            depth == 0
            and ternary_depth == 0
            and tok.kind == "ident"
            and i + 1 < n
            and tokens[i + 1].value == ":"
        ):
            break
        if depth == 0 and tok.value in (";", ","):
            i += 1
            break
        i += 1
    return i


def _parse_structure(tokens: list[_Token]) -> _ParsedCode:
    parsed = _ParsedCode()

    # Imports are statements at the top of the document; scan for the keyword
    # anywhere (the tokenizer classifies it as a plain ident).
    index = 0
    while index < len(tokens):
        if tokens[index].value == "import" and index + 1 < len(tokens):
            item = _parse_import(tokens, index + 1)
            if item is not None:
                imp, index = item
                parsed.imports.append(imp)
                continue
        index += 1

    stack: list[tuple[str, _TypeRef | None]] = [("root", None)]
    current_object: _TypeRef | None = None
    in_qml_direct = False

    def restore_parent() -> None:
        nonlocal current_object, in_qml_direct
        current_object = None
        for frame_kind, frame_obj in reversed(stack):
            if frame_kind == "qml" and frame_obj is not None:
                current_object = frame_obj
                break
        in_qml_direct = bool(stack) and stack[-1][0] == "qml"

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.kind == "punct" and tok.value == "{":
            frame_kind = _classify_open(tokens[i - 1] if i > 0 else None)
            if frame_kind == "qml":
                raw, start = _qualified_name_ending_at(tokens, i - 1)
                obj = _TypeRef(
                    raw=raw,
                    base_name=raw.split(".")[-1],
                    line=tokens[start].line,
                    col=tokens[start].col,
                )
                parsed.objects.append(obj)
                stack.append(("qml", obj))
                current_object = obj
                in_qml_direct = True
            elif frame_kind == "group":
                name_tok = tokens[i - 1]
                if current_object is not None:
                    parsed.bindings.append(
                        _PropertyBinding(
                            object_type=current_object.raw,
                            name=name_tok.value,
                            line=name_tok.line,
                            col=name_tok.col,
                            literal_kind=None,
                        )
                    )
                stack.append(("group", None))
                in_qml_direct = False
            else:
                stack.append(("js", None))
                in_qml_direct = False
        elif tok.kind == "punct" and tok.value == "}":
            if len(stack) <= 1:
                parsed.malformed = "Unbalanced closing brace '}'"
                return parsed
            stack.pop()
            restore_parent()
        elif in_qml_direct and current_object is not None and tok.kind == "ident":
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            if tok.value in _DECLARATION_KEYWORDS:
                if tok.value == "property" or (
                    tok.value in ("readonly", "required")
                    and nxt is not None
                    and nxt.value == "property"
                ):
                    decl_start = i if tok.value == "property" else i + 1
                    j = decl_start + 1
                    decl_type: str | None = None
                    if j < len(tokens) and tokens[j].kind == "ident":
                        if tokens[j].value == "alias":
                            # `property alias name: expr` has no type to validate
                            decl_type = None
                            j += 1
                        else:
                            decl_type = tokens[j].value
                            j += 1
                    if j < len(tokens) and tokens[j].kind == "ident":
                        parsed.declarations.append(
                            _CustomDecl(
                                kind="property",
                                name=tokens[j].value,
                                type_name=decl_type,
                                line=tokens[j].line,
                                col=tokens[j].col,
                            )
                        )
                        i = j + 1
                        continue
                elif tok.value == "signal":
                    j = i + 1
                    if j < len(tokens) and tokens[j].kind == "ident":
                        parsed.declarations.append(
                            _CustomDecl(
                                kind="signal",
                                name=tokens[j].value,
                                type_name=None,
                                line=tokens[j].line,
                                col=tokens[j].col,
                            )
                        )
                        i = j + 1
                        continue
                elif tok.value == "function":
                    j = i + 1
                    if j < len(tokens) and tokens[j].kind == "ident":
                        parsed.declarations.append(
                            _CustomDecl(
                                kind="function",
                                name=tokens[j].value,
                                type_name=None,
                                line=tokens[j].line,
                                col=tokens[j].col,
                            )
                        )
                        i = j + 1
                        continue
                i += 1
                continue
            if nxt is not None and nxt.kind == "punct" and nxt.value == ":":
                if i >= 1 and tokens[i - 1].kind == "punct" and tokens[i - 1].value == ".":
                    # Dotted key `a.b: value`: only the owner (first segment) is
                    # a property of this object; `b` belongs to a group type we
                    # do not resolve.
                    full, start = _qualified_name_ending_at(tokens, i)
                    owner = full.split(".")[0]
                    start_tok = tokens[start]
                    if _is_handler_name(owner) or owner in _DECLARATION_KEYWORDS:
                        # Attached handler like `Component.onCompleted`; skip.
                        i = _consume_binding_value(tokens, i + 2)
                        continue
                    parsed.bindings.append(
                        _PropertyBinding(
                            object_type=current_object.raw,
                            name=owner,
                            line=start_tok.line,
                            col=start_tok.col,
                            literal_kind=_literal_kind_of_value(tokens, i + 2),
                        )
                    )
                    i = _consume_binding_value(tokens, i + 2)
                    continue
                if _is_handler_name(tok.value):
                    parsed.handlers.append(
                        _SignalHandler(
                            object_type=current_object.raw,
                            signal_name=tok.value[2:],
                            line=tok.line,
                            col=tok.col,
                        )
                    )
                    i = _consume_binding_value(tokens, i + 2)
                    continue
                else:
                    parsed.bindings.append(
                        _PropertyBinding(
                            object_type=current_object.raw,
                            name=tok.value,
                            line=tok.line,
                            col=tok.col,
                            literal_kind=_literal_kind_of_value(tokens, i + 2),
                        )
                    )
                    i = _consume_binding_value(tokens, i + 2)
                    continue
        i += 1

    if len(stack) > 1:
        parsed.malformed = "Unbalanced braces: unclosed '{'"
    return parsed


def _strip_markdown_links(text: str) -> str:
    return re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)


def _next_line_scalar_type(lines: list[str], index: int) -> str | None:
    """Read the scalar type documented under a property bullet, if any."""
    j = index + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j >= len(lines):
        return None
    type_line = _strip_markdown_links(lines[j].strip())
    match = _PROPERTY_TYPE_HINT_RE.search(type_line)
    return match.group(1) if match else None


def _parse_members(markdown: str, source_url: str | None = None) -> _Members:
    """Extract properties/signals/methods and the base class from a type page.

    Handles both markup shapes seen in the wild: the current quickshell.org
    bullet list (``- name  :`` with the type on the following line) and the
    older ``### **name**`` headings.
    """
    properties: dict[str, str] = {}
    signals: set[str] = set()
    methods: set[str] = set()
    base: str | None = None
    section: str | None = None

    lines = markdown.splitlines()
    for i, raw in enumerate(lines):
        heading = _SECTION_HEADING_RE.match(raw)
        if heading:
            title = _strip_markdown_links(heading.group("title")).strip()
            first_word = title.split()[0].lower() if title.split() else ""
            kind = _SECTION_NAME_TO_KIND.get(first_word)
            if kind is not None:
                section = kind
                continue
            # Base class lives in the title heading: `## TypeName: [Base](url)`.
            if base is None and ":" in title:
                after = title.partition(":")[2].strip()
                if after:
                    base = after.split()[0]
            continue
        if section is None:
            continue
        bullet = _MEMBER_BULLET_RE.match(raw)
        if bullet:
            name = bullet.group("name")
            if section == "properties":
                properties[name] = _next_line_scalar_type(lines, i) or ""
            elif section == "signals":
                signals.add(name)
            else:
                methods.add(name)
            continue
        h3 = _H3_MEMBER_RE.match(raw)
        if h3:
            name = h3.group("name")
            if section == "properties":
                properties[name] = _next_line_scalar_type(lines, i) or ""
            elif section == "signals":
                signals.add(name)
            else:
                methods.add(name)

    return _Members(
        properties=properties,
        signals=signals,
        methods=methods,
        base=base,
        source_url=source_url,
    )


def _find_quickshell_namespace(type_name: str, version: str) -> str | None:
    index = _build_index(version)
    for ns, names in index["types_by_namespace"].items():
        if type_name in names:
            return ns
    return None


def _qt_module_for_type(type_name: str) -> str | None:
    index = _build_qt_index()
    for module, names in index["modules"].items():
        if type_name in names:
            return module
    return None


def _type_source_url(
    namespace: str | None, module: str | None, type_name: str, version: str
) -> str | None:
    if namespace:
        return f"https://quickshell.org/docs/{version}/types/{namespace}/{type_name}/"
    if module:
        try:
            slug, _ = _resolve_qt_slug(type_name, module, None)
        except ValueError:
            return None
        return f"{_qt_docs_base(None)}/qml-{slug}.html"
    return None


def _is_quickshell_url(url: str) -> bool:
    return url.startswith("https://quickshell.org/")


def _close_matches(needle: str, candidates: list[str], n: int = 5) -> list[str]:
    matches = get_close_matches(needle, candidates, n=n, cutoff=0.5)
    if not matches:
        low = needle.lower()
        matches = [c for c in candidates if low in c.lower() or c.lower() in low][:n]
    return matches


def _similar_type_names(needle: str, version: str) -> list[str]:
    index = _build_index(version)
    all_names = [name for names in index["types_by_namespace"].values() for name in names]
    qt_index = _build_qt_index()
    all_names += [name for names in qt_index["modules"].values() for name in names]
    return _close_matches(needle, all_names)


def _similar_member_names(needle: str, members: _Members) -> list[str]:
    candidates = list(members.properties) + list(members.signals) + list(members.methods)
    return _close_matches(needle, candidates, n=3)


def _resolve_type_refs(
    parsed: _ParsedCode, version: str, filename: str | None, diagnostics: list[_Diagnostic]
) -> list[_TypeRef]:
    """Resolve every referenced type to real docs, collecting type errors."""
    index = _build_index(version)
    known_namespaces = set(index["types_by_namespace"])
    imported = {imp.module for imp in parsed.imports}
    imported.update(imp.alias for imp in parsed.imports if imp.alias)
    stem = Path(filename).stem if filename else None
    latest: str | None = None
    latest_index: dict | None = None

    resolved: list[_TypeRef] = []
    seen: set[str] = set()
    for obj in parsed.objects:
        if obj.raw in seen:
            continue
        seen.add(obj.raw)
        base_name = obj.base_name

        # A sibling component file shadows any docs type; never flag it.
        if stem and base_name == stem:
            obj.local = True
            resolved.append(obj)
            continue

        namespace = _find_quickshell_namespace(base_name, version)
        if namespace is not None:
            obj.namespace = namespace
            obj.source_url = _type_source_url(namespace, None, base_name, version)
            resolved.append(obj)
            continue

        module = _qt_module_for_type(base_name)
        if module is not None:
            obj.module = module
            obj.source_url = _type_source_url(None, module, base_name, version)
            resolved.append(obj)
            continue

        # A name qualified by a known namespace is definitely wrong.
        qualifier = obj.raw.split(".")[0] if "." in obj.raw else None
        if qualifier in known_namespaces:
            diagnostics.append(
                _diag(
                    severity="error",
                    code="unknown_type",
                    message=f"Type '{base_name}' does not exist in namespace '{qualifier}'.",
                    line=obj.line,
                    column=obj.col,
                    type=obj.raw,
                    api=base_name,
                    alternatives=_similar_type_names(base_name, version),
                    source=None,
                    confidence="high",
                )
            )
            resolved.append(obj)
            continue

        # Not in the requested version's docs; check a newer published one.
        if latest is None:
            latest = _latest_version()
        if version != latest:
            if latest_index is None:
                latest_index = _build_index(latest)
            latest_names = {
                name for names in latest_index["types_by_namespace"].values() for name in names
            }
            if base_name in latest_names:
                ns_latest = next(
                    ns
                    for ns, names in latest_index["types_by_namespace"].items()
                    if base_name in names
                )
                obj.namespace = ns_latest
                obj.source_url = _type_source_url(ns_latest, None, base_name, latest)
                diagnostics.append(
                    _diag(
                        severity="error",
                        code="version_incompatible",
                        message=(
                            f"Type '{base_name}' is not available in {version}; "
                            f"it appears in {latest}."
                        ),
                        line=obj.line,
                        column=obj.col,
                        type=obj.raw,
                        api=base_name,
                        alternatives=[],
                        source=_source_dict(obj.source_url),
                        confidence="high",
                    )
                )
                resolved.append(obj)
                continue

        # A bare unknown name could be a local QML component we cannot see.
        diagnostics.append(
            _diag(
                severity="warning",
                code="unknown_type",
                message=(
                    f"Unknown type '{base_name}'. It is not in the {version} docs "
                    "index and may be a local component."
                ),
                line=obj.line,
                column=obj.col,
                type=obj.raw,
                api=base_name,
                alternatives=_similar_type_names(base_name, version),
                source=None,
                confidence="medium",
                could_not_verify=True,
            )
        )
        resolved.append(obj)

    # Import validation: every used Quickshell namespace should be imported.
    used_namespaces: set[str] = set()
    for obj in resolved:
        if obj.namespace and not obj.local:
            used_namespaces.add(obj.namespace)
    for ns in sorted(used_namespaces):
        if ns not in imported:
            diagnostics.append(
                _diag(
                    severity="warning",
                    code="missing_import",
                    message=f"Types from '{ns}' are used but '{ns}' is not imported.",
                    line=None,
                    column=None,
                    type=ns,
                    api=ns,
                    alternatives=[f"import {ns}"],
                    source=None,
                    confidence="medium",
                    suggestion=f"Add 'import {ns}' at the top of the file.",
                )
            )

    for imp in parsed.imports:
        if imp.module not in known_namespaces and not imp.module.startswith(
            ("QtQuick", "QtQml", "Quickshell", "QtTest", "QtMultimedia", "QtGraphicalEffects")
        ):
            diagnostics.append(
                _diag(
                    severity="info",
                    code="unknown_module",
                    message=(
                        f"Import '{imp.module}' is not recognized by the docs index; "
                        "it may be a third-party or local module."
                    ),
                    line=imp.line,
                    column=imp.col,
                    type=imp.module,
                    api=imp.module,
                    alternatives=[],
                    source=None,
                    confidence="low",
                    could_not_verify=True,
                )
            )
    return resolved


def _resolve_members_concurrently(refs: list[_TypeRef], version: str) -> None:
    """Fetch member pages for every resolvable type in parallel, capped."""
    fetchable = [ref for ref in refs if (ref.namespace or ref.module) and not ref.local][
        :_MAX_MEMBER_FETCHES
    ]
    if not fetchable:
        return

    markdown_by_url: dict[str, str] = {}

    def fetch_one(url: str) -> None:
        if url in markdown_by_url:
            return
        try:
            if _is_quickshell_url(url):
                markdown_by_url[url] = _fetch_page_markdown(url)
            else:
                markdown_by_url[url] = _fetch_qt_page_markdown(url)
        except Exception:  # noqa: BLE001 - a docs fetch failure must not crash validation
            markdown_by_url[url] = ""

    urls = [
        url
        for ref in fetchable
        if (url := _type_source_url(ref.namespace, ref.module, ref.base_name, version))
    ]
    with ThreadPoolExecutor(max_workers=_MAX_MEMBER_FETCHES) as pool:
        list(pool.map(fetch_one, urls))

    def members_for(ref: _TypeRef, depth: int = 0, seen: tuple[str, ...] = ()) -> _Members:
        url = _type_source_url(ref.namespace, ref.module, ref.base_name, version)
        if url is None or url in seen:
            return _Members(properties={}, signals=set(), methods=set(), base=None, source_url=url)
        markdown = markdown_by_url.get(url, "")
        if not markdown:
            return _Members(properties={}, signals=set(), methods=set(), base=None, source_url=url)
        members = _parse_members(markdown, url)
        if depth < _MAX_BASE_DEPTH and members.base:
            base_name = members.base.split(".")[-1]
            base_ref = _TypeRef(raw=members.base, base_name=base_name, line=0, col=0)
            base_ref.namespace = _find_quickshell_namespace(base_name, version)
            if base_ref.namespace is None:
                base_ref.module = _qt_module_for_type(base_name)
            if base_ref.namespace or base_ref.module:
                base_url = _type_source_url(
                    base_ref.namespace, base_ref.module, base_ref.base_name, version
                )
                if base_url is not None and base_url not in markdown_by_url:
                    fetch_one(base_url)
                base_members = members_for(base_ref, depth + 1, seen + (url,))
                return _Members(
                    properties={**base_members.properties, **members.properties},
                    signals=base_members.signals | members.signals,
                    methods=base_members.methods | members.methods,
                    base=members.base,
                    source_url=members.source_url,
                )
        return members

    for ref in fetchable:
        members = members_for(ref)
        ref.members = members
        ref.members_available = not members.is_empty()


def _validate_property_bindings(
    parsed: _ParsedCode,
    refs_by_name: dict[str, _TypeRef],
    diagnostics: list[_Diagnostic],
) -> None:
    noted_unavailable: set[str] = set()
    for binding in parsed.bindings:
        ref = refs_by_name.get(binding.object_type)
        if ref is None or ref.members is None:
            continue
        name = binding.name
        if name in _COMMON_QML_MEMBERS or name in ref.members.properties:
            _check_assignment_type(binding, ref, diagnostics)
            continue
        if not ref.members_available:
            if ref.raw in noted_unavailable:
                continue
            noted_unavailable.add(ref.raw)
            diagnostics.append(
                _diag(
                    severity="info",
                    code="cannot_verify",
                    message=(
                        f"Properties on '{ref.raw}' could not be verified: the "
                        "type's documentation is unavailable."
                    ),
                    line=binding.line,
                    column=binding.col,
                    type=ref.raw,
                    api=name,
                    alternatives=[],
                    source=_source_dict(ref.source_url),
                    confidence="low",
                    could_not_verify=True,
                )
            )
            continue
        diagnostics.append(
            _diag(
                severity="warning",
                code="unknown_property",
                message=f"Property '{name}' is not documented on '{ref.raw}'.",
                line=binding.line,
                column=binding.col,
                type=ref.raw,
                api=name,
                alternatives=_similar_member_names(name, ref.members),
                source=_source_dict(ref.source_url),
                confidence="medium",
            )
        )


def _check_assignment_type(
    binding: _PropertyBinding, ref: _TypeRef, diagnostics: list[_Diagnostic]
) -> None:
    if ref.members is None or binding.literal_kind is None:
        return
    prop_type = ref.members.properties.get(binding.name)
    if not prop_type:
        return
    forbidden = _MISMATCH_TABLE.get(prop_type)
    if forbidden and binding.literal_kind in forbidden:
        diagnostics.append(
            _diag(
                severity="warning",
                code="type_mismatch",
                message=(
                    f"Invalid assignment: property '{binding.name}' on '{ref.raw}' "
                    f"expects {prop_type}, got a {binding.literal_kind} literal."
                ),
                line=binding.line,
                column=binding.col,
                type=ref.raw,
                api=binding.name,
                alternatives=[],
                source=_source_dict(ref.source_url),
                confidence="medium",
            )
        )


def _validate_handlers(
    parsed: _ParsedCode,
    refs_by_name: dict[str, _TypeRef],
    diagnostics: list[_Diagnostic],
) -> None:
    for handler in parsed.handlers:
        ref = refs_by_name.get(handler.object_type)
        if ref is None or ref.members is None or not ref.members_available:
            continue
        signal_name = handler.signal_name
        signal_set = {s.lower() for s in ref.members.signals}
        if signal_name.lower() in signal_set:
            continue
        # QML auto-generates onXChanged change signals for every property; the
        # handler capitalizes the first letter of the property name.
        if signal_name.endswith("Changed"):
            property_name = signal_name[: -len("Changed")].lower()
            if property_name in {p.lower() for p in ref.members.properties} or property_name in {
                m.lower() for m in _COMMON_QML_MEMBERS
            }:
                continue
        diagnostics.append(
            _diag(
                severity="warning",
                code="unknown_signal",
                message=f"Signal '{signal_name}' is not documented on '{ref.raw}'.",
                line=handler.line,
                column=handler.col,
                type=ref.raw,
                api=signal_name,
                alternatives=_similar_member_names(signal_name, ref.members),
                source=_source_dict(ref.source_url),
                confidence="medium",
            )
        )


def _validate_declarations(
    parsed: _ParsedCode, version: str, diagnostics: list[_Diagnostic]
) -> None:
    index = _build_index(version)
    known = {name for names in index["types_by_namespace"].values() for name in names}
    qt_index = _build_qt_index()
    known.update(name for names in qt_index["modules"].values() for name in names)
    known.update(_BUILTIN_QML_TYPES)
    known.update(_COMMON_QML_MEMBERS)
    for decl in parsed.declarations:
        if decl.kind != "property" or not decl.type_name:
            continue
        if decl.type_name in known:
            continue
        diagnostics.append(
            _diag(
                severity="warning",
                code="unknown_type",
                message=f"Unknown property type '{decl.type_name}' on '{decl.name}'.",
                line=decl.line,
                column=decl.col,
                type=decl.type_name,
                api=decl.type_name,
                alternatives=_similar_type_names(decl.type_name, version),
                source=None,
                confidence="medium",
                could_not_verify=True,
            )
        )


def _diag(
    severity: str,
    code: str,
    message: str,
    line: int | None,
    column: int | None,
    type: str | None,
    api: str | None,
    alternatives: list[str],
    source: dict | None,
    confidence: str,
    could_not_verify: bool = False,
    suggestion: str | None = None,
) -> _Diagnostic:
    return _Diagnostic(
        severity=severity,
        code=code,
        message=message,
        line=line,
        column=column,
        type=type,
        api=api,
        alternatives=alternatives,
        source=source,
        confidence=confidence,
        could_not_verify=could_not_verify,
        suggestion=suggestion,
    )


def _source_dict(url: str | None) -> dict | None:
    if not url:
        return None
    text = "quickshell.org" if _is_quickshell_url(url) else "doc.qt.io"
    return {"text": text, "url": url}


_SEVERITY_ORDER = {"error": 0, "warning": 1, "info": 2}


def _validate(source: str, version: str = "latest", filename: str | None = None) -> dict:
    """Validate *source* as QML and return a structured diagnostic report."""
    resolved_version = _resolve_version(version)
    tokens = _tokenize(source)
    parsed = _parse_structure(tokens)
    diagnostics: list[_Diagnostic] = []
    refs: list[_TypeRef] = []

    if parsed.malformed:
        diagnostics.append(
            _diag(
                severity="error",
                code="malformed_qml",
                message=parsed.malformed,
                line=None,
                column=None,
                type=None,
                api=None,
                alternatives=[],
                source=None,
                confidence="high",
            )
        )
    elif not parsed.objects:
        diagnostics.append(
            _diag(
                severity="info",
                code="cannot_verify",
                message=(
                    "No QML object declarations found; the snippet could not be "
                    "meaningfully validated."
                ),
                line=None,
                column=None,
                type=None,
                api=None,
                alternatives=[],
                source=None,
                confidence="low",
                could_not_verify=True,
            )
        )
    else:
        refs = _resolve_type_refs(parsed, resolved_version, filename, diagnostics)
        refs_by_name = {ref.raw: ref for ref in refs}
        _resolve_members_concurrently(refs, resolved_version)
        _validate_property_bindings(parsed, refs_by_name, diagnostics)
        _validate_handlers(parsed, refs_by_name, diagnostics)
        _validate_declarations(parsed, resolved_version, diagnostics)
        for ref in refs:
            if ref.local:
                diagnostics.append(
                    _diag(
                        severity="info",
                        code="local_component",
                        message=(
                            f"Type '{ref.base_name}' matches the filename stem and is "
                            "treated as a local component; it is not validated against "
                            "the docs."
                        ),
                        line=ref.line,
                        column=ref.col,
                        type=ref.raw,
                        api=ref.base_name,
                        alternatives=[],
                        source=None,
                        confidence="medium",
                    )
                )

    diagnostics.sort(
        key=lambda d: (
            d.line if d.line is not None else 10**9,
            d.column if d.column is not None else 10**9,
            _SEVERITY_ORDER.get(d.severity, 3),
        )
    )

    summary = {
        "errors": sum(1 for d in diagnostics if d.severity == "error"),
        "warnings": sum(1 for d in diagnostics if d.severity == "warning"),
        "infos": sum(1 for d in diagnostics if d.severity == "info"),
        "types_checked": len(refs),
        "properties_checked": len(parsed.bindings),
        "signals_checked": len(parsed.handlers),
        "imports_checked": len(parsed.imports),
    }
    note = (
        "Static heuristic validation that complements qmlls; it cannot see local "
        "components or dynamic JavaScript, so the absence of a diagnostic is not "
        "proof of correctness."
    )
    return {
        "diagnostics": [d.to_dict() for d in diagnostics],
        "summary": summary,
        "version": resolved_version,
        "filename": filename,
        "note": note,
    }
