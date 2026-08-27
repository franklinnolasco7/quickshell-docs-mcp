"""Real-world implementation references (Caelestia / Noctalia shells) via the
GitHub API. These are practical Quickshell configs, NOT API documentation;
when they disagree with quickshell.org or doc.qt.io, the docs are authoritative."""

import json
import re

from .. import utils
from ..caches import _cache_get, _cache_set
from ..config import IMPLEMENTATION_REPOS

_GITHUB_API = "https://api.github.com"

# key, description, query phrases (matched in the query), path fragments
_IMPL_TOPICS: list[tuple[str, str, list[str], list[str]]] = [
    ("bar", "Bar/status-bar implementation", ["bar", "status bar"], ["bar"]),
    ("panel", "Panel/dock implementation", ["panel", "dock"], ["panel", "dock"]),
    (
        "control-center",
        "Control center/dashboard implementation",
        ["control center", "control-center", "dashboard"],
        ["dashboard", "controlcenter", "control-center"],
    ),
    ("notifications", "Notification implementation", ["notification"], ["notif"]),
    ("osd", "OSD/on-screen display implementation", ["osd", "hud", "on-screen"], ["osd"]),
    ("launcher", "App launcher implementation", ["launcher", "run prompt"], ["launcher"]),
    ("lock", "Lock screen implementation", ["lock screen", "lockscreen"], ["lock"]),
    (
        "wallpaper",
        "Wallpaper/background handling",
        ["wallpaper", "background"],
        ["wallpaper", "background"],
    ),
    (
        "workspaces",
        "Workspace/pager widget",
        ["workspace", "pager"],
        ["workspace", "pager"],
    ),
    (
        "windows",
        "Window management/focused-window handling",
        ["window management", "window info", "focused window", "windowlist"],
        ["window"],
    ),
    (
        "screens",
        "Multi-monitor/screen handling",
        ["multi-monitor", "multimonitor", "monitor", "per-screen"],
        ["screen", "multimonitor"],
    ),
    (
        "ipc",
        "IPC usage (IpcHandler / ScriptRunner; Caelestia's hub is modules/nexus)",
        ["ipc", "inter-process"],
        ["ipc", "nexus"],
    ),
    (
        "services",
        "Service patterns wrapping system daemons",
        ["service", "daemon"],
        ["service"],
    ),
    (
        "animations",
        "Animations and transitions",
        ["animation", "transition", "morph", "fluid"],
        ["anim"],
    ),
    (
        "components",
        "Reusable QML components/widgets",
        ["widget", "reusable component", "component composition", "components"],
        ["widget", "components/", "commons/"],
    ),
    ("hyprland", "Hyprland integration", ["hyprland", "hypr"], ["hypr"]),
    ("niri", "Niri integration", ["niri"], ["niri"]),
    (
        "theming",
        "Theming/configuration/appearance",
        ["theme", "theming", "appearance", "colorscheme", "styling", "config"],
        ["theme", "appearance", "colour", "settings"],
    ),
    ("tray", "System tray widget", ["tray"], ["tray"]),
    (
        "audio",
        "Audio/volume implementation (Pipewire, output/input volumes, mixers)",
        ["volume", "audio", "mixer", "sound"],
        ["audio", "pipewire", "players", "volume"],
    ),
    (
        "network",
        "Network/wifi implementation",
        ["wifi", "wi-fi", "network", "ethernet"],
        ["wifi", "network", "nmcli"],
    ),
    ("bluetooth", "Bluetooth implementation", ["bluetooth"], ["bluetooth"]),
    ("brightness", "Brightness/night-light implementation", ["brightness"], ["brightness"]),
    (
        "battery",
        "Battery/power implementation",
        ["battery", "power profile", "upower"],
        ["battery", "upower", "power"],
    ),
    (
        "media",
        "Media-player controls (MPRIS)",
        ["media control", "media player", "mpris", "now playing"],
        ["media", "mpris", "players"],
    ),
]

_IMPL_QUERY_STOPWORDS = {
    "find",
    "show",
    "quickshell",
    "example",
    "examples",
    "implementation",
    "implementations",
    "usage",
    "pattern",
    "patterns",
    "similar",
    "compare",
    "caelestia",
    "noctalia",
    "source",
    "sources",
    "the",
    "and",
    "for",
    "with",
}


def _impl_repo_config(source: str) -> dict[str, str]:
    repo_config = IMPLEMENTATION_REPOS.get(source.strip().lower())
    if repo_config is None:
        raise ValueError(
            f"Unknown source '{source}'. Known sources: {', '.join(IMPLEMENTATION_REPOS)}"
        )
    return repo_config


def _norm_source(source: str) -> str:
    """Validate + normalize a repo-source key ('Caelestia' -> 'caelestia')."""
    normalized = source.strip().lower()
    _impl_repo_config(normalized)
    return normalized


def _impl_branch(repo_config: dict[str, str]) -> str:
    if "branch" in repo_config:
        return repo_config["branch"]
    repo_info = json.loads(
        utils._fetch_raw(f"{_GITHUB_API}/repos/{repo_config['owner']}/{repo_config['repo']}")
    )
    branch = repo_info.get("default_branch")
    if not branch:
        raise RuntimeError(
            f"repo metadata for {repo_config['owner']}/{repo_config['repo']} carries no "
            "default_branch; the GitHub API shape may have changed."
        )
    return branch


def _build_impl_index(source: str, refresh: bool = False) -> dict:
    cache_key = f"impl_index:{source}"
    if not refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached

    repo_config = _impl_repo_config(source)
    full_name = f"{repo_config['owner']}/{repo_config['repo']}"
    branch = _impl_branch(repo_config)
    tree_url = f"{_GITHUB_API}/repos/{full_name}/git/trees/{branch}?recursive=1"
    payload = json.loads(utils._fetch_raw(tree_url))
    if payload.get("truncated"):
        raise RuntimeError(
            f"GitHub returned a truncated tree for {full_name}@{branch}; the repo "
            "outgrew the trees API. Index would be incomplete."
        )

    files = sorted(
        (
            {"path": entry["path"], "size": entry.get("size", 0)}
            for entry in payload.get("tree", [])
            if entry.get("type") == "blob" and entry["path"].endswith(".qml")
        ),
        key=lambda file_entry: file_entry["path"],
    )
    index = {"repo": full_name, "branch": branch, "files": files}
    utils.log.info("built %s implementation index: %d QML file(s)", source, len(files))
    _cache_set(cache_key, index)
    return index


def _impl_component(path: str) -> str:
    parts = path.split("/")
    return "/".join(parts[:2]) if len(parts) > 2 else (parts[0] if len(parts) > 1 else "")


def _impl_topics_for_query(query: str) -> list[tuple[str, str, list[str]]]:
    query_lower = query.lower()
    return [
        (topic_key, topic_description, path_terms)
        for topic_key, topic_description, query_terms, path_terms in _IMPL_TOPICS
        if any(term in query_lower for term in query_terms)
    ]


def _impl_entry_meta(source: str, index: dict, path: str, size: int, topics: list[str]) -> dict:
    descriptions = [
        topic_description
        for topic_key, topic_description, _, _ in _IMPL_TOPICS
        if topic_key in topics
    ]
    return {
        "source": source,
        "kind": "real-world implementation",
        "repo": index["repo"],
        "branch": index["branch"],
        "path": path,
        "component": _impl_component(path),
        "topics": topics,
        "description": "; ".join(descriptions) or "QML implementation reference",
        "size_bytes": size,
        "url": f"https://github.com/{index['repo']}/blob/{index['branch']}/{path}",
    }


def _search_implementations(source: str, query: str, limit: int) -> list[dict]:
    """Rank QML files of a repo against the query via topic aliases plus raw
    token substring matches on the path. Directory-segment matches outrank
    incidental substring matches (modules/bar beats SearchBar.qml)."""
    index = _build_impl_index(source)
    active_topic_path_terms = {
        topic_key: path_terms for topic_key, _, path_terms in _impl_topics_for_query(query)
    }
    tokens = [
        token
        for token in re.split(r"[^a-z0-9]+", query.lower())
        if len(token) > 2 and token not in _IMPL_QUERY_STOPWORDS
    ]

    def segment_bonus(path_lower: str, needle: str) -> int:
        for segment in path_lower.replace("/", " ").split():
            if segment == needle:
                return 3
            if segment.startswith(needle):
                return 1
        return 0

    scored: list[tuple[int, str, list[str], int]] = []
    for file_entry in index["files"]:
        path_lower = file_entry["path"].lower()
        hit_topics = [
            topic_key
            for topic_key, path_terms in active_topic_path_terms.items()
            if any(fragment in path_lower for fragment in path_terms)
        ]
        score = 8 * len(hit_topics)
        score += sum(
            2 * segment_bonus(path_lower, token) + (1 if token in path_lower else 0)
            for token in tokens
        )
        if score:
            scored.append((-score, file_entry["path"], hit_topics, file_entry["size"]))

    if not scored and not tokens:
        # Broad query on one shell (e.g. "similar implementation in Noctalia"):
        # fall back to a structural tour instead of an empty result.
        seen_components: set[str] = set()
        for file_entry in index["files"]:
            component = _impl_component(file_entry["path"])
            if component in seen_components:
                continue
            seen_components.add(component)
            scored.append((0, file_entry["path"], [], file_entry["size"]))
            if len(scored) >= limit:
                break

    scored.sort(key=lambda scored_entry: (scored_entry[0], scored_entry[1]))
    return [
        _impl_entry_meta(source, index, path, size, sorted(topics))
        for _, path, topics, size in scored[:limit]
    ]


def _impl_file(source: str, path: str, find: str | None, max_chars: int) -> str:
    source = _norm_source(source)
    index = _build_impl_index(source)
    path = path.strip("/")
    matched_file = next(
        (file_entry for file_entry in index["files"] if file_entry["path"] == path), None
    )
    if matched_file is None:
        directory = path.rsplit("/", 1)[0] if "/" in path else ""
        siblings = [
            file_entry["path"]
            for file_entry in index["files"]
            if file_entry["path"].startswith(f"{directory}/")
        ]
        close = [p for p in siblings if path.lower() in p.lower()] or siblings
        raise ValueError(
            f"No file '{path}' indexed in {index['repo']}@{index['branch']}. "
            f"Did you mean one of: {close[:20]}"
        )

    blob_url = f"https://github.com/{index['repo']}/blob/{index['branch']}/{path}"
    raw_url = f"https://raw.githubusercontent.com/{index['repo']}/{index['branch']}/{path}"
    text = utils._fetch_raw(raw_url)

    section_note = ""
    if find:
        find_terms = {term for term in re.split(r"[^a-z0-9]+", find.lower()) if term}
        lines = text.splitlines()
        best_line_index, best_hit_count = 0, 0
        window_size = 40
        for line_index, line in enumerate(lines):
            hits = sum(1 for term in find_terms if term in line.lower())
            if hits > best_hit_count:
                best_line_index, best_hit_count = line_index, hits
        window_start = max(0, best_line_index - window_size // 4)
        text = "\n".join(lines[window_start : window_start + window_size])
        section_note = (
            f" (showing lines {window_start + 1}-"
            f"{min(len(lines), window_start + window_size)} around '{find}'; "
            f"full file at {blob_url})"
        )
    elif len(text) > max_chars:
        truncated = text[:max_chars]
        last_newline = truncated.rfind("\n")
        text = truncated[:last_newline] if last_newline > 0 else truncated
        section_note = f" ...[truncated at {max_chars} chars; full file at {blob_url}]"

    meta = _impl_entry_meta(source, index, path, matched_file["size"], [])
    header = (
        f"*Implementation reference: {meta['kind']} from {meta['repo']} "
        f"(branch {meta['branch']}), path `{meta['path']}`; not official "
        f"documentation.* *Source: [{blob_url}]({blob_url})*{section_note}\n\n"
    )
    return header + text
