#!/usr/bin/env python3
"""End-to-end smoke test: drives the server over stdio like a real MCP client.

Usage: .venv/bin/python scripts/smoke_test.py [server-command...]

Keeps stdin OPEN while awaiting each response; closing the pipe early makes
the mcp stdio transport abort in-flight requests, which looks like a hang but
isn't. Exits 0 only if every check passes.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading

DEFAULT_SERVER = [".venv/bin/quickshell-mcp"]
TIMEOUT = 90


class Client:
    def __init__(self, argv: list[str]):
        self.proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        self._lock = threading.Lock()
        self._next_id = 0

    def call(self, method: str, params: dict | None = None, notify: bool = False) -> dict | None:
        msg: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        out = json.dumps(msg) + "\n"
        with self._lock:
            if not notify:
                self._next_id += 1
                msg["id"] = self._next_id
                out = json.dumps(msg) + "\n"
            assert self.proc.stdin is not None
            self.proc.stdin.write(out)
            self.proc.stdin.flush()
            if notify:
                return None
            return self._read_response(msg["id"])

    def _read_response(self, want_id: int, remaining_time: float = TIMEOUT) -> dict:
        import time

        deadline = time.monotonic() + remaining_time
        assert self.proc.stdout is not None
        while time.monotonic() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("server closed stdout before responding")
            resp = json.loads(line)
            if resp.get("id") == want_id:
                return resp
        raise TimeoutError(f"no response for request id {want_id} within {TIMEOUT}s")


def _tool_json(client: Client, name: str, arguments: dict | None = None) -> dict:
    resp = client.call("tools/call", {"name": name, "arguments": arguments or {}})
    return json.loads(resp["result"]["content"][0]["text"])


def main() -> int:
    argv = sys.argv[1:] or DEFAULT_SERVER
    c = Client(argv)

    c.call(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "smoke", "version": "0"},
        },
    )
    c.call("notifications/initialized", notify=True)
    print(f"[ok] server started: {argv}")

    tools = c.call("tools/list")
    names = {t["name"] for t in tools["result"]["tools"]}
    expected = {
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
    }
    missing = expected - names
    assert not missing, f"missing tools: {missing}"
    print(f"[ok] all {len(expected)} expected tools registered")

    versions = _tool_json(c, "quickshell_list_versions")
    assert versions["all_versions"], "version discovery returned nothing"
    print(f"[ok] latest version: {versions['latest']} ({len(versions['all_versions'])} published)")

    search = _tool_json(c, "quickshell_search", {"query": "pam"})
    assert search["namespace_matches"] == ["Quickshell.Services.Pam"], search["namespace_matches"]
    print("[ok] search 'pam' -> Quickshell.Services.Pam")

    search_all = _tool_json(c, "quickshell_search_all", {"query": "volume OSD"})
    assert isinstance(search_all.get("section_order"), list)
    assert isinstance(search_all.get("results"), dict)
    print(f"[ok] search_all sections: {search_all['section_order']}")

    find_pattern = _tool_json(c, "quickshell_find_pattern", {"query": "volume OSD"})
    assert isinstance(find_pattern.get("implementations"), list)
    assert isinstance(find_pattern.get("cross_project_patterns"), list)
    print(
        f"[ok] find_pattern interpreted as: "
        f"{[entry['pattern'] for entry in find_pattern['interpreted_as']]}"
    )

    impl_search = _tool_json(
        c, "quickshell_search_implementations", {"query": "volume", "source": "dots-hyprland"}
    )
    dots_entries = impl_search["results"].get("dots-hyprland") or []
    assert dots_entries, "dots-hyprland should return volume/audio paths"
    assert all("dots/.config" not in entry["path"] for entry in dots_entries), (
        "qml_root must be stripped from dots-hyprland paths"
    )
    print(f"[ok] dots-hyprland search: {len(dots_entries)} volume path(s)")

    page = c.call(
        "tools/call",
        {
            "name": "quickshell_get_type",
            "arguments": {"type_name": "PamContext", "namespace": "Quickshell.Services.Pam"},
        },
    )
    text = page["result"]["content"][0]["text"]
    assert "*Source:" in text and "PamContext" in text
    print(f"[ok] PamContext page fetched ({len(text)} chars, cited)")

    stats = _tool_json(c, "quickshell_stats")
    assert stats["tool_calls"].get("quickshell_stats", 0) >= 1
    print(f"[ok] stats tracked: {stats['tool_calls']}")

    validate = _tool_json(c, "quickshell_validate_qml", {"source": "PanelWindow { foo: 1 }"})
    assert isinstance(validate.get("diagnostics"), list)
    assert isinstance(validate.get("summary"), dict)
    assert "version" in validate
    print(f"[ok] validate_qml returned {len(validate['diagnostics'])} diagnostic(s)")

    compat = _tool_json(
        c,
        "quickshell_check_compatibility",
        {"api": "PanelWindow.exclusiveZone", "version": "latest"},
    )
    assert compat["compatibility"] in ("compatible", "uncertain")
    assert compat["target_version"] == versions["latest"]
    print(
        f"[ok] check_compatibility: {compat['compatibility']} for {compat['detected_api']['type']}"
    )

    generated = _tool_json(c, "quickshell_generate_component", {"description": "volume OSD"})
    assert isinstance(generated.get("component"), dict)
    assert generated["component"]["qml"].strip()
    assert generated["verification"]["verdict"] in ("verified", "unverified")
    assert isinstance(generated.get("validation", {}).get("summary"), dict)
    assert generated.get("verified_surface", {}).get("types") is not None
    print(
        f"[ok] generate_component: {len(generated['component']['qml'])} chars, "
        f"verdict={generated['verification']['verdict']}, "
        f"{len(generated['verified_surface']['types'])} type(s) in surface"
    )

    migrate = _tool_json(
        c,
        "quickshell_migrate",
        {
            "code": 'Quickshell { shellRoot: "/tmp" }',
            "from_version": "v0.1.0",
            "to_version": versions["latest"],
        },
    )
    assert isinstance(migrate.get("issues"), list)
    assert "summary" in migrate and migrate["from_version"] == "v0.1.0"
    print(
        f"[ok] migrate returned summary: {migrate['summary']['verdict']} "
        f"({len(migrate['issues'])} issue(s))"
    )

    c.proc.terminate()
    print("\nALL SMOKE CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
