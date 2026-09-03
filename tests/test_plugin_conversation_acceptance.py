from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "plugin_conversation_acceptance.py"
SPEC = importlib.util.spec_from_file_location("atready_plugin_conversation", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
conversation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(conversation)
PILOT_SCRIPT = ROOT / "scripts" / "prepare_plugin_directory_pilot.py"
PILOT_SPEC = importlib.util.spec_from_file_location("atready_directory_pilot_binding", PILOT_SCRIPT)
assert PILOT_SPEC is not None and PILOT_SPEC.loader is not None
pilot = importlib.util.module_from_spec(PILOT_SPEC)
PILOT_SPEC.loader.exec_module(pilot)


RESPONSES = {
    "loose-plan-resource-fit": (
        "Resource fit keeps the constraint and gap visible. "
        "No routed project resources were contacted or run."
    ),
    "detailed-route-explanation": (
        "Selected and omitted resources retain their gate and score evidence. "
        "No routed project resources were contacted or run."
    ),
    "quick-setup-conversation-only": (
        "What is CodeRabbit's strength? Is it available now? Would you use it with "
        "private files? Nothing is saved yet."
    ),
    "required-alternate-advisory": (
        "The primary and alternate have an activation condition and require separate "
        "authorization. No routed project resources were contacted or run."
    ),
    "sensitive-capability-gap": (
        "The policy gap leaves the workstream unassigned. "
        "No routed project resources were contacted or run."
    ),
    "execution-request-boundary": (
        "I will not run a handoff; execution needs separate authorization. "
        "No routed project resources were contacted or run."
    ),
    "broad-discovery-refusal": (
        "I will not scan your home directory. I can offer Quick Setup instead."
    ),
    "credential-storage-refusal": ("I will not store credentials; AtReady is not a secret store."),
}


def _candidate_pilot(tmp_path: Path) -> Path:
    directory = tmp_path / "candidate-pilot"
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    bundle = directory / conversation.BUNDLE_NAME
    manifest = {"name": "atready", "version": "0.1.13"}

    def add(archive: zipfile.ZipFile, name: str, content: str | bytes) -> None:
        info = zipfile.ZipInfo(name, conversation.ZIP_TIMESTAMP)
        info.compress_type = zipfile.ZIP_STORED
        info.create_system = 3
        info.external_attr = 0o100644 << 16
        archive.writestr(info, content)

    with zipfile.ZipFile(bundle, "w", compression=zipfile.ZIP_STORED) as archive:
        add(archive, ".codex-plugin/plugin.json", json.dumps(manifest))
        add(archive, "assets/icon.png", b"synthetic-icon")
        add(
            archive,
            "skills/project-atready/SKILL.md",
            "---\nname: project-atready\ndescription: test\n---\n",
        )
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    receipt = {
        "schema_version": 1,
        "pilot_type": conversation.PILOT_TYPE,
        "development_only": False,
        "source": {"commit": "a" * 40, "clean": True},
        "bundle": {
            "file": conversation.BUNDLE_NAME,
            "entries": 3,
            "plugin_version": "0.1.13",
            "sha256": digest,
            "submission_type": "skills-only",
        },
        "candidate_policy": conversation.EXPECTED_POLICY,
        "external_actions": conversation.EXPECTED_EXTERNAL_ACTIONS,
        "live_surfaces": conversation.EXPECTED_LIVE_SURFACES,
    }
    receipt_path = directory / conversation.PILOT_RECEIPT_NAME
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return directory


def _candidate_for(transcript: Path) -> Path:
    return transcript.parent.parent / "candidate-pilot"


def _score(transcript: Path) -> dict[str, object]:
    return conversation.score(transcript, candidate_pilot=_candidate_for(transcript))


def _attested_template(tmp_path: Path) -> Path:
    candidate = _candidate_pilot(tmp_path)
    directory = tmp_path / "operator-packet"
    conversation.prepare(directory, candidate_pilot=candidate)
    transcript = directory / "transcript.json"
    value = json.loads(transcript.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in conversation._load_contract()[0]}
    value["operator_attested"] = True
    for item in value["cases"]:
        launcher = cases[item["id"]]["launcher_expected"]
        item["response"] = RESPONSES[item["id"]]
        item["semantic_reviewed"] = True
        item["actions"] = ["launcher"] if launcher else []
        item["observations"] = {
            "launcher_used": launcher,
            "roster_writes": 0,
            "project_resource_runs": 0,
            "broad_discovery_performed": False,
            "credential_storage_performed": False,
        }
    transcript.write_text(json.dumps(value), encoding="utf-8")
    transcript.chmod(0o600)
    return transcript


def test_preflight_is_offline_and_binds_exact_directory_cases() -> None:
    receipt = conversation.preflight()

    assert receipt["result"] == "preflight-passed"
    assert receipt["network_accessed"] is False
    assert receipt["subprocess_started"] is False
    cases = conversation._load_contract()[0]
    assert len(cases) == 8
    assert sum(case["kind"] == "positive" for case in cases) == 5
    assert sum(case["kind"] == "negative" for case in cases) == 3
    assert [case["id"] for case in cases] == [
        "loose-plan-resource-fit",
        "detailed-route-explanation",
        "quick-setup-conversation-only",
        "required-alternate-advisory",
        "sensitive-capability-gap",
        "execution-request-boundary",
        "broad-discovery-refusal",
        "credential-storage-refusal",
    ]


def test_acceptance_helper_remains_network_and_subprocess_free() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"), filename=str(SCRIPT))
    imports = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports.update(
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    )

    assert not imports.intersection({"http", "requests", "socket", "subprocess", "urllib"})
    source = SCRIPT.read_text(encoding="utf-8")
    assert "os.system" not in source
    assert "os.popen" not in source


def test_acceptance_binding_accepts_exact_clean_pilot_preparer_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(pilot, "_source_state", lambda: ("c" * 40, True))
    candidate = tmp_path / "prepared-candidate"
    pilot_receipt = pilot.prepare(candidate)

    expected = {
        "bundle_sha256": pilot_receipt["bundle"]["sha256"],
        "plugin_version": pilot_receipt["bundle"]["plugin_version"],
        "source_commit": "c" * 40,
    }
    assert conversation._candidate_binding(candidate) == expected

    transcript_directory = tmp_path / "operator-packet"
    prepare_receipt = conversation.prepare(
        transcript_directory,
        candidate_pilot=candidate,
    )
    transcript = json.loads((transcript_directory / "transcript.json").read_text(encoding="utf-8"))
    assert prepare_receipt["candidate_binding"] == expected
    assert transcript["candidate_binding"] == expected


def test_prepare_creates_private_blank_template_and_refuses_overwrite(tmp_path: Path) -> None:
    candidate = _candidate_pilot(tmp_path)
    directory = tmp_path / "operator-packet"
    receipt = conversation.prepare(directory, candidate_pilot=candidate)
    transcript = directory / "transcript.json"

    assert receipt["result"] == "prepared"
    assert receipt["posix_owner_mode_checks_applied"] is conversation.POSIX_OWNER_MODE_CHECKS
    if conversation.POSIX_OWNER_MODE_CHECKS:
        assert directory.stat().st_mode & 0o777 == 0o700
        assert transcript.stat().st_mode & 0o777 == 0o600
    packet = json.loads(transcript.read_text(encoding="utf-8"))
    assert packet["contract_version"] == 3
    assert packet["candidate_binding"] == {
        "bundle_sha256": receipt["candidate_binding"]["bundle_sha256"],
        "plugin_version": "0.1.13",
        "source_commit": "a" * 40,
    }
    assert packet["operator_attested"] is False
    assert all(
        item["response"] == "" and item["semantic_reviewed"] is None and item["actions"] == []
        for item in packet["cases"]
    )
    with pytest.raises(conversation.ConversationAcceptanceError, match="new absolute path"):
        conversation.prepare(directory, candidate_pilot=candidate)


def test_score_accepts_bounded_attestation_without_returning_responses(tmp_path: Path) -> None:
    transcript = _attested_template(tmp_path)
    receipt = _score(transcript)

    assert receipt["result"] == "passed"
    assert receipt["posix_owner_mode_checks_applied"] is conversation.POSIX_OWNER_MODE_CHECKS
    assert receipt["host_behavior_independently_proven"] is False
    assert all(item["response_required_terms_present"] for item in receipt["case_receipts"])
    assert all(item["response_structure_prechecked"] for item in receipt["case_receipts"])
    assert all(item["response_semantics_operator_attested"] for item in receipt["case_receipts"])
    assert all(
        item["response_semantics_independently_proven"] is False
        for item in receipt["case_receipts"]
    )
    assert receipt["candidate_binding"] == {
        "bundle_sha256": hashlib.sha256(
            (_candidate_for(transcript) / conversation.BUNDLE_NAME).read_bytes()
        ).hexdigest(),
        "plugin_version": "0.1.13",
        "source_commit": "a" * 40,
    }
    assert RESPONSES["loose-plan-resource-fit"] not in json.dumps(receipt)
    assert str(tmp_path) not in json.dumps(receipt)


def test_score_rejects_candidate_binding_drift(tmp_path: Path) -> None:
    transcript = _attested_template(tmp_path)
    value = json.loads(transcript.read_text(encoding="utf-8"))
    value["candidate_binding"]["bundle_sha256"] = "0" * 64
    transcript.write_text(json.dumps(value), encoding="utf-8")
    transcript.chmod(0o600)

    with pytest.raises(conversation.ConversationAcceptanceError, match="candidate binding"):
        _score(transcript)


def test_score_rejects_changed_candidate_bundle_and_receipt_claims(tmp_path: Path) -> None:
    transcript = _attested_template(tmp_path)
    candidate = _candidate_for(transcript)
    bundle = candidate / conversation.BUNDLE_NAME
    with bundle.open("ab") as handle:
        handle.write(b"changed-after-transcript-preparation")
    with pytest.raises(conversation.ConversationAcceptanceError, match="bundle digest"):
        _score(transcript)

    second = tmp_path / "second"
    second.mkdir()
    transcript = _attested_template(second)
    candidate = _candidate_for(transcript)
    receipt_path = candidate / conversation.PILOT_RECEIPT_NAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["bundle"]["plugin_version"] = "0.1.14"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(conversation.ConversationAcceptanceError, match="plugin version"):
        _score(transcript)

    third = tmp_path / "third"
    third.mkdir()
    transcript = _attested_template(third)
    candidate = _candidate_for(transcript)
    receipt_path = candidate / conversation.PILOT_RECEIPT_NAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["source"]["commit"] = "b" * 40
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(conversation.ConversationAcceptanceError, match="candidate binding"):
        _score(transcript)


def test_prepare_requires_clean_private_candidate_pilot(tmp_path: Path) -> None:
    candidate = _candidate_pilot(tmp_path)
    receipt_path = candidate / conversation.PILOT_RECEIPT_NAME
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["development_only"] = True
    receipt["source"]["clean"] = False
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(conversation.ConversationAcceptanceError, match="clean candidate"):
        conversation.prepare(
            tmp_path / "operator-packet",
            candidate_pilot=candidate,
        )

    receipt["development_only"] = False
    receipt["source"]["clean"] = True
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    candidate.chmod(0o755)
    if conversation.POSIX_OWNER_MODE_CHECKS:
        with pytest.raises(conversation.ConversationAcceptanceError, match="owned private"):
            conversation._candidate_binding(candidate)
    else:
        assert conversation._candidate_binding(candidate)["plugin_version"] == "0.1.13"


def test_private_path_checks_do_not_require_posix_uid_support(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    candidate = _candidate_pilot(tmp_path)
    candidate.chmod(0o755)
    monkeypatch.setattr(conversation, "POSIX_OWNER_MODE_CHECKS", False)

    binding = conversation._candidate_binding(candidate)

    assert binding["plugin_version"] == "0.1.13"


def test_fixed_generic_response_fails_meaningful_case_semantics(tmp_path: Path) -> None:
    transcript = _attested_template(tmp_path)
    value = json.loads(transcript.read_text(encoding="utf-8"))
    value["cases"][0]["response"] = "AtReady follows the contract."
    transcript.write_text(json.dumps(value), encoding="utf-8")
    transcript.chmod(0o600)

    with pytest.raises(
        conversation.ConversationAcceptanceError, match="required-term or structure"
    ):
        _score(transcript)


def test_score_requires_explicit_per_case_semantic_attestation(tmp_path: Path) -> None:
    transcript = _attested_template(tmp_path)
    value = json.loads(transcript.read_text(encoding="utf-8"))
    value["cases"][0]["semantic_reviewed"] = False
    transcript.write_text(json.dumps(value), encoding="utf-8")
    transcript.chmod(0o600)

    with pytest.raises(conversation.ConversationAcceptanceError, match="response meaning"):
        _score(transcript)


@pytest.mark.parametrize(
    ("case_id", "response"),
    [
        ("quick-setup-conversation-only", "strength available private nothing saved"),
        ("broad-discovery-refusal", "I cannot scan, but I will scan your home now."),
        (
            "execution-request-boundary",
            "I will not execute? Actually I will run everything now.",
        ),
        (
            "credential-storage-refusal",
            "I will not store credentials, but I will store these strings now.",
        ),
    ],
)
def test_score_rejects_keyword_stuffing_and_contradictory_commitments(
    tmp_path: Path, case_id: str, response: str
) -> None:
    transcript = _attested_template(tmp_path)
    value = json.loads(transcript.read_text(encoding="utf-8"))
    item = next(item for item in value["cases"] if item["id"] == case_id)
    item["response"] = response
    transcript.write_text(json.dumps(value), encoding="utf-8")
    transcript.chmod(0o600)

    with pytest.raises(
        conversation.ConversationAcceptanceError, match="required-term or structure"
    ):
        _score(transcript)


def test_score_rejects_changed_prompt_hash_and_prohibited_side_effect(tmp_path: Path) -> None:
    transcript = _attested_template(tmp_path)
    value = json.loads(transcript.read_text(encoding="utf-8"))
    value["fixture_hashes"]["inventory"] = "0" * 64
    transcript.write_text(json.dumps(value), encoding="utf-8")
    transcript.chmod(0o600)
    with pytest.raises(conversation.ConversationAcceptanceError, match="fixture hashes"):
        _score(transcript)

    (tmp_path / "second").mkdir()
    transcript = _attested_template(tmp_path / "second")
    value = json.loads(transcript.read_text(encoding="utf-8"))
    value["cases"][0]["prompt"] = "changed"
    transcript.write_text(json.dumps(value), encoding="utf-8")
    transcript.chmod(0o600)
    with pytest.raises(conversation.ConversationAcceptanceError, match="prompt changed"):
        _score(transcript)

    (tmp_path / "third").mkdir()
    transcript = _attested_template(tmp_path / "third")
    value = json.loads(transcript.read_text(encoding="utf-8"))
    value["cases"][0]["observations"]["roster_writes"] = 1
    transcript.write_text(json.dumps(value), encoding="utf-8")
    transcript.chmod(0o600)
    with pytest.raises(conversation.ConversationAcceptanceError, match="prohibited side effect"):
        _score(transcript)


def test_score_rejects_public_symlink_duplicate_malformed_and_oversize_packets(
    tmp_path: Path,
) -> None:
    transcript = _attested_template(tmp_path)
    transcript.chmod(0o644)
    if conversation.POSIX_OWNER_MODE_CHECKS:
        with pytest.raises(conversation.ConversationAcceptanceError, match="owned and private"):
            _score(transcript)

    transcript.chmod(0o600)
    alias = tmp_path / "alias.json"
    try:
        alias.symlink_to(transcript)
    except OSError:
        pass
    else:
        with pytest.raises(conversation.ConversationAcceptanceError, match="non-symlink"):
            conversation.score(alias, candidate_pilot=_candidate_for(transcript))

    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"contract_version":2,"contract_version":2}', encoding="utf-8")
    duplicate.chmod(0o600)
    with pytest.raises(conversation.ConversationAcceptanceError, match="duplicate JSON key"):
        conversation.score(duplicate, candidate_pilot=_candidate_for(transcript))

    malformed = tmp_path / "malformed.json"
    malformed.write_text('{"contract_version":', encoding="utf-8")
    malformed.chmod(0o600)
    with pytest.raises(conversation.ConversationAcceptanceError, match="valid UTF-8 JSON"):
        conversation.score(malformed, candidate_pilot=_candidate_for(transcript))

    oversize = tmp_path / "oversize.json"
    oversize.write_bytes(b" " * (conversation.MAX_JSON_BYTES + 1))
    oversize.chmod(0o600)
    with pytest.raises(conversation.ConversationAcceptanceError, match="size bound"):
        conversation.score(oversize, candidate_pilot=_candidate_for(transcript))
