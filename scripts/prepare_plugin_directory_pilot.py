#!/usr/bin/env python3
"""Prepare a local-only, nonrelease AtReady plugin-directory pilot bundle."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import shutil
import stat
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "atready"
AGENT = PLUGIN / "skills" / "project-atready" / "agents" / "openai.yaml"
BUILDER_PATH = ROOT / "scripts" / "build_plugin_submission.py"
BUNDLE_NAME = "atready-directory-pilot.zip"
RECEIPT_NAME = "LOCAL_PILOT_RECEIPT.json"
EXPECTED_POLICY = {
    "products": ["CODEX"],
    "allow_implicit_invocation": False,
}
LIVE_SURFACES = (
    "openai_plugin_portal",
    "chatgpt_chat_work_web_desktop_mobile",
    "codex_desktop_local_worktree",
    "codex_cli",
    "codex_ide_extension",
    "codex_cloud_remote",
)
COMMIT = re.compile(r"^[0-9a-f]{40}$")

BUILDER_SPEC = importlib.util.spec_from_file_location("atready_submission_builder", BUILDER_PATH)
if BUILDER_SPEC is None or BUILDER_SPEC.loader is None:  # pragma: no cover - importlib contract
    raise RuntimeError("could not load the deterministic submission builder")
submission_builder = importlib.util.module_from_spec(BUILDER_SPEC)
BUILDER_SPEC.loader.exec_module(submission_builder)


def _git(*arguments: str) -> str:
    """Run one fixed, local Git read command without a shell."""

    executable = shutil.which("git")
    if executable is None or not Path(executable).is_absolute():
        raise ValueError("could not resolve the local Git executable")
    result = subprocess.run(  # noqa: S603 - fixed local Git command vector
        [executable, "-C", str(ROOT), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise ValueError("could not read the local source state")
    return result.stdout


def _source_state() -> tuple[str, bool]:
    commit = _git("rev-parse", "--verify", "HEAD").strip()
    if not COMMIT.fullmatch(commit):
        raise ValueError("local source commit is invalid")
    clean = not _git("status", "--porcelain=v1", "--untracked-files=all")
    return commit, clean


def _candidate_policy() -> dict[str, object]:
    try:
        payload = yaml.safe_load(AGENT.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError("could not read the candidate policy") from exc
    if not isinstance(payload, dict) or payload.get("policy") != EXPECTED_POLICY:
        raise ValueError("candidate policy is not the reviewed Codex-only policy")
    return dict(EXPECTED_POLICY)


def _new_output_directory(output_dir: Path) -> Path:
    # lstat also detects a dangling symlink, for which Path.exists() is false.
    try:
        output_dir.lstat()
    except FileNotFoundError:
        pass
    else:
        raise ValueError("refusing to overwrite an existing pilot output directory")

    parent = output_dir.parent
    try:
        parent_metadata = parent.lstat()
    except FileNotFoundError as exc:
        raise ValueError("pilot output parent directory must already exist") from exc
    if parent.is_symlink() or not stat.S_ISDIR(parent_metadata.st_mode):
        raise ValueError("pilot output parent must be a real directory")

    try:
        output_dir.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise ValueError("refusing to overwrite an existing pilot output directory") from exc
    return output_dir


def prepare(output_dir: Path, *, allow_dirty: bool = False) -> dict[str, object]:
    """Build one isolated local pilot and return its value-safe receipt."""

    output_dir = output_dir.expanduser().absolute().resolve(strict=False)
    repository_root = ROOT.resolve()
    if output_dir == repository_root or repository_root in output_dir.parents:
        raise ValueError("pilot output directory must be outside the source repository")
    commit, clean = _source_state()
    if not clean and not allow_dirty:
        raise ValueError("refusing dirty source; pass --allow-dirty for a development-only pilot")
    policy = _candidate_policy()
    destination = _new_output_directory(output_dir)
    try:
        bundle_receipt = submission_builder.build(destination / BUNDLE_NAME)
        commit_after, clean_after = _source_state()
        if clean and (commit_after != commit or not clean_after):
            raise ValueError("source changed while preparing the clean pilot")
        receipt: dict[str, object] = {
            "schema_version": 1,
            "pilot_type": "local-only-plugin-directory-preparation",
            "development_only": not clean,
            "source": {"commit": commit, "clean": clean},
            "bundle": {
                "file": BUNDLE_NAME,
                "entries": bundle_receipt["entries"],
                "plugin_version": bundle_receipt["plugin_version"],
                "sha256": bundle_receipt["sha256"],
                "submission_type": bundle_receipt["submission_type"],
            },
            "candidate_policy": policy,
            "external_actions": {
                "network_accessed": False,
                "portal_draft_created": False,
                "portal_upload_performed": False,
                "submitted_for_review": False,
                "published": False,
                "plugin_installed": False,
                "runtime_installed": False,
            },
            "live_surfaces": {surface: "unproved" for surface in LIVE_SURFACES},
        }
        receipt_path = destination / RECEIPT_NAME
        with receipt_path.open("x", encoding="utf-8") as handle:
            json.dump(receipt, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except BaseException:
        shutil.rmtree(destination)
        raise
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="prepare a development-only pilot from a dirty local checkout",
    )
    arguments = parser.parse_args()
    try:
        receipt = prepare(arguments.output_dir, allow_dirty=arguments.allow_dirty)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
