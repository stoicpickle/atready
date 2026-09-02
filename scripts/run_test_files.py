#!/usr/bin/env python3
"""Run pytest files in small, separately bounded processes.

GitHub's Windows runners can remain attached to a pytest process after an
individual test leaks or retains an operating-system handle. Running small
batches makes the responsible group visible in the log and keeps the CI job
bounded without paying for a fresh interpreter for every file.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests"
BATCH_SIZE = 8
BATCH_TIMEOUT_SECONDS = 180


def main() -> int:
    test_files = sorted(TESTS.glob("test_*.py"))
    if not test_files:
        print("No test files found.", file=sys.stderr)
        return 2

    for offset in range(0, len(test_files), BATCH_SIZE):
        batch = [path.relative_to(ROOT) for path in test_files[offset : offset + BATCH_SIZE]]
        names = ", ".join(str(path) for path in batch)
        print(f"Running batch: {names}", flush=True)
        try:
            result = subprocess.run(  # noqa: S603 - fixed interpreter and repository tests
                [sys.executable, "-m", "pytest", "-q", *(str(path) for path in batch)],
                cwd=ROOT,
                check=False,
                timeout=BATCH_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            print(
                f"Timed out after {BATCH_TIMEOUT_SECONDS}s: {names}",
                file=sys.stderr,
                flush=True,
            )
            return 124
        if result.returncode != 0:
            return result.returncode

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
