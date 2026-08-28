"""Tests for quickshell_generate_component: minimal, docs-grounded generation.

Offline by construction: the reference searches reuse the committed
search_all fixtures, and the per-version indexes, type pages, and changelog
that verification and validation consult are synthetic snapshots in the real
quickshell.org markup format (same pattern as test_compat.py).
"""

from __future__ import annotations

import re

from conftest import load_fixture
from test_search_all import _install as install_search_fixtures

import quickshell_mcp.server as srv
from quickshell_mcp import utils  # noqa: E402
from quickshell_mcp.sources import generate as gen

QT = srv.QT_DOCS_BASE
BASE = srv.BASE

_VERSIONS = ["v0.3.1", "v0.3.0", "v0.2.1", "v0.2.0", "v0.1.0"]


def _wrap(markdown: str) -> str:
    return f"<html><body><main>{markdown}</main></body></html>"


def _type_page(
    title: str,
    base: str,
    props: list[tuple[str, str]] | None = None,
    methods: list[str] | None = None,
    signals: list[str] | None = None,
) -> str:
    lines = [
        f"# {title}",
        "",
        f"## {title}: [{base}]({base})",
        "",
        "## Properties [[?]](/docs/v0.3.1/guide/qml-language#properties)",
        "",
    ]
    for name, type_name in props or []:
        lines.append(f"- {name}  :")
        lines.append(f"  [{type_name}](https://doc.qt.io/qt-6/qml-{type_name}.html)")
        lines.append("")
    if methods:
        lines.append("## Functions [[?]](/docs/v0.3.1/guide/qml-language#functions)")
        lines.append("")
        for name in methods:
            lines.append(f"- {name} ()  :")
            lines.append("  [void](https://doc.qt.io/qt-6/qml-void.html)")
            lines.append("")
    if signals:
        lines.append("## Signals [[?]](/docs/v0.3.1/guide/qml-language#signals)")
        lines.append("")
        for name in signals:
            lines.append(f"- {name} ()")
            lines.append("")
    return "\n".join(lines)


_QT_OBJECT = "https://doc.qt.io/qt-6/qml-qtqml-qtobject.html"
_QS_WINDOW = "/docs/v0.3.1/types/Quickshell/QsWindow"


# Every type the templates reference, with the members the templates use.
_PAGES: dict[str, str] = {
    "Quickshell/PanelWindow": _type_page(
        "PanelWindow",
        _QS_WINDOW,
        props=[
            ("exclusiveZone", "int"),
            ("exclusionMode", "int"),
            ("anchors", "object"),
            ("focusable", "bool"),
        ],
        methods=["mapFromGlobal"],
        signals=["statusChanged", "closed"],
    ),
    "Quickshell/QsWindow": _type_page(
        "QsWindow", _QT_OBJECT, props=[("width", "int"), ("height", "int"), ("color", "color")]
    ),
    "Quickshell/ExclusionMode": _type_page("ExclusionMode", _QT_OBJECT, props=[("mode", "int")]),
    "Quickshell/SystemClock": _type_page(
        "SystemClock",
        _QT_OBJECT,
        props=[
            ("date", "date"),
            ("precision", "SystemClock"),
            ("hours", "int"),
            ("minutes", "int"),
            ("seconds", "int"),
        ],
    ),
    "Quickshell.Hyprland/Hyprland": _type_page(
        "Hyprland",
        _QT_OBJECT,
        props=[
            ("workspaces", "ObjectModel"),
            ("monitors", "ObjectModel"),
            ("focusedMonitor", "HyprlandMonitor"),
            ("focusedWorkspace", "HyprlandWorkspace"),
        ],
        methods=["dispatch", "refreshWorkspaces"],
        signals=["rawEvent"],
    ),
    "Quickshell.Hyprland/HyprlandWorkspace": _type_page(
        "HyprlandWorkspace",
        _QT_OBJECT,
        props=[
            ("active", "bool"),
            ("focused", "bool"),
            ("name", "string"),
            ("id", "int"),
            ("monitor", "HyprlandMonitor"),
            ("urgent", "bool"),
        ],
        methods=["activate"],
    ),
    "Quickshell.Hyprland/HyprlandMonitor": _type_page(
        "HyprlandMonitor",
        _QT_OBJECT,
        props=[
            ("name", "string"),
            ("width", "int"),
            ("height", "int"),
            ("focused", "bool"),
            ("activeWorkspace", "HyprlandWorkspace"),
        ],
    ),
    "Quickshell.Services.SystemTray/SystemTray": _type_page(
        "SystemTray", _QT_OBJECT, props=[("items", "ObjectModel")]
    ),
    "Quickshell.Services.SystemTray/SystemTrayItem": _type_page(
        "SystemTrayItem",
        _QT_OBJECT,
        props=[("icon", "string"), ("title", "string")],
        methods=["activate", "secondaryActivate"],
    ),
    "Quickshell.Services.Notifications/NotificationServer": _type_page(
        "NotificationServer",
        _QT_OBJECT,
        props=[("trackedNotifications", "ObjectModel"), ("actionsSupported", "bool")],
        signals=["notification"],
    ),
    "Quickshell.Services.Notifications/Notification": _type_page(
        "Notification",
        _QT_OBJECT,
        props=[
            ("summary", "string"),
            ("body", "string"),
            ("appName", "string"),
            ("tracked", "bool"),
        ],
        methods=["dismiss", "expire"],
        signals=["closed"],
    ),
    "Quickshell.Services.Pipewire/Pipewire": _type_page(
        "Pipewire",
        _QT_OBJECT,
        props=[
            ("defaultAudioSink", "PwNode"),
            ("defaultAudioSource", "PwNode"),
            ("nodes", "ObjectModel"),
            ("ready", "bool"),
        ],
    ),
    "Quickshell.Services.Pipewire/PwNode": _type_page(
        "PwNode",
        _QT_OBJECT,
        props=[("audio", "PwNodeAudio"), ("isSink", "bool"), ("name", "string"), ("ready", "bool")],
    ),
    "Quickshell.Services.Pipewire/PwNodeAudio": _type_page(
        "PwNodeAudio",
        _QT_OBJECT,
        props=[("volume", "real"), ("muted", "bool"), ("channels", "list")],
    ),
    "Quickshell.Services.Pipewire/PwObjectTracker": _type_page(
        "PwObjectTracker", _QT_OBJECT, props=[("objects", "list")]
    ),
}

# SystemClock and the service namespaces only exist from v0.3.1 on, mirroring
# how newer Quickshell releases gained these APIs.
_FULL_TYPES = {
    "Quickshell": ["PanelWindow", "QsWindow", "SystemClock", "ExclusionMode", "Quickshell"],
    "Quickshell.Hyprland": ["Hyprland", "HyprlandWorkspace", "HyprlandMonitor"],
    "Quickshell.Services.SystemTray": ["SystemTray", "SystemTrayItem"],
    "Quickshell.Services.Notifications": ["NotificationServer", "Notification"],
    "Quickshell.Services.Pipewire": ["Pipewire", "PwNode", "PwNodeAudio", "PwObjectTracker"],
}
_REDUCED_TYPES = {
    "Quickshell": ["PanelWindow", "QsWindow", "Quickshell", "ExclusionMode"],
    "Quickshell.Hyprland": ["Hyprland", "HyprlandWorkspace", "HyprlandMonitor"],
}


def _guide_index_html(version: str, types_by_ns: dict[str, list[str]]) -> str:
    links = []
    for ns, names in types_by_ns.items():
        for name in names:
            links.append(f'<a href="/docs/{version}/types/{ns}/{name}/">{name}</a>')
    return "<html><body><main>" + "".join(links) + "</main></body></html>"


def _changelog_html() -> str:
    return _wrap(
        "# Changelog\n"
        "\n"
        "## v0.3.1\n"
        "- Fixed hiding the last PanelWindow on screen causing a crash under X11.\n"
        "\n"
        "## v0.3.0\n"
        "\n"
        "## v0.2.1\n"
        "\n"
        "## v0.2.0\n"
        "\n"
        "## v0.1.0\n"
        "Initial release\n"
    )


def _build_generate_mapping(docs_fixture_urls: dict[str, str]) -> dict[str, str]:
    """Per-version indexes, type pages, changelog, and Qt module pages, layered
    on top of the committed search_all fixtures."""
    mapping = dict(docs_fixture_urls)
    mapping[f"{BASE}/changelog/"] = _changelog_html()

    for version in _VERSIONS:
        idx = _FULL_TYPES if version == "v0.3.1" else _REDUCED_TYPES
        mapping[f"{BASE}/docs/{version}/guide/"] = _guide_index_html(version, idx)
    for path, page in _PAGES.items():
        mapping[f"{BASE}/docs/v0.3.1/types/{path}/"] = _wrap(page)

    qt_htmls = [
        load_fixture("qt_qtquick_qmlmodule.html"),
        load_fixture("qt_qtquick_controls_qmlmodule.html"),
    ]
    mapping[f"{QT}/qtquick-qmlmodule.html"] = qt_htmls[0]
    mapping[f"{QT}/qtquick-controls-qmlmodule.html"] = qt_htmls[1]
    for html in qt_htmls:
        for stem in re.findall(r'href="([a-z0-9-]+-qmlmodule)\.html"', html):
            mapping.setdefault(f"{QT}/{stem}.html", "")
    return mapping


def _install_generate_fixtures(
    monkeypatch, docs_fixture_urls: dict[str, str], extra_404: set[str] | None = None
) -> None:
    """Install the search_all fixtures, then layer the generation fixtures on
    top; the outer fetch answers generation URLs first and delegates the rest."""
    install_search_fixtures(monkeypatch, docs_fixture_urls, extra_404=extra_404)
    search_fetch = utils._fetch_raw
    mapping = _build_generate_mapping(docs_fixture_urls)

    def fake_fetch(url: str) -> str:
        if url in mapping:
            return mapping[url]
        return search_fetch(url)

    monkeypatch.setattr(utils, "_fetch_raw", fake_fetch)


def test_simple_component_generation(monkeypatch, docs_fixture_urls):
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._generate_component("Create a Hyprland workspace indicator", compositor="hyprland")

    assert out["version"] == "v0.3.1"
    assert out["interpreted_as"][0]["pattern"] == "workspaces"
    assert out["component"]["verified"] is True
    assert "WorkspaceIndicator" in out["component"]["filename"]
    assert out["component"]["filename"].endswith(".qml")
    qml = out["component"]["qml"]
    assert "import Quickshell.Hyprland" in qml
    assert "Hyprland.workspaces" in qml
    assert "HyprlandWorkspace" in out["dependencies"]["quickshell_types"]
    assert "PanelWindow" in qml
    assert "Hyprland" in out["integration"]["compositor"]
    assert out["validation"]["summary"]["errors"] == 0
    assert out["references"]["implementations"]


def test_multiple_quickshell_types(monkeypatch, docs_fixture_urls):
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._generate_component("top bar with workspaces and clock", compositor="hyprland")

    qml = out["component"]["qml"]
    assert qml.count("PanelWindow") == 1
    # The bar is the root; workspaces and clock are embedded children.
    assert "Hyprland.workspaces" in qml
    assert "SystemClock" in qml
    deps = out["dependencies"]
    assert "Quickshell" in deps["imports"]
    assert "Quickshell.Hyprland" in deps["imports"]
    assert {"PanelWindow", "Hyprland", "HyprlandWorkspace", "SystemClock"} <= set(
        deps["quickshell_types"]
    )
    assert out["component"]["verified"] is True


def test_qt_and_quickshell_combination(monkeypatch, docs_fixture_urls):
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._generate_component("volume OSD")

    qml = out["component"]["qml"]
    assert "PanelWindow" in qml
    assert "Pipewire.defaultAudioSink" in qml
    assert "Behavior on width" in qml  # Qt animation driving the OSD bar
    assert "Rectangle" in out["dependencies"]["qt_types"]
    assert {"PanelWindow"} <= set(out["dependencies"]["quickshell_types"])
    assert out["verification"]["verdict"] == "verified"
    assert any("PipeWire daemon" in dep for dep in out["integration"]["external_dependencies"])


def test_top_bar_with_tray_clock_workspaces(monkeypatch, docs_fixture_urls):
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._generate_component(
        "top bar with workspaces, clock and system tray", compositor="hyprland"
    )

    patterns = {entry["pattern"] for entry in out["interpreted_as"]}
    assert {"bar", "workspaces", "tray", "clock"} <= patterns
    qml = out["component"]["qml"]
    assert qml.count("PanelWindow") == 1
    assert "SystemTray.items" in qml
    assert "SystemClock" in qml
    assert "Hyprland.workspaces" in qml


def test_version_specific_generation_flags_absent_api(monkeypatch, docs_fixture_urls):
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._generate_component("clock", version="v0.2.0")

    assert out["version"] == "v0.2.0"
    # SystemClock does not exist in v0.2.0; verification must not claim it does.
    assert out["verification"]["verdict"] == "unverified"
    bad = [f["api"] for f in out["verification"]["per_api"] if f["compatibility"] != "compatible"]
    assert any("SystemClock" in api for api in bad)
    assert out["component"]["verified"] is False

    latest = srv._generate_component("clock", version="v0.3.1")
    assert latest["verification"]["verdict"] == "verified"


def test_compositor_specific_generation(monkeypatch, docs_fixture_urls):
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)

    hypr = srv._generate_component("workspace indicator", compositor="hyprland")
    assert "import Quickshell.Hyprland" in hypr["component"]["qml"]
    assert hypr["integration"]["compositor"] == "Hyprland"
    assert "Hyprland.workspaces" in hypr["component"]["qml"]

    generic = srv._generate_component("workspace indicator")
    assert "import Quickshell.Hyprland" not in generic["component"]["qml"]
    assert "Hyprland.workspaces" not in generic["component"]["qml"]
    assert generic["integration"]["compositor"] is None
    assert any("compositor" in a.lower() for a in generic["assumptions"])

    sway = srv._generate_component("workspace indicator", compositor="sway")
    assert any("sway" in a.lower() for a in sway["assumptions"])


def test_invalid_request_is_loud(monkeypatch, docs_fixture_urls):
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._generate_component("zzzqqq wibble")

    assert out["interpreted_as"] == []
    assert out["component"] is None
    assert "verified_surface" in out
    assert out["verified_surface"]["types"] == []
    assert "no types or references" in out["note"]


def test_empty_description_short_circuits(monkeypatch, docs_fixture_urls):
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._generate_component("   ")
    assert out["component"] is None
    assert "verified_surface" in out
    assert "Empty description" in out["note"]


def test_generated_code_unknown_api_is_surfaced(monkeypatch, docs_fixture_urls):
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)

    real_check = gen._check_compatibility

    def fake_check(api: str | None = None, **kwargs):
        if api == "Hyprland.workspaces":
            return {
                "compatibility": "incompatible",
                "confidence": "high",
                "explanation": "Hyprland.workspaces does not exist.",
                "documentation": [],
            }
        return real_check(api=api, **kwargs)

    monkeypatch.setattr(gen, "_check_compatibility", fake_check)
    out = srv._generate_component("workspace indicator", compositor="hyprland")

    assert out["verification"]["verdict"] == "unverified"
    assert out["component"]["verified"] is False
    assert any(
        f["api"] == "Hyprland.workspaces" and f["compatibility"] == "incompatible"
        for f in out["verification"]["per_api"]
    )
    assert "Hyprland.workspaces" in out["note"]


def test_validation_failures_are_reported(monkeypatch, docs_fixture_urls):
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)

    def bad_clock(compositor, version):
        section = gen._clock_section(compositor, version)
        section.child_block = "PanelWindow {\n    totallyUnknownProp: 1\n}"
        section.standalone = True
        section.apis = []
        return section

    monkeypatch.setattr(gen, "_TEMPLATE_BUILDERS", {**gen._TEMPLATE_BUILDERS, "clock": bad_clock})
    out = srv._generate_component("clock")

    codes = {diag["code"] for diag in out["validation"]["diagnostics"]}
    assert "unknown_property" in codes
    assert out["validation"]["summary"]["warnings"] >= 1


def test_no_result_implementation_searches_do_not_block_generation(monkeypatch, docs_fixture_urls):
    cael_tree = f"{srv._GITHUB_API}/repos/caelestia-dots/shell/git/trees/main?recursive=1"
    noct_tree = f"{srv._GITHUB_API}/repos/noctalia-dev/noctalia/git/trees/legacy-v4?recursive=1"
    dots_tree = f"{srv._GITHUB_API}/repos/end-4/dots-hyprland/git/trees/main?recursive=1"
    _install_generate_fixtures(
        monkeypatch, docs_fixture_urls, extra_404={cael_tree, noct_tree, dots_tree}
    )

    out = srv._generate_component("volume OSD")
    assert out["component"] is not None
    assert out["verification"]["verdict"] == "verified"
    # No implementations were findable, but generation still completed.
    assert out["references"]["implementations"] == []


def test_wrapper_records_stats(monkeypatch, docs_fixture_urls):
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    before = dict(srv._TOOL_CALLS)
    srv.quickshell_generate_component("clock")
    expected = before.get("quickshell_generate_component", 0) + 1
    assert srv._TOOL_CALLS["quickshell_generate_component"] == expected


def test_every_template_api_verifies_against_fixtures(monkeypatch, docs_fixture_urls):
    """Each curated template only references APIs that exist in the docs
    index, exercised through the real compatibility machinery."""
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    for key in gen._TEMPLATE_BUILDERS:
        for compositor in (None, "hyprland"):
            section = gen._build_section(key, "", compositor, "v0.3.1")
            result = gen._verify_apis([section], "v0.3.1")
            if key == "workspaces" and compositor is None:
                # The generic placeholder references no APIs, so nothing is
                # checked rather than everything passing.
                assert result["verdict"] == "unchecked", f"{key} ({compositor})"
            else:
                assert result["verdict"] == "verified", (
                    f"{key} (compositor={compositor}): {result['per_api']}"
                )


def test_template_query_coverage():
    """Every supported template key is reachable from a plain-language
    request through the existing pattern interpreter."""
    requests = {
        "bar": "top bar",
        "panel": "status panel",
        "workspaces": "workspace indicator",
        "tray": "system tray",
        "clock": "clock",
        "control-center": "quick settings",
        "notifications": "notification popup",
        "osd": "volume OSD",
        "audio": "volume control",
    }
    for key, request in requests.items():
        keys = {k for k, _ in gen._interpret_component_query(request, "hyprland")}
        assert key in keys, f"request '{request}' did not map to template '{key}'"
    assert gen._interpret_component_query("zzzqqq wibble", None) == []
    assert gen._interpret_component_query("", None) == []


def test_subsumption_drops_audio_when_osd_present():
    keys = {k for k, _ in gen._interpret_component_query("volume OSD", None)}
    assert "osd" in keys
    assert "audio" not in keys


def test_token_sections_match_word_boundaries():
    # "date" must not match inside unrelated words like "updated" or "mandate".
    assert gen._interpret_component_query("updated mandate widget", None) == []
    assert {k for k, _ in gen._interpret_component_query("show the time", None)} >= {"clock"}
    assert {k for k, _ in gen._interpret_component_query("set the clock", None)} >= {"clock"}


def test_verified_surface_in_generation(monkeypatch, docs_fixture_urls):
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._generate_component("workspace indicator", compositor="hyprland")

    surface = out["verified_surface"]
    assert surface["types"]
    hyprland = next(t for t in surface["types"] if t["type_name"] == "HyprlandWorkspace")
    assert "name" in hyprland["properties"]
    assert "active" in hyprland["properties"]
    assert "activate" in hyprland["methods"]
    assert hyprland["url"].startswith("https://quickshell.org/")
    assert any(t["type_name"] == "Hyprland" for t in surface["types"])


def test_no_match_returns_verified_research(monkeypatch, docs_fixture_urls):
    """A feature request that matches no template still returns research."""
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._generate_component("app launcher")

    assert out["interpreted_as"] == []
    assert out["component"] is None
    assert "verified_surface" in out
    assert "compose the component yourself" in out["note"]
    # The launcher topic matches implementations in the impl trees.
    assert out["references"]["implementations"]


def test_verified_surface_omits_unavailable_pages(monkeypatch, docs_fixture_urls):
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)

    def fake_members(*args, **kwargs):
        return None

    monkeypatch.setattr(gen, "_type_members", fake_members)
    out = srv._generate_component("clock")

    surface = out["verified_surface"]
    assert surface["types"] == []
    assert "unavailable" in surface
    assert any("SystemClock" in entry for entry in surface["unavailable"])


def test_multiple_windows_not_embedded(monkeypatch, docs_fixture_urls):
    """Two standalone/container sections must not nest windows."""
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._generate_component("top bar with notification popup")

    qml = out["component"]["qml"]
    assert qml.count("PanelWindow") == 1
    assert any("notifications" in a for a in out["assumptions"])


def test_osd_and_notifications_produces_one_window(monkeypatch, docs_fixture_urls):
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._generate_component("volume OSD and notification popup")

    qml = out["component"]["qml"]
    assert qml.count("PanelWindow") == 1


def test_control_center_and_notifications_produces_one_window(monkeypatch, docs_fixture_urls):
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._generate_component("control center with notification popup")

    qml = out["component"]["qml"]
    assert qml.count("PanelWindow") == 1
    assert any("notifications" in a for a in out["assumptions"])


def test_standalone_leaf_dropped_not_spliced(monkeypatch, docs_fixture_urls):
    """A standalone section that is not the root is dropped, not spliced."""
    _install_generate_fixtures(monkeypatch, docs_fixture_urls)
    out = srv._generate_component("volume OSD with clock")

    qml = out["component"]["qml"]
    assert qml.count("PanelWindow") == 1
    # The clock was dropped because osd is standalone and cannot host children.
    assert any("clock" in a for a in out["assumptions"])
