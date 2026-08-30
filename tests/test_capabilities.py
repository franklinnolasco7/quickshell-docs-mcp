"""Capability-layer architecture tests.

These tests verify the internal boundaries introduced by the capability
layer (``quickshell_mcp/capabilities/``):

- every MCP tool still registers and belongs to exactly one capability
- the capability dependency graph is complete and acyclic
- planned-but-unimplemented capabilities are registry entries only, with no
  placeholder modules
- every package module imports cleanly (no broken or circular imports)
- the capability layer re-exports the same function objects the tests and
  server have always addressed (behavior preserved, no copies)
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path

import pytest

import quickshell_mcp.server as srv
from quickshell_mcp.capabilities import registry

EXPECTED_TOOLS = {
    "quickshell_list_versions",
    "quickshell_about",
    "quickshell_changelog",
    "quickshell_list_guide_pages",
    "quickshell_get_guide_page",
    "quickshell_list_types",
    "quickshell_get_type",
    "quickshell_search",
    "quickshell_search_all",
    "quickshell_find_pattern",
    "quickshell_list_qt_types",
    "quickshell_get_qt_type",
    "quickshell_list_examples",
    "quickshell_get_example",
    "quickshell_search_implementations",
    "quickshell_get_implementation",
    "quickshell_explain_error",
    "quickshell_validate_qml",
    "quickshell_check_compatibility",
    "quickshell_migrate",
    "quickshell_stats",
    "quickshell_generate_component",
    "quickshell_coding_assistant",
    "quickshell_project_analyze",
    "quickshell_project_map",
    "quickshell_project_find",
    "quickshell_project_dependencies",
    "quickshell_project_config",
    "quickshell_project_validate",
    "quickshell_project_lint",
    "quickshell_project_compatibility",
    "quickshell_project_migrate",
    "quickshell_generate_service",
    "quickshell_generate_panel",
    "quickshell_refactor",
    "quickshell_apply_patch",
    "quickshell_style_match",
}

# Tools that report session telemetry / live in server.py, not a domain capability.
SYSTEM_TOOLS = {"quickshell_stats"}


def _registered_tools() -> set[str]:
    return {t.name for t in srv.mcp._tool_manager.list_tools()}


def _capability_tools() -> set[str]:
    return {tool for cap in registry.CAPABILITIES.values() for tool in cap.tools}


# --- Tool registration -----------------------------------------------------


def test_all_tools_registered():
    assert _registered_tools() == EXPECTED_TOOLS


def test_every_tool_maps_to_exactly_one_capability():
    owned = _capability_tools()
    assert owned == EXPECTED_TOOLS - SYSTEM_TOOLS
    for tool in owned:
        cap = registry.capability_for_tool(tool)
        assert cap is not None, f"tool {tool} maps to no capability"
        assert tool in registry.CAPABILITIES[cap].tools


def test_system_tools_are_not_domain_capabilities():
    for tool in SYSTEM_TOOLS:
        assert registry.capability_for_tool(tool) is None
        assert tool not in _capability_tools()


# --- Capability dependency graph -------------------------------------------


def test_capability_dependencies_are_registered():
    for name, cap in registry.CAPABILITIES.items():
        for dep in cap.depends_on:
            assert dep in registry.CAPABILITIES, (
                f"capability {name!r} depends on unregistered {dep!r}"
            )


def test_capability_dependency_order_is_acyclic():
    order = registry.dependency_order()
    assert set(order) == set(registry.CAPABILITIES)
    seen = set()
    for name in order:
        for dep in registry.CAPABILITIES[name].depends_on:
            assert dep in seen, f"dependency {dep!r} of {name!r} not resolved before it: {order}"
        seen.add(name)


def test_assistant_depends_on_all_other_capabilities():
    others = set(registry.CAPABILITIES) - {"assistant"}
    assert set(registry.CAPABILITIES["assistant"].depends_on) == others


# --- Planned capabilities --------------------------------------------------


def test_planned_capabilities_are_metadata_only():
    for name, cap in registry.PLANNED_CAPABILITIES.items():
        assert cap.status == "planned"
        assert cap.tools == ()
        assert not importlib.util.find_spec(f"quickshell_mcp.capabilities.{name}")


# --- Safety level classification -------------------------------------------


def test_implemented_capability_safety_levels():
    for name, cap in registry.CAPABILITIES.items():
        assert cap.safety_level == "read-only", f"{name} should be read-only"


def test_planned_capability_safety_levels():
    for name, cap in registry.PLANNED_CAPABILITIES.items():
        if name in ("runtime", "testing"):
            assert cap.safety_level == "mutating", f"{name} should be mutating"
        else:
            assert cap.safety_level == "read-only", f"{name} should be read-only"


def test_classify_capability():
    assert registry.classify_capability("knowledge") == "read-only"
    assert registry.classify_capability("runtime") == "mutating"
    assert registry.classify_capability("testing") == "mutating"


def test_classify_capability_unknown_raises():
    with pytest.raises(ValueError, match="Unknown capability"):
        registry.classify_capability("nonexistent")


def test_safety_level_for_tool_inherits_from_capability():
    assert registry.safety_level_for_tool("quickshell_search") == "read-only"
    assert registry.safety_level_for_tool("quickshell_coding_assistant") == "read-only"


def test_safety_level_for_tool_system_tool_read_only():
    assert registry.safety_level_for_tool("quickshell_stats") == "read-only"


def test_safety_level_for_tool_unknown_raises():
    with pytest.raises(ValueError, match="Unknown tool"):
        registry.safety_level_for_tool("nonexistent_tool")


def test_safety_levels_map_consistent_with_capabilities():
    for name, cap in registry.ALL_CAPABILITIES.items():
        assert registry.SAFETY_LEVELS[name] == cap.safety_level
    assert set(registry.SAFETY_LEVELS) == set(registry.ALL_CAPABILITIES)


# --- Import validity / no circular imports ---------------------------------


def test_every_module_imports_cleanly():
    root = Path(srv.__file__).resolve().parent
    broken = []
    for mod in pkgutil.walk_packages([str(root)], "quickshell_mcp."):
        try:
            importlib.import_module(mod.name)
        except Exception as exc:  # pragma: no cover - only on failure
            broken.append(f"{mod.name}: {type(exc).__name__}: {exc}")
    assert not broken, "modules failed to import:\n" + "\n".join(broken)


# --- Behavior preserved (identity of re-exports) ---------------------------


@pytest.mark.parametrize(
    "name, source_module",
    [
        ("_validate", "validate"),
        ("_check_compatibility", "compat"),
        ("_build_index", "docs"),
        ("_search_everything", "search_all"),
        ("_find_pattern", "find_pattern"),
        ("_generate_component", "generate"),
        ("_migrate", "migrate"),
        ("_explain_error", "explain_error"),
        ("_coding_assistant", "assistant"),
        ("_qt_type_page", "qt_docs"),
        ("_examples_listing", "examples"),
        ("_search_implementations", "implementations"),
    ],
)
def test_reexports_are_the_same_objects(name, source_module):
    source = importlib.import_module(f"quickshell_mcp.sources.{source_module}")
    assert getattr(srv, name) is getattr(source, name)


def test_capability_modules_reexport_source_objects():
    # A capability module must expose the same objects the sources expose, so
    # monkeypatching sources.* in tests still reaches the tool paths.
    val = __import__("quickshell_mcp.capabilities.validation", fromlist=[""])
    src = __import__("quickshell_mcp.sources.validate", fromlist=[""])
    assert srv._validate is val._validate is src._validate
