"""Managed Quickshell runtime sessions: launch, track, inspect, and stop
isolated ``qs`` processes backed by a runtime profile.

Every session is tracked in the global ``_SESSION_REGISTRY`` by a unique
session id. Lifecycle operations (start/stop/reset) are mutating; status,
logs, and ping are read-only. The session ring buffer keeps the last
:data:`_LOG_BUF_SIZE` log lines.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .runtime_profile import _RuntimeProfile

_LOG_BUF_SIZE = 10_000
_POLL_INTERVAL = 0.1
_KILL_TIMEOUT = 5.0

_SESSION_REGISTRY: dict[str, _RuntimeSession] = {}

# Status values
STATUS_STARTING = "starting"
STATUS_RUNNING = "running"
STATUS_EXITED = "exited"
STATUS_KILLED = "killed"
STATUS_ERROR = "error"


def _qs_binary() -> str:
    """Path to the ``qs`` executable, or raises ``FileNotFoundError``."""
    path = shutil.which("qs")
    if path is None:
        raise FileNotFoundError(
            "qs binary not found on PATH; install Quickshell to use runtime tools"
        )
    return path


@dataclass
class _LogLine:
    stream: str  # "stdout" | "stderr"
    line: str
    ts: float = field(default_factory=time.time)


@dataclass
class _RuntimeSession:
    session_id: str
    profile: _RuntimeProfile
    status: str = STATUS_STARTING
    pid: int | None = None
    start_time: float = field(default_factory=time.time)
    exit_code: int | None = None
    kind: str = "managed"  # "managed" | "detached"
    log_buffer: list[_LogLine] = field(default_factory=list)
    _process: subprocess.Popen | None = None

    def append_log(self, stream: str, line: str) -> None:
        self.log_buffer.append(_LogLine(stream=stream, line=line))
        if len(self.log_buffer) > _LOG_BUF_SIZE:
            self.log_buffer = self.log_buffer[-_LOG_BUF_SIZE:]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "pid": self.pid,
            "start_time": self.start_time,
            "uptime": (
                round(time.time() - self.start_time, 1) if self.status == STATUS_RUNNING else None
            ),
            "exit_code": self.exit_code,
            "kind": self.kind,
            "profile": {
                "project_root": self.profile.project_root,
                "entrypoint": self.profile.entrypoint,
                "compositor": self.profile.compositor,
            },
        }


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------


def _start_session(profile: _RuntimeProfile) -> _RuntimeSession:
    """Launch a managed Quickshell session from *profile* and register it.

    Returns a session with status ``running`` on success, or ``error`` if
    the binary is missing or the process fails to start.
    """
    session_id = uuid.uuid4().hex[:12]
    try:
        entrypoint = profile.resolved_entrypoint()
        env = profile.isolated_environment(session_id)
        binary = _qs_binary()
        cmd = [binary, "-p", entrypoint, "--no-daemonize"] + profile.arguments
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            start_new_session=True,
            text=True,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError, ValueError) as exc:
        session = _RuntimeSession(
            session_id=session_id,
            profile=profile,
            status=STATUS_ERROR,
            exit_code=-1,
        )
        session.append_log("stderr", f"Failed to launch: {exc}")
        _SESSION_REGISTRY[session_id] = session
        return session

    session = _RuntimeSession(
        session_id=session_id,
        profile=profile,
        status=STATUS_RUNNING,
        pid=proc.pid,
        _process=proc,
    )
    _SESSION_REGISTRY[session_id] = session
    return session


def _stop_session(session: _RuntimeSession, timeout: float = _KILL_TIMEOUT) -> None:
    """Stop a managed session gracefully (SIGTERM → timeout → SIGKILL).

    Handles already-exited and orphaned processes safely.
    """
    if session.status in (STATUS_EXITED, STATUS_KILLED, STATUS_ERROR):
        return
    pid = session.pid
    if pid is None:
        session.status = STATUS_ERROR
        return

    try:
        # Send SIGTERM to the whole process group (negative pid).
        os.killpg(pid, signal.SIGTERM)
        waited = _wait_with_timeout(pid, timeout)
        if waited is None:
            os.killpg(pid, signal.SIGKILL)
            _wait_with_timeout(pid, 2.0)
            session.status = STATUS_KILLED
        else:
            session.status = STATUS_EXITED
            session.exit_code = waited
    except ProcessLookupError:
        session.status = STATUS_EXITED
        session.exit_code = 0
    except PermissionError:
        session.status = STATUS_ERROR

    _drain_logs(session)
    session._process = None


def _reset_session(session: _RuntimeSession) -> _RuntimeSession:
    """Stop the existing session and start a fresh one with the same profile.

    A new session id is allocated; the old session is removed from the
    registry. Stale processes, temp files, and sockets are cleaned up.
    """
    _stop_session(session)
    _cleanup_temp(session)
    old_id = session.session_id
    _SESSION_REGISTRY.pop(old_id, None)
    return _start_session(session.profile)


def _status_session(session: _RuntimeSession) -> dict[str, Any]:
    """Return structured status for a session, refreshing the process state."""
    _refresh_status(session)
    return session.to_dict()


def _logs(
    session: _RuntimeSession,
    *,
    stream: str | None = None,
    severity: str | None = None,
    text: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return structured log lines from the session's ring buffer."""
    lines = list(session.log_buffer)
    if stream:
        lines = [line for line in lines if line.stream == stream]
    if text:
        text_lower = text.lower()
        lines = [line for line in lines if text_lower in line.line.lower()]
    return [{"ts": line.ts, "stream": line.stream, "line": line.line} for line in lines[-limit:]]


def _ping(session: _RuntimeSession) -> dict[str, str]:
    """Lightweight health check. Returns one of:

    * ``process_running`` — the process is alive
    * ``exited`` — the process has exited
    * ``unhealthy`` — the session is in an error state
    """
    _refresh_status(session)
    if session.status == STATUS_RUNNING:
        return {"status": "process_running"}
    if session.status in (STATUS_EXITED, STATUS_KILLED):
        return {"status": "exited", "exit_code": str(session.exit_code)}
    return {"status": "unhealthy", "detail": session.status}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _wait_with_timeout(pid: int, timeout: float) -> int | None:
    """Wait for *pid* to exit, returning the exit code or None on timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            pid_out, status = os.waitpid(pid, os.WNOHANG)
            if pid_out == pid:
                if os.WIFEXITED(status):
                    return os.WEXITSTATUS(status)
                if os.WIFSIGNALED(status):
                    return -os.WTERMSIG(status)
                return status
        except ChildProcessError:
            return None
        time.sleep(_POLL_INTERVAL)
    return None


def _drain_logs(session: _RuntimeSession) -> None:
    """Read any remaining stdout/stderr from the finished process."""
    proc = session._process
    if proc is None:
        return
    for stream_name in ("stdout", "stderr"):
        handle = getattr(proc, stream_name, None)
        if handle is None:
            continue
        for line in handle.readlines():
            session.append_log(stream_name, line.rstrip("\n"))


def _refresh_status(session: _RuntimeSession) -> None:
    """Update session status from the actual process state."""
    if session.status in (STATUS_EXITED, STATUS_KILLED, STATUS_ERROR):
        return
    pid = session.pid
    if pid is None:
        session.status = STATUS_ERROR
        return
    try:
        os.kill(pid, 0)
        session.status = STATUS_RUNNING
    except ProcessLookupError:
        _drain_logs(session)
        session.status = STATUS_EXITED
        session.exit_code = 0
    except PermissionError:
        session.status = STATUS_ERROR


def _cleanup_temp(session: _RuntimeSession) -> None:
    """Remove the isolated temp directories for a session."""
    import tempfile

    for var in ("XDG_CONFIG_HOME", "XDG_CACHE_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        env = session.profile.environment.get(var) or ""
        if env.startswith(tempfile.gettempdir()):
            with contextlib.suppress(OSError):
                Path(env).rmdir()  # only removes empty dirs, not recursive
