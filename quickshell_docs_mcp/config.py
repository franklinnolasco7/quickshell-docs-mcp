"""Upstream locations, identities, and tuning constants for every source."""

BASE = "https://quickshell.org"
QT_DOCS_BASE = "https://doc.qt.io/qt-6"
EXAMPLES_REPO_WEB = "https://git.outfoxxed.me/quickshell/quickshell-examples"
EXAMPLES_REPO_API = "https://git.outfoxxed.me/api/v1/repos/quickshell/quickshell-examples"

USER_AGENT = "quickshell-docs-mcp/0.1 (+https://github.com/; contact: local use)"

_CACHE_TTL = 60 * 30  # 30 minutes; long enough to be polite, short enough to track site updates

_RETRY_ATTEMPTS = 3

# Version numbers are vX.Y.Z today but tolerate prerelease suffixes (v0.4.0-rc1)
# so "latest" doesn't silently lag behind when the site publishes one.
_VERSION_NUM = r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)*"

# doc.qt.io hosts its page body inside <article class="b-sidebar__content...">,
# so the generic [class*=sidebar] strip rule would delete the actual content.
_STRIP_SELECTORS = [
    "nav",
    "header",
    "footer",
    "aside",
    "script",
    "style",
    "[class*=sidebar]",
    "[class*=toc]",
    "[class*=search]",
    "[class*=version-switch]",
    "[class*=breadcrumb]",
]
_QT_STRIP_SELECTORS = ["script", "style"]

IMPLEMENTATION_REPOS: dict[str, dict[str, str]] = {
    "caelestia": {"owner": "caelestia-dots", "repo": "shell"},
    # The Quickshell shell lives on the legacy-v4 branch; noctalia's main
    # branch moved to a C++ compositor project, so the ref is pinned here.
    "noctalia": {"owner": "noctalia-dev", "repo": "noctalia", "branch": "legacy-v4"},
}
