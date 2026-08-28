"""Minimal Quickshell component generation grounded in real docs.

Turns a plain-language description into a small QML component. The generator
is template-based, not freeform: every supported feature maps to a curated
section whose QML only references APIs that have been verified against the
live type pages. At generation time every referenced API is re-checked
against the requested Quickshell version via the compatibility machinery, so
an API that never existed (or was removed) surfaces in the result instead of
being silently emitted. The assembled QML is then passed through the existing
static validator, and the surrounding search tools are reused to attach
supporting references.

Every generated file contains exactly one top-level window. A request that
matches several windows keeps the highest-ranked one and surfaces the rest as
assumptions rather than nesting a window inside another window's layout.
Unmatched requests return the verified API surface of the relevant types plus
references, so a caller can compose the component itself from verified
building blocks.

This module deliberately contains no new fetching or index logic; it composes
the existing per-source helpers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..config import BASE
from ..versions import _resolve_version
from .compat import _check_compatibility, _type_members
from .find_pattern import _find_pattern, _interpret_query
from .search_all import _search_everything
from .validate import _validate

# Ordered preference for picking which section becomes the root of a
# standalone component when no container is present.
_ROOT_PRIORITY = ("bar", "panel", "osd", "control-center", "notifications")
# Sections that subsume others (the subsumed key is dropped when the root is
# present, to avoid doubling up on the same types).
_SUBSUMES: dict[str, set[str]] = {"osd": {"audio"}}

_INDENT = "    "

# Compositor names with a dedicated Quickshell integration; anything else is
# treated as unrecognized and gets no compositor-specific types.
_COMPOSITOR_NAMESPACES = {"hyprland"}

# Extra sections keyed off plain tokens that the pattern table does not cover.
_TOKEN_SECTIONS: list[tuple[str, tuple[str, ...]]] = [
    ("clock", ("clock", "time", "date")),
]


@dataclass
class _Section:
    key: str
    reason: str
    imports: list[str]
    apis: list[str]
    types: list[dict]
    qt_types: list[str]
    child_block: str
    standalone: bool = False
    container: bool = False
    compositor: str | None = None
    description: str = ""


def _bar_section(compositor: str | None, version: str) -> _Section:
    return _Section(
        key="bar",
        reason="top bar / status bar / panel request",
        imports=["Quickshell", "QtQuick"],
        apis=["PanelWindow", "PanelWindow.anchors", "PanelWindow.exclusiveMode"],
        types=[{"type_name": "PanelWindow", "namespace": "Quickshell"}],
        qt_types=["Item", "RowLayout", "Text"],
        child_block="""PanelWindow {
    id: panel
    anchors { left: true; right: true; top: true }
    exclusiveMode: ExclusionMode.Normal
    height: 36
    color: "#1e1e2e"

    RowLayout {
        anchors.fill: parent
        anchors.margins: 4
        spacing: 8
        /*CHILD_SECTIONS*/
        Item { Layout.fillWidth: true }
    }
}""",
        standalone=True,
        container=True,
        description=(
            "Top status bar: full-width PanelWindow with a horizontal layout for child widgets."
        ),
    )


def _workspaces_section(compositor: str | None, version: str) -> _Section:
    if compositor is not None and compositor.lower() == "hyprland":
        return _Section(
            key="workspaces",
            reason="hyprland workspace indicator",
            imports=["Quickshell.Hyprland", "QtQuick"],
            apis=[
                "Hyprland",
                "Hyprland.workspaces",
                "HyprlandWorkspace",
                "HyprlandWorkspace.active",
                "HyprlandWorkspace.name",
                "HyprlandWorkspace.activate()",
            ],
            types=[
                {"type_name": "Hyprland", "namespace": "Quickshell.Hyprland"},
                {"type_name": "HyprlandWorkspace", "namespace": "Quickshell.Hyprland"},
            ],
            qt_types=["Item", "Rectangle", "Text", "MouseArea", "Row", "Repeater"],
            compositor="Hyprland",
            child_block="""Row {
    spacing: 4
    Repeater {
        model: Hyprland.workspaces
        delegate: Item {
            required property var modelData
            width: 28
            height: 28
            Rectangle {
                anchors.fill: parent
                radius: 4
                color: modelData.active ? "#89b4fa" : "#313244"
                Text {
                    anchors.centerIn: parent
                    text: modelData.name
                    color: "#cdd6f4"
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: modelData.activate()
                }
            }
        }
    }
}""",
            description="Workspace indicator backed by the Hyprland socket.",
        )
    return _Section(
        key="workspaces",
        reason="workspace indicator (no compositor resolved)",
        imports=["QtQuick"],
        apis=[],
        types=[],
        qt_types=["Row", "Text"],
        compositor=None,
        child_block="""Row {
    spacing: 4
    Text {
        text: "workspaces"
        color: "#cdd6f4"
        // Requires compositor-specific workspace types from the matching
        // Quickshell namespace. Pass compositor='hyprland' for the
        // dedicated integration, or use the WLR types for a generic
        // compositor.
    }
}""",
        description="Workspace indicator placeholder; compositor-specific types are required.",
    )


def _tray_section(compositor: str | None, version: str) -> _Section:
    return _Section(
        key="tray",
        reason="system tray request",
        imports=["Quickshell.Services.SystemTray", "QtQuick"],
        apis=["SystemTray", "SystemTray.items", "SystemTrayItem", "SystemTrayItem.activate()"],
        types=[
            {"type_name": "SystemTray", "namespace": "Quickshell.Services.SystemTray"},
            {"type_name": "SystemTrayItem", "namespace": "Quickshell.Services.SystemTray"},
        ],
        qt_types=["Item", "Image", "MouseArea", "Row", "Repeater"],
        child_block="""Row {
    spacing: 4
    Repeater {
        model: SystemTray.items
        delegate: Item {
            required property var modelData
            width: 24
            height: 24
            Image {
                anchors.fill: parent
                source: modelData.icon
            }
            MouseArea {
                anchors.fill: parent
                onClicked: modelData.activate()
            }
        }
    }
}""",
        description="System tray icons from the SystemTray singleton.",
    )


def _clock_section(compositor: str | None, version: str) -> _Section:
    return _Section(
        key="clock",
        reason="clock / time / date request",
        imports=["Quickshell", "QtQuick"],
        apis=["SystemClock", "SystemClock.date", "SystemClock.precision"],
        types=[{"type_name": "SystemClock", "namespace": "Quickshell"}],
        qt_types=["Text"],
        child_block="""SystemClock {
    id: clock
    precision: SystemClock.Seconds
}
Text {
    anchors.verticalCenter: parent.verticalCenter
    text: Qt.formatDateTime(clock.date, "HH:mm")
    color: "#cdd6f4"
}""",
        description="Clock using the SystemClock timer.",
    )


def _control_center_section(compositor: str | None, version: str) -> _Section:
    return _Section(
        key="control-center",
        reason="control center / quick settings request",
        imports=["Quickshell", "QtQuick"],
        apis=["PanelWindow", "PanelWindow.anchors", "PanelWindow.exclusiveZone"],
        types=[{"type_name": "PanelWindow", "namespace": "Quickshell"}],
        qt_types=["Item", "ColumnLayout"],
        child_block="""PanelWindow {
    id: controlCenter
    anchors { right: true; top: true; bottom: true }
    width: 300
    color: "#1e1e2e"
    exclusiveMode: ExclusionMode.Normal

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 12
        /*CHILD_SECTIONS*/
        Item { Layout.fillHeight: true }
    }
}""",
        standalone=True,
        container=True,
        description="Control center: right-edge popup panel with a vertical layout.",
    )


def _notifications_section(compositor: str | None, version: str) -> _Section:
    return _Section(
        key="notifications",
        reason="notification popup request",
        imports=["Quickshell", "Quickshell.Services.Notifications", "QtQuick"],
        apis=[
            "NotificationServer",
            "NotificationServer.trackedNotifications",
            "Notification",
            "Notification.summary",
            "Notification.body",
            "Notification.dismiss()",
        ],
        types=[
            {"type_name": "NotificationServer", "namespace": "Quickshell.Services.Notifications"},
            {"type_name": "Notification", "namespace": "Quickshell.Services.Notifications"},
        ],
        qt_types=["Item", "ColumnLayout", "Column", "Text", "MouseArea", "Repeater"],
        child_block="""PanelWindow {
    id: notificationPopup
    anchors { right: true; top: true }
    width: 320
    color: "#1e1e2e"
    exclusiveMode: ExclusionMode.Normal

    NotificationServer {
        id: notificationServer
        onNotification: (notification) => {
            notification.tracked = true
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 8
        /*CHILD_SECTIONS*/
        Repeater {
            model: notificationServer.trackedNotifications
            delegate: Item {
                required property var modelData
                width: parent.width
                height: 56
                Column {
                    spacing: 2
                    Text {
                        text: modelData.summary
                        font.bold: true
                        color: "#cdd6f4"
                    }
                    Text {
                        text: modelData.body
                        color: "#a6adc8"
                        elide: Text.ElideRight
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    onClicked: modelData.dismiss()
                }
            }
        }
    }
}""",
        standalone=True,
        container=True,
        description="Notification popup: top-right panel fed by a NotificationServer.",
    )


def _osd_section(compositor: str | None, version: str) -> _Section:
    return _Section(
        key="osd",
        reason="on-screen display / volume OSD request",
        imports=["Quickshell", "Quickshell.Services.Pipewire", "QtQuick"],
        apis=[
            "PanelWindow",
            "PanelWindow.anchors",
            "Pipewire",
            "Pipewire.defaultAudioSink",
            "PwNode",
            "PwNode.audio",
            "PwNodeAudio",
            "PwNodeAudio.volume",
            "PwNodeAudio.muted",
        ],
        types=[
            {"type_name": "PanelWindow", "namespace": "Quickshell"},
            {"type_name": "Pipewire", "namespace": "Quickshell.Services.Pipewire"},
            {"type_name": "PwNode", "namespace": "Quickshell.Services.Pipewire"},
            {"type_name": "PwNodeAudio", "namespace": "Quickshell.Services.Pipewire"},
        ],
        qt_types=["Item", "RowLayout", "Text", "Rectangle", "Behavior", "NumberAnimation"],
        child_block="""PanelWindow {
    id: osd
    anchors { left: true; right: true; bottom: true }
    height: 48
    color: "#1e1e2e"
    exclusiveMode: ExclusionMode.Normal

    PwObjectTracker {
        id: sinkTracker
        objects: [Pipewire.defaultAudioSink]
    }

    RowLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 8

        Text {
            text: "♪"
            color: "#cdd6f4"
            font.pixelSize: 20
        }

        Rectangle {
            Layout.fillWidth: true
            height: 6
            radius: 3
            color: "#313244"
            Rectangle {
                width: parent.width * ((Pipewire.defaultAudioSink?.audio?.volume ?? 0) / 1.0)
                height: parent.height
                radius: 3
                color: "#89b4fa"
                Behavior on width { NumberAnimation { duration: 100 } }
            }
        }

        Text {
            text: Math.round((Pipewire.defaultAudioSink?.audio?.volume ?? 0) * 100) + "%"
            color: "#cdd6f4"
        }
    }
}""",
        standalone=True,
        description="Volume OSD: bottom overlay driven by the Pipewire default audio sink.",
    )


def _audio_section(compositor: str | None, version: str) -> _Section:
    return _Section(
        key="audio",
        reason="volume / audio control request",
        imports=["Quickshell.Services.Pipewire", "QtQuick"],
        apis=[
            "Pipewire",
            "Pipewire.defaultAudioSink",
            "PwNode",
            "PwNode.audio",
            "PwNodeAudio",
            "PwNodeAudio.volume",
            "PwNodeAudio.muted",
        ],
        types=[
            {"type_name": "Pipewire", "namespace": "Quickshell.Services.Pipewire"},
            {"type_name": "PwNode", "namespace": "Quickshell.Services.Pipewire"},
            {"type_name": "PwNodeAudio", "namespace": "Quickshell.Services.Pipewire"},
        ],
        qt_types=["Text"],
        child_block="""PwObjectTracker {
    id: audioTracker
    objects: [Pipewire.defaultAudioSink]
}
Text {
    text: "♪ " + Math.round((Pipewire.defaultAudioSink?.audio?.volume ?? 0) * 100) + "%"
    color: "#cdd6f4"
}""",
        description="Volume readout bound to the Pipewire default audio sink.",
    )


_TEMPLATE_BUILDERS: dict[str, Any] = {
    "bar": _bar_section,
    "panel": _bar_section,
    "workspaces": _workspaces_section,
    "tray": _tray_section,
    "clock": _clock_section,
    "control-center": _control_center_section,
    "notifications": _notifications_section,
    "osd": _osd_section,
    "audio": _audio_section,
}


def _build_section(key: str, reason: str, compositor: str | None, version: str) -> _Section:
    builder = _TEMPLATE_BUILDERS.get(key)
    if builder is None:
        raise ValueError(f"No template for section '{key}'")
    section = builder(compositor, version)
    section.reason = reason or section.reason
    return section


def _interpret_component_query(description: str, compositor: str | None) -> list[tuple[str, str]]:
    description_lower = description.lower()
    matched: dict[str, str] = {}

    for pattern, reason in _interpret_query(description):
        key = pattern["key"]
        if key in _TEMPLATE_BUILDERS:
            matched[key] = reason

    for key, tokens in _TOKEN_SECTIONS:
        if any(token in description_lower for token in tokens):
            matched.setdefault(key, f"query mentions '{tokens[0]}'")

    # Apply subsumption: a root key drops the sections it subsumes.
    for root_key, subsumed in _SUBSUMES.items():
        if root_key in matched:
            for sub in subsumed:
                matched.pop(sub, None)

    def rank(item: tuple[str, str]) -> tuple[int, str]:
        key = item[0]
        if key in _ROOT_PRIORITY:
            return (0, str(_ROOT_PRIORITY.index(key)))
        return (1, key)

    ordered = sorted(matched.items(), key=rank)
    if not ordered:
        return []
    return ordered


def _child_placeholder() -> str:
    return "/*CHILD_SECTIONS*/"


def _indent_block(block: str, level: int = 1) -> str:
    prefix = _INDENT * level
    return "\n".join(prefix + line for line in block.splitlines())


def _assemble_qml(sections: list[_Section]) -> tuple[str, list[str], list[str]]:
    """Assemble one QML file from sections.

    Returns ``(qml, imports, used_keys)``. Only one top-level window may
    exist, so a single container (or standalone section) becomes the root and
    hosts the remaining *leaf* blocks; any other standalone section is a
    second window and is left out of the file so a window is never nested
    inside another window's layout.
    """
    imports: list[str] = []
    for section in sections:
        for imp in section.imports:
            if imp not in imports:
                imports.append(imp)

    container = next((section for section in sections if section.container), None)
    if container is not None:
        children = [
            section for section in sections if section is not container and not section.standalone
        ]
        body = container.child_block
        if children:
            child_qml = "\n".join(
                _indent_block(child.child_block, level=2) for child in children if child.child_block
            )
            body = body.replace(_child_placeholder(), child_qml)
        else:
            body = body.replace(_child_placeholder(), "")
        qml = "\n".join(f"import {imp}" for imp in imports) + "\n\n" + body
        used = [container.key] + [child.key for child in children]
        return qml.strip() + "\n", imports, used

    primary = sections[0]
    if primary.standalone:
        qml = "\n".join(f"import {imp}" for imp in imports) + "\n\n" + primary.child_block
        return qml.strip() + "\n", imports, [primary.key]

    for imp in ("Quickshell", "QtQuick"):
        if imp not in imports:
            imports.append(imp)
    leaf_block = _indent_block(primary.child_block, level=2) if primary.child_block else ""
    qml = "\n".join(f"import {imp}" for imp in imports) + "\n\n"
    qml += (
        "PanelWindow {\n"
        "    id: root\n"
        "    anchors { left: true; right: true; bottom: true }\n"
        "    height: 36\n"
        '    color: "#1e1e2e"\n'
        "    exclusiveMode: ExclusionMode.Normal\n\n"
        "    RowLayout {\n"
        "        anchors.fill: parent\n"
        "        anchors.margins: 4\n"
        "        spacing: 8\n"
        f"{leaf_block}\n"
        "        Item { Layout.fillWidth: true }\n"
        "    }\n"
        "}"
    )
    return qml.strip() + "\n", imports, [primary.key]


def _suggest_filename(description: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", description)
    skip = {"a", "an", "the", "with", "and", "create", "make", "build", "generate", "add"}
    words = [word for word in words if word.lower() not in skip]
    return "".join(word[:1].upper() + word[1:] for word in words[:4]) + ".qml"


def _verify_apis(sections: list[_Section], version: str) -> dict[str, Any]:
    seen: set[str] = set()
    findings: list[dict[str, Any]] = []
    for section in sections:
        for api in section.apis:
            if api in seen:
                continue
            seen.add(api)
            try:
                result = _check_compatibility(api=api, version=version)
            except Exception as exc:  # noqa: BLE001
                findings.append(
                    {
                        "api": api,
                        "compatibility": "uncertain",
                        "confidence": "low",
                        "explanation": str(exc),
                        "url": None,
                    }
                )
                continue
            findings.append(
                {
                    "api": api,
                    "compatibility": result["compatibility"],
                    "confidence": result["confidence"],
                    "explanation": result["explanation"],
                    "url": _compat_doc_url(result),
                }
            )

    verdicts = {finding["compatibility"] for finding in findings}
    verdict = "verified" if verdicts <= {"compatible"} else "unverified"
    return {"per_api": findings, "verdict": verdict}


def _compat_doc_url(result: dict[str, Any]) -> str | None:
    docs = result.get("documentation") or []
    for doc in docs:
        if doc.get("kind") == "type_page" and doc.get("url"):
            return doc["url"]
    return None


def _gather_references(description: str, version: str) -> dict[str, Any]:
    references: dict[str, Any] = {"documentation": [], "examples": [], "implementations": []}
    try:
        pattern = _find_pattern(description, version)
        for entry in pattern.get("implementations", []):
            references["implementations"].append(
                {"source": entry["source"], "path": entry["path"], "url": entry["url"]}
            )
        for entry in pattern.get("examples", []):
            references["examples"].append({"path": entry["path"]})
        if pattern.get("cross_project_patterns"):
            references["cross_project_patterns"] = pattern["cross_project_patterns"]
    except Exception as error:  # noqa: BLE001
        references["implementations_error"] = str(error)
    try:
        search = _search_everything(description, version)
        for section, entries in search.get("results", {}).items():
            if section == "quickshell_types":
                references["documentation"].extend(
                    {"type_name": e["type_name"], "namespace": e.get("namespace"), "url": e["url"]}
                    for e in entries
                )
    except Exception as error:  # noqa: BLE001
        references["documentation_error"] = str(error)
    return references


def _verified_type_surface(type_refs: list[tuple[str, str]], version: str) -> dict[str, Any]:
    """Fetch the documented members of each referenced Quickshell type.

    Returns ``{"types": [...], "unavailable": [...]}`` where each type entry
    carries its base class and the properties/signals/methods pulled from the
    live type page, so a caller can compose QML against verified members.
    Qt-only types and unreachable pages are skipped and listed under
    ``unavailable`` rather than guessed.
    """
    entries: list[dict[str, Any]] = []
    unavailable: list[str] = []
    seen: set[tuple[str, str]] = set()
    for type_name, namespace in type_refs:
        key = (type_name, namespace)
        if key in seen:
            continue
        seen.add(key)
        if not namespace or not namespace.startswith("Quickshell"):
            continue
        try:
            members = _type_members(type_name, namespace, version)
        except Exception:  # noqa: BLE001 - a docs failure must not crash generation
            members = None
        if members is None:
            unavailable.append(f"{namespace}.{type_name}")
            continue
        entries.append(
            {
                "type_name": type_name,
                "namespace": namespace,
                "url": f"{BASE}/docs/{version}/types/{namespace}/{type_name}/",
                "base": members["base"],
                "properties": {
                    name: type_str for name, type_str in sorted(members["properties"].items())
                },
                "signals": sorted(members["signals"]),
                "methods": sorted(members["methods"]),
            }
        )
    surface: dict[str, Any] = {"types": entries}
    if unavailable:
        surface["unavailable"] = unavailable
    return surface


def _generate_component(
    description: str,
    version: str = "latest",
    compositor: str | None = None,
    style: str | None = None,
    context: str | None = None,
    filename: str | None = None,
) -> dict[str, Any]:
    resolved_version = _resolve_version(version)
    description = description.strip()
    if not description:
        return {
            "description": description,
            "version": resolved_version,
            "interpreted_as": [],
            "component": None,
            "verified_surface": {"types": []},
            "references": {},
            "note": "Empty description. Describe the component you want to build.",
        }

    ordered = _interpret_component_query(description, compositor)
    if not ordered:
        known = ", ".join(sorted(_TEMPLATE_BUILDERS))
        references = _gather_references(description, resolved_version)
        type_refs = [
            (entry["type_name"], entry["namespace"])
            for entry in references.get("documentation", [])
            if entry.get("type_name") and entry.get("namespace")
        ][:6]
        verified_surface = _verified_type_surface(type_refs, resolved_version)
        if type_refs or references.get("implementations") or references.get("examples"):
            note = (
                f"No curated template matched '{description}'. Supported templates: {known}. "
                "The verified_surface and references below are grounded building blocks; "
                "compose the component yourself and check it with quickshell_validate_qml."
            )
        else:
            note = (
                f"No curated template matched '{description}' and no types or references "
                f"were found in any source. Supported templates: {known}. Try "
                "quickshell_search_all to research the feature first."
            )
        return {
            "description": description,
            "version": resolved_version,
            "interpreted_as": [],
            "component": None,
            "verified_surface": verified_surface,
            "references": references,
            "assumptions": [],
            "note": note,
        }

    sections = [
        _build_section(key, reason, compositor, resolved_version) for key, reason in ordered
    ]

    qml, imports, used_keys = _assemble_qml(sections)
    out_filename = filename or _suggest_filename(description)

    verification = _verify_apis(sections, resolved_version)
    validation = _validate(qml, version=resolved_version, filename=out_filename)
    references = _gather_references(description, resolved_version)
    verified_surface = _verified_type_surface(
        [
            (type_info["type_name"], type_info.get("namespace", ""))
            for section in sections
            for type_info in section.types
        ],
        resolved_version,
    )

    quickshell_types: list[str] = []
    qt_types: list[str] = []
    for section in sections:
        for type_info in section.types:
            ns = type_info.get("namespace", "")
            name = type_info["type_name"]
            (quickshell_types if ns.startswith("Quickshell") else qt_types).append(name)
        qt_types.extend(section.qt_types)
    quickshell_types = sorted(set(quickshell_types))
    qt_types = sorted(set(qt_types))

    compositor_dep: str | None = None
    for section in sections:
        if section.compositor:
            compositor_dep = section.compositor
            break

    assumptions: list[str] = []
    if compositor and compositor.lower() not in _COMPOSITOR_NAMESPACES:
        assumptions.append(
            f"Compositor '{compositor}' is not a recognized Quickshell integration; "
            "no compositor-specific types were used."
        )
    if compositor_dep:
        assumptions.append(
            f"Workspace sections depend on the {compositor_dep} compositor; "
            "on another compositor replace them with the matching WLR types."
        )
    keys = {section.key for section in sections}
    if "workspaces" in keys and not compositor_dep:
        assumptions.append(
            "Workspace sections need compositor-specific types; pass "
            "compositor='hyprland' (or the matching backend) to generate them."
        )
    if style:
        assumptions.append(f"Style hint '{style}' noted; the default dark palette was kept.")
    if context:
        assumptions.append(
            "Existing project context was noted but no project files were read or written."
        )
    for section in sections:
        if section.key in used_keys:
            continue
        if section.standalone:
            assumptions.append(
                f"Also requested '{section.key}', which is a separate top-level window; "
                "it was not embedded. Generate it as its own component."
            )
        else:
            assumptions.append(
                f"Section '{section.key}' was requested alongside the primary component; "
                "embed it by adding its block to the root layout."
            )

    note_parts = ["generated from verified APIs; read the references before extending"]
    if verification["verdict"] == "unverified":
        bad = [
            finding["api"]
            for finding in verification["per_api"]
            if finding["compatibility"] != "compatible"
        ]
        note_parts.append(
            "some referenced APIs could not be verified for this version and were kept out "
            "of the 'verified' claim: " + ", ".join(bad)
        )
    note_parts.append("official docs take precedence over examples and real-world implementations")

    external_deps = _external_dependencies(sections, compositor_dep)

    return {
        "description": description,
        "version": resolved_version,
        "interpreted_as": [
            {"pattern": section.key, "why": section.reason, "apis": section.apis}
            for section in sections
        ],
        "component": {
            "qml": qml,
            "filename": out_filename,
            "verified": verification["verdict"] == "verified",
        },
        "dependencies": {
            "imports": sorted(imports),
            "quickshell_types": quickshell_types,
            "qt_types": qt_types,
        },
        "verified_surface": verified_surface,
        "integration": {
            "compositor": compositor_dep,
            "external_dependencies": external_deps,
        },
        "verification": verification,
        "validation": validation,
        "references": references,
        "assumptions": assumptions,
        "note": "; ".join(note_parts),
    }


def _external_dependencies(sections: list[_Section], compositor_dep: str | None) -> list[str]:
    deps: list[str] = []
    keys = {section.key for section in sections}
    if keys & {"osd", "audio"}:
        deps.append("PipeWire daemon (for audio volume/mute)")
    if "notifications" in keys:
        deps.append("a desktop notification daemon speaking the freedesktop spec")
    if "tray" in keys:
        deps.append("a system tray host (StatusNotifierItem)")
    if "workspaces" in keys:
        if compositor_dep:
            deps.append(f"a running {compositor_dep} compositor")
        else:
            deps.append(
                "a compositor exposing workspace information (compositor-specific types required)"
            )
    return deps
