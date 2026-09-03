#!/usr/bin/env python3
"""Prepare and score offline, operator-attested Directory reviewer conversations.

This tool never authenticates, contacts a network service, invokes Codex, or starts a subprocess.
It validates a source-controlled packet plus a clean candidate receipt and ZIP, prepares a private
bundle-bound transcript, and scores bounded operator observations without returning observed model
text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evals" / "DIRECTORY_CONVERSATION_CASES.json"
DIRECTORY_PACKET = ROOT / "docs" / "DIRECTORY_SUBMISSION.md"
MAX_JSON_BYTES = 1_048_576
MAX_ARCHIVE_BYTES = 100_000_000
MAX_ARCHIVE_ENTRIES = 5_000
MAX_ARCHIVE_MEMBER_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
PRIVATE_MODE_MASK = stat.S_IRWXG | stat.S_IRWXO
POSIX_OWNER_MODE_CHECKS = os.name == "posix" and callable(getattr(os, "getuid", None))
ALLOWED_ACTIONS = {"launcher", "inventory-read", "route", "preview", "write"}
SECRET_PATTERNS = (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), re.compile(r"\bAKIA[0-9A-Z]{16}\b"))
PILOT_RECEIPT_NAME = "LOCAL_PILOT_RECEIPT.json"
PILOT_TYPE = "local-only-plugin-directory-preparation"
BUNDLE_NAME = "atready-directory-pilot.zip"
EXPECTED_POLICY = {"products": ["CODEX"], "allow_implicit_invocation": False}
EXPECTED_EXTERNAL_ACTIONS = {
    "network_accessed": False,
    "portal_draft_created": False,
    "portal_upload_performed": False,
    "submitted_for_review": False,
    "published": False,
    "plugin_installed": False,
    "runtime_installed": False,
}
EXPECTED_LIVE_SURFACES = {
    "openai_plugin_portal": "unproved",
    "chatgpt_chat_work_web_desktop_mobile": "unproved",
    "codex_desktop_local_worktree": "unproved",
    "codex_cli": "unproved",
    "codex_ide_extension": "unproved",
    "codex_cloud_remote": "unproved",
}
COMMIT = re.compile(r"^[0-9a-f]{40}$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class ConversationAcceptanceError(RuntimeError):
    """The offline packet, transcript, or bounded observations are invalid."""


def _unique_json(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ConversationAcceptanceError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path, *, label: str, require_private: bool) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ConversationAcceptanceError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ConversationAcceptanceError(f"{label} must be a regular non-symlink file")
    if metadata.st_size > MAX_JSON_BYTES:
        raise ConversationAcceptanceError(f"{label} exceeds its size bound")
    if (
        require_private
        and POSIX_OWNER_MODE_CHECKS
        and (metadata.st_uid != os.getuid() or metadata.st_mode & PRIVATE_MODE_MASK)
    ):
        raise ConversationAcceptanceError(f"{label} must be owned and private")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConversationAcceptanceError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ConversationAcceptanceError(f"{label} must contain a JSON object")
    return value


def _private_directory(path: Path, *, label: str) -> Path:
    if not path.is_absolute():
        raise ConversationAcceptanceError(f"{label} must be an absolute path")
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ConversationAcceptanceError(f"{label} is unavailable") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISDIR(metadata.st_mode)
        or (
            POSIX_OWNER_MODE_CHECKS
            and (metadata.st_uid != os.getuid() or metadata.st_mode & PRIVATE_MODE_MASK)
        )
    ):
        raise ConversationAcceptanceError(f"{label} must be an owned private directory")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise ConversationAcceptanceError("candidate bundle is unavailable") from exc
    return digest.hexdigest()


def _bundle_manifest(bundle_path: Path, *, expected_entries: int) -> dict[str, Any]:
    try:
        metadata = bundle_path.lstat()
    except OSError as exc:
        raise ConversationAcceptanceError("candidate bundle is unavailable") from exc
    if (
        stat.S_ISLNK(metadata.st_mode)
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size > MAX_ARCHIVE_BYTES
    ):
        raise ConversationAcceptanceError("candidate bundle must be a bounded regular ZIP")
    try:
        with zipfile.ZipFile(bundle_path) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if (
                not infos
                or len(infos) > MAX_ARCHIVE_ENTRIES
                or len(infos) != expected_entries
                or len(names) != len(set(names))
                or names != sorted(names)
                or any(info.is_dir() for info in infos)
                or any(info.compress_type != zipfile.ZIP_STORED for info in infos)
                or any(info.create_system != 3 for info in infos)
                or any(info.date_time != ZIP_TIMESTAMP for info in infos)
                or any(info.external_attr != 0o100644 << 16 for info in infos)
                or any(info.file_size > MAX_ARCHIVE_MEMBER_BYTES for info in infos)
                or sum(info.file_size for info in infos) > MAX_ARCHIVE_UNCOMPRESSED_BYTES
            ):
                raise ConversationAcceptanceError("candidate bundle entry contract is invalid")
            for name in names:
                if (
                    not name
                    or name != name.strip()
                    or name.startswith("/")
                    or "\\" in name
                    or "\x00" in name
                    or any(part in {"", ".", ".."} for part in name.split("/"))
                ):
                    raise ConversationAcceptanceError("candidate bundle contains an unsafe path")
            if archive.testzip() is not None:
                raise ConversationAcceptanceError("candidate bundle has a failed integrity check")
            if (
                names.count(".codex-plugin/plugin.json") != 1
                or names.count("assets/icon.png") != 1
                or not any(
                    name.startswith("skills/project-atready/") and name.endswith("/SKILL.md")
                    for name in names
                )
                or any(
                    name not in {".codex-plugin/plugin.json", "assets/icon.png"}
                    and not name.startswith("skills/project-atready/")
                    for name in names
                )
            ):
                raise ConversationAcceptanceError("candidate bundle is not a skills-only plugin")
            manifest_info = archive.getinfo(".codex-plugin/plugin.json")
            if manifest_info.file_size > MAX_JSON_BYTES:
                raise ConversationAcceptanceError(
                    "candidate plugin manifest exceeds its size bound"
                )
            manifest_bytes = archive.read(".codex-plugin/plugin.json")
            manifest = json.loads(manifest_bytes.decode("utf-8"), object_pairs_hook=_unique_json)
    except ConversationAcceptanceError:
        raise
    except (
        OSError,
        RuntimeError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        zipfile.BadZipFile,
    ) as exc:
        raise ConversationAcceptanceError("candidate bundle is not a valid plugin ZIP") from exc
    if not isinstance(manifest, dict) or manifest.get("name") != "atready":
        raise ConversationAcceptanceError("candidate bundle manifest is not AtReady")
    return manifest


def _candidate_binding(candidate_pilot: str | Path) -> dict[str, str]:
    directory = _private_directory(
        Path(candidate_pilot).expanduser(), label="candidate pilot directory"
    )
    receipt = _read_json(
        directory / PILOT_RECEIPT_NAME,
        label="candidate pilot receipt",
        require_private=False,
    )
    source, bundle = receipt.get("source"), receipt.get("bundle")
    if (
        set(receipt)
        != {
            "schema_version",
            "pilot_type",
            "development_only",
            "source",
            "bundle",
            "candidate_policy",
            "external_actions",
            "live_surfaces",
        }
        or type(receipt.get("schema_version")) is not int
        or receipt.get("schema_version") != 1
        or receipt.get("pilot_type") != PILOT_TYPE
        or receipt.get("development_only") is not False
        or receipt.get("candidate_policy") != EXPECTED_POLICY
        or receipt.get("external_actions") != EXPECTED_EXTERNAL_ACTIONS
        or receipt.get("live_surfaces") != EXPECTED_LIVE_SURFACES
        or not isinstance(source, dict)
        or set(source) != {"commit", "clean"}
        or source.get("clean") is not True
        or not isinstance(source.get("commit"), str)
        or COMMIT.fullmatch(source["commit"]) is None
        or not isinstance(bundle, dict)
        or set(bundle) != {"file", "entries", "plugin_version", "sha256", "submission_type"}
        or bundle.get("file") != BUNDLE_NAME
        or type(bundle.get("entries")) is not int
        or not 1 <= bundle["entries"] <= MAX_ARCHIVE_ENTRIES
        or not isinstance(bundle.get("plugin_version"), str)
        or len(bundle["plugin_version"]) > 64
        or SEMVER.fullmatch(bundle["plugin_version"]) is None
        or not isinstance(bundle.get("sha256"), str)
        or DIGEST.fullmatch(bundle["sha256"]) is None
        or bundle.get("submission_type") != "skills-only"
    ):
        raise ConversationAcceptanceError(
            "candidate pilot receipt is not a clean candidate preparation receipt"
        )
    bundle_path = directory / BUNDLE_NAME
    actual_digest = _sha256(bundle_path)
    if actual_digest != bundle["sha256"]:
        raise ConversationAcceptanceError(
            "candidate bundle digest does not match its pilot receipt"
        )
    manifest = _bundle_manifest(bundle_path, expected_entries=bundle["entries"])
    if manifest.get("version") != bundle["plugin_version"]:
        raise ConversationAcceptanceError(
            "candidate plugin version does not match its pilot receipt"
        )
    return {
        "bundle_sha256": actual_digest,
        "plugin_version": bundle["plugin_version"],
        "source_commit": source["commit"],
    }


def _repository_file(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ConversationAcceptanceError("fixture source must be repository-relative")
    candidate = ROOT / path
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ConversationAcceptanceError("fixture source is unavailable") from exc
    if not resolved.is_relative_to(ROOT) or candidate.is_symlink() or not resolved.is_file():
        raise ConversationAcceptanceError("fixture source must be a regular repository file")
    return resolved


def _markdown_yaml(path: Path, heading: str) -> bytes:
    match = re.search(
        rf"### `{re.escape(heading)}`\n\n```yaml\n(.*?)\n```",
        path.read_text(encoding="utf-8"),
        re.DOTALL,
    )
    if match is None:
        raise ConversationAcceptanceError(
            "fixture source does not contain its expected YAML payload"
        )
    return (match.group(1) + "\n").encode()


def _fixture_hashes(contract: dict[str, Any]) -> dict[str, str]:
    sources = contract.get("fixture_sources")
    if not isinstance(sources, dict) or not sources:
        raise ConversationAcceptanceError("conversation contract lacks fixture sources")
    hashes: dict[str, str] = {}
    for identifier, source in sources.items():
        if not isinstance(identifier, str) or not isinstance(source, dict):
            raise ConversationAcceptanceError("conversation fixture definition is invalid")
        kind, location, expected = source.get("kind"), source.get("path"), source.get("sha256")
        if kind not in {"file", "markdown-yaml"} or not isinstance(location, str):
            raise ConversationAcceptanceError("conversation fixture source is invalid")
        if not isinstance(expected, str) or re.fullmatch(r"[0-9a-f]{64}", expected) is None:
            raise ConversationAcceptanceError("conversation fixture hash is invalid")
        path = _repository_file(location)
        if kind == "file":
            content = path.read_bytes()
        else:
            heading = source.get("heading")
            if not isinstance(heading, str) or not heading.endswith(".yaml"):
                raise ConversationAcceptanceError("markdown fixture heading is invalid")
            content = _markdown_yaml(path, heading)
        actual = hashlib.sha256(content).hexdigest()
        if actual != expected:
            raise ConversationAcceptanceError(f"fixture hash changed: {identifier}")
        hashes[identifier] = actual
    return hashes


def _load_contract() -> tuple[list[dict[str, Any]], dict[str, str]]:
    contract = _read_json(CASES_PATH, label="conversation contract", require_private=False)
    if contract.get("contract_version") != 2:
        raise ConversationAcceptanceError("conversation contract version is unsupported")
    cases = contract.get("cases")
    if not isinstance(cases, list) or len(cases) != 8:
        raise ConversationAcceptanceError("conversation contract must contain exactly eight cases")
    hashes = _fixture_hashes(contract)
    identifiers: set[str] = set()
    positive = negative = 0
    packet = DIRECTORY_PACKET.read_text(encoding="utf-8")
    for case in cases:
        if not isinstance(case, dict):
            raise ConversationAcceptanceError("conversation case is invalid")
        identifier, kind, prompt = case.get("id"), case.get("kind"), case.get("prompt")
        fixtures, launcher, semantic = (
            case.get("fixtures"),
            case.get("launcher_expected"),
            case.get("semantic"),
        )
        if (
            not isinstance(identifier, str)
            or re.fullmatch(r"[a-z][a-z0-9-]{0,63}", identifier) is None
            or identifier in identifiers
            or kind not in {"positive", "negative"}
            or not isinstance(prompt, str)
            or not prompt
            or f"- Prompt: `{prompt}`" not in packet
            or not isinstance(fixtures, list)
            or not all(isinstance(item, str) and item in hashes for item in fixtures)
            or type(launcher) is not bool
            or not isinstance(semantic, dict)
        ):
            raise ConversationAcceptanceError("conversation case contract is invalid or drifted")
        identifiers.add(identifier)
        positive += kind == "positive"
        negative += kind == "negative"
    if positive != 5 or negative != 3:
        raise ConversationAcceptanceError(
            "conversation contract must contain five positive and three negative cases"
        )
    return cases, hashes


def preflight() -> dict[str, Any]:
    cases, hashes = _load_contract()
    return {
        "case_count": len(cases),
        "fixture_hashes": hashes,
        "host_behavior_independently_proven": False,
        "network_accessed": False,
        "result": "preflight-passed",
        "subprocess_started": False,
        "synthetic_only": True,
    }


def _template(
    cases: list[dict[str, Any]], hashes: dict[str, str], candidate_binding: dict[str, str]
) -> dict[str, Any]:
    return {
        "contract_version": 3,
        "candidate_binding": candidate_binding,
        "fixture_hashes": hashes,
        "operator_attested": False,
        "cases": [
            {
                "id": case["id"],
                "prompt": case["prompt"],
                "response": "",
                "semantic_reviewed": None,
                "actions": [],
                "observations": {
                    "launcher_used": None,
                    "roster_writes": None,
                    "project_resource_runs": None,
                    "broad_discovery_performed": None,
                    "credential_storage_performed": None,
                },
            }
            for case in cases
        ],
    }


def prepare(directory: str | Path, *, candidate_pilot: str | Path) -> dict[str, Any]:
    cases, hashes = _load_contract()
    candidate_binding = _candidate_binding(candidate_pilot)
    target = Path(directory).expanduser()
    if not target.is_absolute() or target.exists():
        raise ConversationAcceptanceError("prepare directory must be a new absolute path")
    try:
        parent = target.parent.lstat()
    except OSError as exc:
        raise ConversationAcceptanceError("prepare directory parent is unavailable") from exc
    if stat.S_ISLNK(parent.st_mode) or not stat.S_ISDIR(parent.st_mode):
        raise ConversationAcceptanceError("prepare directory parent must be a real directory")
    try:
        target.mkdir(mode=0o700)
        target.chmod(0o700)
        output = target / "transcript.json"
        descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(
                descriptor,
                (
                    json.dumps(
                        _template(cases, hashes, candidate_binding), indent=2, sort_keys=True
                    )
                    + "\n"
                ).encode(),
            )
        finally:
            os.close(descriptor)
        output.chmod(0o600)
    except OSError as exc:
        raise ConversationAcceptanceError("could not create private transcript template") from exc
    return {
        "case_count": len(cases),
        "candidate_binding": candidate_binding,
        "host_behavior_independently_proven": False,
        "network_accessed": False,
        "posix_owner_mode_checks_applied": POSIX_OWNER_MODE_CHECKS,
        "result": "prepared",
        "subprocess_started": False,
        "synthetic_only": True,
        "transcript_template_created": True,
    }


def _required_term_errors(response: str, rules: dict[str, Any]) -> list[str]:
    """Return conservative lexical/structure failures, never a semantic judgment."""

    normalized = " ".join(response.casefold().split())
    required_all, required_any = rules.get("all", []), rules.get("any", [])
    minimum_questions = rules.get("min_questions", 0)
    forbidden_commitments = rules.get("forbidden_commitments", [])
    if (
        not isinstance(required_all, list)
        or not isinstance(required_any, list)
        or not all(isinstance(term, str) for term in required_all + required_any)
        or type(minimum_questions) is not int
        or not 0 <= minimum_questions <= 10
        or not isinstance(forbidden_commitments, list)
        or not all(term in {"execute", "run", "scan", "store"} for term in forbidden_commitments)
    ):
        raise ConversationAcceptanceError("conversation response precheck contract is invalid")
    errors = [term for term in required_all if term.casefold() not in normalized]
    if required_any and not any(term.casefold() in normalized for term in required_any):
        errors.append("one case-specific outcome")
    if response.count("?") < minimum_questions:
        errors.append(f"at least {minimum_questions} questions")
    if rules.get("boundary") is True and not any(
        term in normalized
        for term in ("no routed project resources were contacted or run", "not execute", "not run")
    ):
        errors.append("execution boundary")
    blocked_verbs = set(forbidden_commitments)
    if rules.get("boundary") is True:
        blocked_verbs.update({"execute", "run"})
    for verb in sorted(blocked_verbs):
        commitment = re.compile(
            rf"\b(?:i|we)\s+(?:will|can|shall|am going to|are going to)\s+"
            rf"(?:actually\s+)?{verb}\b"
        )
        if commitment.search(normalized):
            errors.append(f"contradictory commitment to {verb}")
    return errors


def _score_case(
    observed: dict[str, Any], case: dict[str, Any], hashes: dict[str, str]
) -> dict[str, Any]:
    if observed.get("id") != case["id"] or observed.get("prompt") != case["prompt"]:
        raise ConversationAcceptanceError("transcript case ID or prompt changed")
    response, semantic_reviewed, actions, observations = (
        observed.get("response"),
        observed.get("semantic_reviewed"),
        observed.get("actions"),
        observed.get("observations"),
    )
    if not isinstance(response, str) or not response.strip() or len(response) > 20_000:
        raise ConversationAcceptanceError("transcript response must be a bounded non-empty string")
    if any(pattern.search(response) for pattern in SECRET_PATTERNS):
        raise ConversationAcceptanceError("transcript response appears to contain a credential")
    if semantic_reviewed is not True:
        raise ConversationAcceptanceError(
            "transcript case must explicitly attest that response meaning was reviewed"
        )
    if (
        not isinstance(actions, list)
        or len(actions) != len(set(actions))
        or not all(isinstance(action, str) and action in ALLOWED_ACTIONS for action in actions)
        or not isinstance(observations, dict)
    ):
        raise ConversationAcceptanceError("transcript actions or observations are invalid")
    expected = {
        "launcher_used",
        "roster_writes",
        "project_resource_runs",
        "broad_discovery_performed",
        "credential_storage_performed",
    }
    if (
        set(observations) != expected
        or type(observations["launcher_used"]) is not bool
        or type(observations["roster_writes"]) is not int
        or type(observations["project_resource_runs"]) is not int
        or type(observations["broad_discovery_performed"]) is not bool
        or type(observations["credential_storage_performed"]) is not bool
    ):
        raise ConversationAcceptanceError(
            "transcript observations must use exact bounded primitive fields"
        )
    if observations["launcher_used"] is not case["launcher_expected"] or observations[
        "launcher_used"
    ] != ("launcher" in actions):
        raise ConversationAcceptanceError("operator launcher observation contradicts this case")
    if (
        observations["roster_writes"] != 0
        or observations["project_resource_runs"] != 0
        or observations["broad_discovery_performed"]
        or observations["credential_storage_performed"]
        or "write" in actions
    ):
        raise ConversationAcceptanceError("operator observations record a prohibited side effect")
    if _required_term_errors(response, case["semantic"]):
        raise ConversationAcceptanceError(
            "transcript response fails its required-term or structure precheck"
        )
    return {
        "id": case["id"],
        "fixture_hashes": {name: hashes[name] for name in case["fixtures"]},
        "launcher_observed": observations["launcher_used"],
        "operator_observations_bounded": True,
        "response_required_terms_present": True,
        "response_semantics_independently_proven": False,
        "response_semantics_operator_attested": semantic_reviewed,
        "response_structure_prechecked": True,
    }


def score(transcript_path: str | Path, *, candidate_pilot: str | Path) -> dict[str, Any]:
    cases, hashes = _load_contract()
    candidate_binding = _candidate_binding(candidate_pilot)
    transcript = _read_json(
        Path(transcript_path), label="operator transcript", require_private=True
    )
    if transcript.get("contract_version") != 3 or transcript.get("operator_attested") is not True:
        raise ConversationAcceptanceError("transcript must be operator-attested for this contract")
    if transcript.get("candidate_binding") != candidate_binding:
        raise ConversationAcceptanceError(
            "transcript candidate binding does not match the pilot receipt and bundle"
        )
    if transcript.get("fixture_hashes") != hashes:
        raise ConversationAcceptanceError("transcript fixture hashes do not match the packet")
    observed = transcript.get("cases")
    if not isinstance(observed, list) or len(observed) != len(cases):
        raise ConversationAcceptanceError("transcript must contain exactly the eight packet cases")
    receipts = [
        _score_case(item, case, hashes)
        for item, case in zip(observed, cases, strict=True)
        if isinstance(item, dict)
    ]
    if len(receipts) != len(cases):
        raise ConversationAcceptanceError("transcript case is invalid")
    return {
        "case_count": len(receipts),
        "case_receipts": receipts,
        "candidate_binding": candidate_binding,
        "host_behavior_independently_proven": False,
        "network_accessed": False,
        "operator_attested": True,
        "posix_owner_mode_checks_applied": POSIX_OWNER_MODE_CHECKS,
        "result": "passed",
        "subprocess_started": False,
        "synthetic_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--prepare", type=Path)
    group.add_argument("--transcript", type=Path)
    parser.add_argument(
        "--candidate-pilot",
        type=Path,
        help="private clean pilot directory containing its receipt and exact candidate ZIP",
    )
    arguments = parser.parse_args()
    try:
        if arguments.prepare or arguments.transcript:
            if arguments.candidate_pilot is None:
                raise ConversationAcceptanceError(
                    "--candidate-pilot is required for transcript preparation and scoring"
                )
            result = (
                prepare(arguments.prepare, candidate_pilot=arguments.candidate_pilot)
                if arguments.prepare
                else score(arguments.transcript, candidate_pilot=arguments.candidate_pilot)
            )
        elif arguments.candidate_pilot is not None:
            raise ConversationAcceptanceError(
                "--candidate-pilot is only valid with --prepare or --transcript"
            )
        else:
            result = preflight()
    except ConversationAcceptanceError as exc:
        print(json.dumps({"result": "blocked", "blocker": str(exc)}, sort_keys=True))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
