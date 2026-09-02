#!/usr/bin/env python3
"""Run each pytest file in a separate bounded process.

GitHub's Windows runners can remain attached to a pytest process after an
individual test leaks or retains an operating-system handle.  Running one file
per process makes the responsible file visible in the log and keeps the CI job
bounded without changing the normal Linux and macOS suite.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
FILE_TIMEOUT_SECONDS = 90


def main() -> int:
    test_files = sorted(TESTS.glob("test_*.py"))
    if not test_files:
        print("No test files found.", file=sys.stderr)
        return 2

    for test_file in test_files:
        relative = test_file.relative_to(ROOT)
        print(f"Running {relative}", flush=True)
        try:
            result = subprocess.run(  # noqa: S603 - fixed interpreter and repository tests
                [sys.executable, "-m", "pytest", "-q", str(relative)],
                cwd=ROOT,
                check=False,
                timeout=FILE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            print(
                f"Timed out after {FILE_TIMEOUT_SECONDS}s: {relative}",
                file=sys.stderr,
                flush=True,
            )
            return 124
        if result.returncode != 0:
            return result.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
