"""Project-level discovery: a reusable ``_ProjectContext`` that gives MCP tools
a consistent representation of the Quickshell project they are analyzing.

Consumer pattern::

    ctx = _build_project_context("/path/to/shell")
    info = ctx.discover({"qml_files", "imports", "compositor"})
    # info = {"qml_files": [...], "imports": [...], "compositor": ["Hyprland"], ...}
    # ctx.detection_status("qml_files")  -> "detected"
    # ctx.detection_status("compositor") -> "inferred"

Every field is lazily computed on first request and cached for the lifetime of
the ``_ProjectContext`` instance. Expensive cross-file scans are also cached
in the shared in-memory cache (``_cache_get``/``_cache_set``, 30-minute TTL).

Fields are one of three statuses:

* **detected** — directly observed in the filesystem
* **inferred** — derived from detected data
* **unknown** — no data could be found

Available fields (all lazy): ``qml_files``, ``js_files``, ``entrypoints``,
``imports``, ``quickshell_modules``, ``quickshell_version``, ``qt_version``,
``compositor``, ``config_paths``, ``dependencies``, ``conventions``,
``components``, ``services``, ``runtime_dependencies``, ``environment``.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path

from ..caches import _cache_get, _cache_set
from .validate import _parse_structure, _tokenize

# Root QML object base names that constitute a project entrypoint (a
# top-level window the shell runtime instantiates).
_ENTRYPOINT_TYPES = frozenset({"Window", "PanelWindow", "PopupWindow", "ShellRoot"})

# Quickshell namespaces that are core infrastructure rather than compositor
# integration modules. Anything under ``Quickshell.<X>`` (single dot) that is
# NOT in this set is treated as an inferred compositor integration. May need
# updating as Quickshell adds new core namespaces.
_QUICKSHELL_CORE = frozenset(
    {
        "Bluetooth",
        "DBusMenu",
        "Io",
        "Networking",
        "Services",
        "Wayland",
        "Widgets",
        "WindowManager",
    }
)

# Config file extensions to scan for at the project root.
_CONFIG_EXTENSIONS = frozenset({".json", ".toml", ".yaml", ".yml", ".conf", ".ini"})

# Directory names that hold reusable UI parts.
_COMPONENT_DIRS = frozenset({"components", "widgets"})

# QML types that wire the shell to external runtime infrastructure.  Only
# types named exactly like these count; anything else is not a runtime hook.
_RUNTIME_QML_TYPES = frozenset(
    {"Process", "IpcHandler", "Socket", "SocketServer", "DataStream", "StdioCollector", "FileView"}
)

# Config keywords that hint at external runtime dependencies.
_CONFIG_DEP_KEYWORDS = (
    "command",
    "exec",
    "binary",
    "dbus",
    "socket",
    "pipewire",
    "systemctl",
    "hyprctl",
    "wayland",
)

_ENV_VAR_RE = re.compile(
    r"process\.env\.([A-Za-z_][A-Za-z0-9_]*)"
    r"|process\.env\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]"
)

_ALL_FIELDS = frozenset(
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
)

_CACHE_PREFIX = "project:"


def _is_quickshell_module(module: str) -> bool:
    return module == "Quickshell" or module.startswith("Quickshell.")


def _is_qt_module(module: str) -> bool:
    return module.startswith("Qt") and module != "Qt"


def _is_service_module(module: str) -> bool:
    return module.startswith("Quickshell.Services.")


def _find_env_vars(source: str) -> set[str]:
    names: set[str] = set()
    for match in _ENV_VAR_RE.finditer(source):
        name = match.group(1) or match.group(2)
        if name:
            names.add(name)
    return names


@dataclass
class _ProjectContext:
    """Lazy project-metadata container.

    Do not instantiate directly — use ``_build_project_context``.
    """

    root: Path
    _values: dict = field(default_factory=dict, repr=False)
    _status: dict = field(default_factory=dict, repr=False)

    def discover(self, needs: Collection[str]) -> dict[str, object]:
        """Return the requested fields, computing each lazily on first access.

        Unknown field names raise ``ValueError``.
        """
        unknown = set(needs) - _ALL_FIELDS
        if unknown:
            raise ValueError(f"Unknown context field(s): {sorted(unknown)}")
        for name in needs:
            if name not in self._values:
                self._compute(name)
        return {name: self._values[name] for name in needs}

    def detection_status(self, name: str) -> str:
        """Return ``"detected"``, ``"inferred"``, or ``"unknown"`` for *name*."""
        if name not in self._values:
            self._compute(name)
        return self._status.get(name, "unknown")

    def _compute(self, name: str) -> None:
        method = getattr(self, f"_discover_{name}", None)
        if method is None:
            raise ValueError(f"No discovery method for {name!r}")
        method()

    def _set(self, name: str, value: object, status: str = "detected") -> None:
        self._values[name] = value
        self._status[name] = status

    def _set_inferred(self, name: str, value: object) -> None:
        # "unknown" for empty lists, None strings, or falsy scalars.
        is_empty = value is None or (isinstance(value, (list, dict)) and not value)
        status = "unknown" if is_empty else "inferred"
        self._values[name] = value
        self._status[name] = status

    def _scan(self) -> dict:
        """Expensive scan: walk the tree, parse every QML file, collect raw
        facts. Result is cached in the shared 30-minute cache."""
        cache_key = f"{_CACHE_PREFIX}{self.root}"
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

        qml_files: list[str] = []
        js_files: list[str] = []
        imports: list[dict] = []
        entrypoints: list[str] = []
        config_paths: list[str] = []
        objects: list[dict] = []
        env_vars: set[str] = set()
        config_deps: list[dict] = []

        for path in self.root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix == ".qml":
                qml_files.append(str(path))
            elif path.suffix == ".js":
                js_files.append(str(path))
            elif path.suffix in _CONFIG_EXTENSIONS and path.parent == self.root:
                config_paths.append(str(path))

        for str_path in qml_files:
            try:
                source = Path(str_path).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            env_vars.update(_find_env_vars(source))
            parsed = _parse_structure(_tokenize(source))
            for imp in parsed.imports:
                imports.append(
                    {
                        "module": imp.module,
                        "alias": imp.alias,
                        "version": imp.version,
                        "file": str_path,
                        "line": imp.line,
                        "col": imp.col,
                    }
                )
            for obj in parsed.objects:
                objects.append({"base_name": obj.base_name, "file": str_path})
            if parsed.objects and parsed.objects[0].base_name in _ENTRYPOINT_TYPES:
                entrypoints.append(str_path)

        for str_path in config_paths:
            try:
                text = Path(str_path).read_text(encoding="utf-8").lower()
            except (OSError, UnicodeDecodeError):
                continue
            for keyword in _CONFIG_DEP_KEYWORDS:
                if keyword in text:
                    config_deps.append({"keyword": keyword, "file": str_path})

        result = {
            "qml_files": qml_files,
            "js_files": js_files,
            "imports": imports,
            "entrypoints": entrypoints,
            "config_paths": config_paths,
            "objects": objects,
            "env_vars": sorted(env_vars),
            "config_deps": config_deps,
        }
        _cache_set(cache_key, result)
        return result

    def _discover_qml_files(self) -> None:
        self._set("qml_files", self._scan()["qml_files"])

    def _discover_js_files(self) -> None:
        self._set("js_files", self._scan()["js_files"])

    def _discover_config_paths(self) -> None:
        self._set("config_paths", self._scan()["config_paths"])

    def _discover_entrypoints(self) -> None:
        self._set("entrypoints", self._scan()["entrypoints"])

    def _discover_imports(self) -> None:
        self._set("imports", self._scan()["imports"])

    def _discover_dependencies(self) -> None:
        modules = sorted({imp["module"] for imp in self._scan()["imports"]})
        self._set("dependencies", modules)

    def _discover_quickshell_modules(self) -> None:
        modules = sorted(
            {
                imp["module"]
                for imp in self._scan()["imports"]
                if _is_quickshell_module(imp["module"])
            }
        )
        self._set("quickshell_modules", modules, status="detected" if modules else "unknown")

    def _discover_quickshell_version(self) -> None:
        # Lexical only: report the version the project itself declares on
        # Quickshell imports (e.g. "0.3" from `import Quickshell 0.3`).
        # Nothing is validated against the live site here, so discovery stays
        # offline and deterministic; callers map it to a published doc version
        # with _resolve_version / _resolve_version_hint when they need one.
        versions = sorted(
            {
                imp["version"]
                for imp in self._scan()["imports"]
                if _is_quickshell_module(imp["module"]) and imp.get("version")
            }
        )
        self._set_inferred("quickshell_version", versions[0] if versions else None)

    def _discover_qt_version(self) -> None:
        versions = sorted(
            {
                imp["version"]
                for imp in self._scan()["imports"]
                if _is_qt_module(imp["module"]) and imp.get("version")
            }
        )
        self._set_inferred("qt_version", versions[0] if versions else None)

    def _discover_compositor(self) -> None:
        segments: set[str] = set()
        for imp in self._scan()["imports"]:
            mod = imp["module"]
            if not mod.startswith("Quickshell."):
                continue
            second = mod.split(".")[1]
            if second not in _QUICKSHELL_CORE:
                segments.add(second)
        self._set_inferred("compositor", sorted(segments))

    def _discover_components(self) -> None:
        info = self._scan()
        components = [
            {"path": str_path, "name": Path(str_path).stem}
            for str_path in info["qml_files"]
            if any(segment in _COMPONENT_DIRS for segment in Path(str_path).parts)
        ]
        self._set("components", components, status="detected" if components else "unknown")

    def _discover_services(self) -> None:
        info = self._scan()
        modules = sorted(
            {imp["module"] for imp in info["imports"] if _is_service_module(imp["module"])}
        )
        objects = sorted(
            {obj["base_name"] for obj in info["objects"] if obj["base_name"].endswith("Service")}
        )
        value = {"modules": modules, "objects": objects}
        if modules:
            status = "detected"
        elif objects:
            status = "inferred"
        else:
            status = "unknown"
        self._set("services", value, status=status)

    def _discover_runtime_dependencies(self) -> None:
        info = self._scan()
        qml_types = sorted(
            {obj["base_name"] for obj in info["objects"] if obj["base_name"] in _RUNTIME_QML_TYPES}
        )
        config_keywords = sorted({dep["keyword"] for dep in info["config_deps"]})
        value = {"qml_types": qml_types, "config": config_keywords}
        if qml_types:
            status = "detected"
        elif config_keywords:
            status = "inferred"
        else:
            status = "unknown"
        self._set("runtime_dependencies", value, status=status)

    def _discover_environment(self) -> None:
        info = self._scan()
        self._set_inferred("environment", info["env_vars"])

    def _discover_conventions(self) -> None:
        info = self._scan()
        conventions: dict[str, object] = {}

        qml_names = [Path(p).stem for p in info["qml_files"]]
        camel_count = sum(1 for n in qml_names if re.match(r"^[a-z]+[A-Z]", n))
        snake_count = sum(1 for n in qml_names if "_" in n)
        if camel_count > snake_count:
            conventions["file_naming"] = "camelCase"
        elif snake_count > camel_count:
            conventions["file_naming"] = "snake_case"
        elif qml_names:
            conventions["file_naming"] = "mixed"
        else:
            conventions["file_naming"] = "unknown"

        entry_stems = {Path(p).stem for p in info["entrypoints"]}
        if "main" in entry_stems:
            conventions["entrypoint_naming"] = "main.qml"
        elif "config" in entry_stems:
            conventions["entrypoint_naming"] = "config.qml"
        elif "shell" in entry_stems:
            conventions["entrypoint_naming"] = "shell.qml"
        elif entry_stems:
            conventions["entrypoint_naming"] = f"custom ({', '.join(sorted(entry_stems))})"
        else:
            conventions["entrypoint_naming"] = "unknown"

        if info["qml_files"]:
            parents = {Path(p).parent for p in info["qml_files"]}
            conventions["directory_layout"] = "nested" if len(parents) > 1 else "flat"
            component_dirs = [
                name
                for name in ("components", "modules", "widgets")
                if any(name in str(p) for p in parents)
            ]
            if component_dirs:
                conventions["component_dirs"] = component_dirs
        else:
            conventions["directory_layout"] = "unknown"

        self._set_inferred("conventions", conventions)


def _build_project_context(project_root: str) -> _ProjectContext:
    """Build a ``_ProjectContext`` from a root directory.

    Raises ``ValueError`` if *project_root* does not exist or is not a
    directory.
    """
    path = Path(project_root).resolve()
    if not path.exists():
        raise ValueError(f"Project root does not exist: {project_root}")
    if not path.is_dir():
        raise ValueError(f"Project root is not a directory: {project_root}")
    return _ProjectContext(root=path)
