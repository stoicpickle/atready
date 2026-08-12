"""Create one private, disposable fresh-host transcript packet."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parents[2]
TEMPLATE = ROOT / "transcript-template.json"
PLUGIN_MANIFEST = REPOSITORY / "plugins/atready/.codex-plugin/plugin.json"
PROJECT = REPOSITORY / "pyproject.toml"
_MAX_TEMPLATE_BYTES = 64_000


class PrepareError(ValueError):
    """Raised when a private packet cannot be prepared safely."""


def _json_object(path: Path, *, maximum: int) -> dict[str, Any]:
    try:
        details = path.lstat()
        if not path.is_file() or path.is_symlink() or details.st_size > maximum:
            raise PrepareError(f"expected one bounded regular file: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PrepareError(f"cannot read packet input: {path}") from exc
    if not isinstance(value, dict):
        raise PrepareError(f"packet input must contain one object: {path}")
    return value


def _source_revision() -> str:
    git = shutil.which("git")
    if git is None:
        raise PrepareError("cannot identify the source revision")
    try:
        commit = subprocess.run(  # noqa: S603
            [git, "rev-parse", "HEAD"],
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
        dirty = subprocess.run(  # noqa: S603
            [git, "status", "--porcelain"],
            cwd=REPOSITORY,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise PrepareError("cannot identify the source revision") from exc
    return f"{commit} ({'dirty' if dirty else 'clean'})"


def prepare(root: Path) -> Path:
    """Create one new mode-private root containing a prompt-complete transcript template."""

    try:
        root.mkdir(mode=0o700, parents=False, exist_ok=False)
        if os.name == "posix":
            root.chmod(0o700)
    except OSError as exc:
        raise PrepareError(f"cannot create new private packet root: {exc}") from exc

    packet = _json_object(TEMPLATE, maximum=_MAX_TEMPLATE_BYTES)
    metadata = packet.get("metadata")
    cases = packet.get("cases")
    if not isinstance(metadata, dict) or not isinstance(cases, list):
        raise PrepareError("transcript template is incomplete")
    plugin = _json_object(PLUGIN_MANIFEST, maximum=_MAX_TEMPLATE_BYTES)
    try:
        project = tomllib.loads(PROJECT.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise PrepareError("cannot read project version") from exc
    metadata.update(
        {
            "source_revision": _source_revision(),
            "skill_version": f"atready plugin {plugin['version']}",
            "cli_version": f"atready {project['project']['version']}",
            "evaluation_date": date.today().isoformat(),
        }
    )
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise PrepareError("transcript template contains an invalid case")
        turns = case.get("turns")
        if not isinstance(turns, list) or not turns or not isinstance(turns[0], dict):
            raise PrepareError("transcript template contains invalid turns")
        prompt = ROOT.parent / "prompts" / f"{case['id']}.txt"
        try:
            if not prompt.is_file() or prompt.is_symlink():
                raise PrepareError(f"missing prompt for {case['id']}")
            turns[0]["text"] = prompt.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise PrepareError(f"cannot read prompt for {case['id']}") from exc

    target = root / "transcript.json"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= int(getattr(os, "O_NOFOLLOW", 0))
    try:
        descriptor = os.open(target, flags, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(packet, stream, indent=2)
            stream.write("\n")
    except (OSError, UnicodeError) as exc:
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass
        raise PrepareError(f"cannot write private transcript template: {exc}") from exc
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="One new disposable directory")
    args = parser.parse_args(argv)
    try:
        target = prepare(args.root.resolve())
    except PrepareError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
