#!/usr/bin/env python3
"""Run the bundled-kernel feasibility assessment under ``python -I -S``."""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

_MAX_RECEIPT_BYTES = 1_000_000


def _load_kernel() -> ModuleType:
    sys.dont_write_bytecode = True
    kernel_path = Path(__file__).resolve().with_name("atready_kernel.py")
    if not kernel_path.is_file() or kernel_path.is_symlink():
        raise RuntimeError("bundled kernel module must be one regular local file")
    spec = importlib.util.spec_from_file_location("atready_bundled_kernel", kernel_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load bundled kernel module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    origin = Path(module.__file__ or "").resolve()
    if origin != kernel_path:
        raise RuntimeError("bundled kernel module resolved outside the local bundle")
    return module


def _read_receipt(path: Path) -> object:
    if not path.is_file() or path.is_symlink():
        raise ValueError("canonical receipt must be one regular file")
    if path.stat().st_size > _MAX_RECEIPT_BYTES:
        raise ValueError("canonical receipt exceeds the one-megabyte probe limit")
    return json.loads(path.read_text(encoding="utf-8"))


def _runtime_facts(kernel: ModuleType) -> dict[str, object]:
    return {
        "isolated": sys.flags.isolated == 1,
        "no_site": sys.flags.no_site == 1,
        "site_packages_present": any("site-packages" in item for item in sys.path),
        "local_module": str(Path(kernel.__file__ or "").resolve()),
        "yaml_available": importlib.util.find_spec("yaml") is not None,
        "pydantic_available": importlib.util.find_spec("pydantic") is not None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assess, but never execute, a dependency-free AtReady kernel candidate."
    )
    parser.add_argument("--canonical-receipt", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        kernel = _load_kernel()
        result = kernel.assess(_read_receipt(args.canonical_receipt), _runtime_facts(kernel))
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
        print(
            json.dumps(
                {
                    "schema_version": 1,
                    "probe_kind": "bundled-kernel-feasibility",
                    "decision": {"status": "stop", "candidate_is_release_runtime": False},
                    "error": str(error),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
