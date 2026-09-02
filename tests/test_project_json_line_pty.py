from __future__ import annotations

import errno
import json
import os
import select
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

from atready.project import project_from_path

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "evals" / "fixtures"
READY = b"ATREADY_PROJECT_JSON_LINE_READY"


def _read_until(fd: int, *, needle: bytes, timeout: float) -> bytes:
    captured = bytearray()
    deadline = time.monotonic() + timeout
    while needle not in captured:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"timed out waiting for {needle!r}; received {bytes(captured)!r}")
        readable, _, _ = select.select([fd], [], [], remaining)
        if not readable:
            continue
        try:
            chunk = os.read(fd, 65_536)
        except OSError as exc:
            if exc.errno == errno.EIO:
                break
            raise
        if not chunk:
            break
        captured.extend(chunk)
    return bytes(captured)


def _drain(fd: int, *, timeout: float = 0.2) -> bytes:
    captured = bytearray()
    while True:
        readable, _, _ = select.select([fd], [], [], timeout)
        if not readable:
            return bytes(captured)
        try:
            chunk = os.read(fd, 65_536)
        except OSError as exc:
            if exc.errno == errno.EIO:
                return bytes(captured)
            raise
        if not chunk:
            return bytes(captured)
        captured.extend(chunk)


def _write_all(fd: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(fd, remaining)
        remaining = remaining[written:]


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "openpty"),
    reason="protected terminal transport requires a POSIX PTY",
)
def test_project_json_line_process_discards_trailing_terminal_input(tmp_path: Path) -> None:
    """Exercise the same readiness/write sequence used by an agent terminal session."""

    import termios

    project = project_from_path(FIXTURES / "project-godot.yaml")
    project_payload = json.dumps(
        project.model_dump(mode="json"), separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    executed = tmp_path / "trailing-input-executed"
    trailing_command = f"touch {shlex.quote(str(executed))}\n".encode()

    master_fd, slave_fd = os.openpty()
    original = termios.tcgetattr(slave_fd)
    process: subprocess.Popen[bytes] | None = None
    try:
        # `exec` removes the intermediary shell before any private input is sent. Keeping the
        # parent's slave descriptor open lets this test also inspect the terminal input queue.
        process = subprocess.Popen(  # noqa: S603 - fixed shell and current test interpreter
            [
                "/bin/sh",
                "-c",
                'exec "$@"',
                "atready-pty-test",
                sys.executable,
                "-m",
                "atready.cli",
                "route",
                "--project-json-line",
                "--inventory",
                str(FIXTURES / "inventory.yaml"),
                "--allow-demo",
                "--format",
                "agent-summary",
                "--width",
                "120",
            ],
            cwd=ROOT,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
        )

        transcript = _read_until(master_fd, needle=READY, timeout=5)
        assert READY in transcript

        _write_all(master_fd, project_payload + b"\n" + trailing_command)
        process.wait(timeout=10)
        transcript += _drain(master_fd)

        assert process.returncode == 0, transcript.decode("utf-8", errors="replace")
        assert b"Goal: Build and review a deterministic battle-report feature." in transcript
        assert b"Route: 3 steps assigned." in transcript
        assert b"No routed project resources were contacted or run." in transcript

        # Neither the accepted record nor later shell-looking bytes may be reflected into the
        # captured console. The later bytes must also be absent from the restored input queue.
        assert project_payload not in transcript
        assert trailing_command.rstrip(b"\n") not in transcript
        assert not executed.exists()

        restored = termios.tcgetattr(slave_fd)
        assert restored == original
        os.set_blocking(slave_fd, False)
        try:
            queued = os.read(slave_fd, 65_536)
        except BlockingIOError:
            queued = b""
        assert queued == b""
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        os.close(master_fd)
        os.close(slave_fd)
