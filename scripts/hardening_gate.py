#!/usr/bin/env python3
"""Run AtReady's bounded provider-free hardening lanes and emit one receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT_SECONDS = 420
MAX_WHEEL_BYTES = 64 * 1_048_576


def _wheel_sha256(path: Path) -> str:
    if path.suffix != ".whl":
        raise RuntimeError(f"expected one local wheel file: {path}")
    try:
        lexical = path.lstat()
    except OSError as exc:
        raise RuntimeError(f"cannot inspect local wheel file: {path}") from exc
    if stat.S_ISLNK(lexical.st_mode):
        raise RuntimeError(f"refusing symlinked local wheel file: {path}")
    flags = os.O_RDONLY
    for name in ("O_BINARY", "O_CLOEXEC", "O_NOFOLLOW"):
        flags |= int(getattr(os, name, 0))
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RuntimeError(f"cannot open local wheel file safely: {path}") from exc
    digest = hashlib.sha256()
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_nlink != 1
            or opened.st_size > MAX_WHEEL_BYTES
            or (lexical.st_dev, lexical.st_ino) != (opened.st_dev, opened.st_ino)
        ):
            raise RuntimeError(f"expected one bounded regular local wheel file: {path}")
        for chunk in iter(lambda: os.read(descriptor, 1_048_576), b""):
            digest.update(chunk)
    except OSError as exc:
        raise RuntimeError(f"cannot read local wheel file: {path}") from exc
    finally:
        os.close(descriptor)
    return digest.hexdigest()


def _run(command: list[str], *, subject: str) -> dict[str, Any]:
    environment = os.environ.copy()
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONPATH"] = str(ROOT / "src")
    completed = subprocess.run(  # noqa: S603
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=TIMEOUT_SECONDS,
        env=environment,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"{subject} failed with exit {completed.returncode}: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{subject} did not return JSON") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{subject} did not return a JSON object")
    return value


def run(*, wheel: Path | None = None) -> dict[str, Any]:
    conversation = _run(
        [sys.executable, str(ROOT / "evals/conversation_hardening/score.py")],
        subject="conversation hardening",
    )
    install_command = [
        sys.executable,
        str(ROOT / "scripts/clean_first_use.py"),
        "--install",
        "source" if wheel is None else "all",
    ]
    if wheel is not None:
        wheel_sha256 = _wheel_sha256(wheel)
        install_command.extend(
            [
                "--wheel",
                str(wheel.absolute()),
                "--wheel-sha256",
                wheel_sha256,
            ]
        )
    first_use = _run(install_command, subject="clean first use")
    provider_calls = conversation.get("provider_calls")
    synthetic_only = (
        conversation.get("synthetic_only") is True and first_use.get("synthetic_only") is True
    )
    network_after_install = first_use.get("network_after_install")
    real_state_accessed = first_use.get("real_atready_or_codex_state_accessed")
    return {
        "conversation": {
            "gates": conversation.get("gates"),
            "manual_provider_required": conversation.get("manual_provider_required"),
            "provider_calls": conversation.get("provider_calls"),
            "summary": conversation.get("summary"),
        },
        "first_use": {
            "installations": [
                {
                    "checks": lane.get("checks"),
                    "commands_checked": lane.get("commands_checked"),
                    "install_kind": lane.get("install_kind"),
                }
                for lane in first_use.get("installations", [])
            ],
            "network_after_install": network_after_install,
            "real_atready_or_codex_state_accessed": real_state_accessed,
        },
        "host_behavior_proven": conversation.get("host_behavior_proven"),
        "manual_provider_cases_completed": conversation.get("manual_provider_cases_completed"),
        "offline_contract_passed": (
            conversation.get("offline_contract_passed") is True
            and first_use.get("result") == "passed"
            and provider_calls == 0
            and synthetic_only
            and network_after_install == "common-python-socket-paths-blocked"
            and real_state_accessed is False
        ),
        "provider_calls": provider_calls,
        "synthetic_only": synthetic_only,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, help="Also prove one exact local wheel installation")
    args = parser.parse_args()
    try:
        receipt = run(wheel=args.wheel)
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt["offline_contract_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
