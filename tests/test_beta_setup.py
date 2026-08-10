from __future__ import annotations

import importlib.util
import json
from argparse import Namespace
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "beta_setup.py"
SPEC = importlib.util.spec_from_file_location("atready_beta_setup", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
beta_setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(beta_setup)

SHA = "a" * 40
NEW_SHA = "b" * 40
REPOSITORY = "example/atready-beta"


def _doctor_payload() -> dict[str, object]:
    return {
        "compatible": True,
        "inventory_read": False,
        "missing_features": [],
        "network_accessed": False,
        "plugin_contract_version": 1,
        "plugin_version": "0.2.0",
        "product": "project-atready",
        "runtime_contract_version": 1,
        "runtime_features": ["inventory.read.v1", "routing.plan-only.v1"],
        "runtime_version": "0.1.4",
        "status": "ready",
        "writes_performed": False,
    }


def _launcher_source(
    tmp_path: Path,
    *,
    version: str = "0.2.0",
    contract: int = 1,
    features: tuple[str, ...] = ("inventory.read.v1", "routing.plan-only.v1"),
) -> Path:
    source = tmp_path / "source"
    launcher = (
        source / "plugins" / "atready" / "skills" / "project-atready" / "scripts" / "atready.py"
    )
    launcher.parent.mkdir(parents=True)
    launcher.write_text(
        f"PLUGIN_VERSION = {version!r}\n"
        f"REQUIRED_RUNTIME_CONTRACT_VERSION = {contract!r}\n"
        f"REQUIRED_RUNTIME_FEATURE_IDS = {features!r}\n",
        encoding="utf-8",
    )
    return source


@pytest.mark.parametrize(
    ("repository", "source_sha", "run_id", "message"),
    [
        ("not-a-repository", SHA, "123", "OWNER/REPOSITORY"),
        (REPOSITORY, "A" * 40, "123", "40 lowercase"),
        (REPOSITORY, SHA, "run-123", "decimal digits"),
    ],
)
def test_candidate_identity_is_explicit_and_bounded(
    repository: str, source_sha: str, run_id: str, message: str
) -> None:
    with pytest.raises(beta_setup.BetaSetupError, match=message):
        beta_setup._validate_identity(repository, source_sha, run_id)


def test_beta_root_must_be_absolute_and_cannot_be_home_or_symlink(tmp_path: Path) -> None:
    with pytest.raises(beta_setup.BetaSetupError, match="explicit absolute"):
        beta_setup._resolve_root(Path("relative"), must_exist=False)
    with pytest.raises(beta_setup.BetaSetupError, match="user home"):
        beta_setup._resolve_root(Path.home(), must_exist=True)

    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("this platform does not permit symlink creation")
    with pytest.raises(beta_setup.BetaSetupError, match="symbolic link"):
        beta_setup._resolve_root(link, must_exist=True)


def test_windows_runtime_uses_the_uv_reported_exe_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(beta_setup.os, "name", "nt")
    assert beta_setup._executable(tmp_path) == tmp_path / "atready.exe"


def test_workflow_verification_binds_all_candidate_identity_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], *, cwd: Path | None = None) -> str:
        assert cwd is None
        calls.append(argv)
        return json.dumps(
            {
                "workflowName": "Release candidate",
                "event": "workflow_dispatch",
                "conclusion": "success",
                "headSha": SHA,
            }
        )

    monkeypatch.setattr(beta_setup, "_run", fake_run)
    beta_setup._verify_workflow(
        {"gh": "/tools/gh"}, repository=REPOSITORY, source_sha=SHA, run_id="123"
    )

    assert calls == [
        [
            "/tools/gh",
            "run",
            "view",
            "123",
            "--repo",
            REPOSITORY,
            "--json",
            "workflowName,event,conclusion,headSha",
        ]
    ]


def test_workflow_verification_refuses_a_branch_or_failed_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        beta_setup,
        "_run",
        lambda argv, cwd=None: json.dumps(
            {
                "workflowName": "Release candidate",
                "event": "push",
                "conclusion": "failure",
                "headSha": SHA,
            }
        ),
    )
    with pytest.raises(beta_setup.BetaSetupError, match="owner-dispatched"):
        beta_setup._verify_workflow(
            {"gh": "gh"}, repository=REPOSITORY, source_sha=SHA, run_id="123"
        )


def test_codex_listing_tables_are_strict_and_preserve_absolute_paths(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    marketplace_root = tmp_path / "marketplace with spaces"
    plugin_path = marketplace_root / "plugins" / "atready"
    marketplace_header = f"{'MARKETPLACE':<28}ROOT"
    marketplace_row = f"{'atready':<28}{marketplace_root}"
    plugin_header = f"{'PLUGIN':<32}{'STATUS':<22}{'VERSION':<10}PATH"
    plugin_row = f"{'atready@atready':<32}{'installed, enabled':<22}{'0.2.0':<10}{plugin_path}"

    def fake_run(argv: list[str], *, cwd: Path | None = None) -> str:
        assert cwd is None
        if argv[-2:] == ["marketplace", "list"]:
            return f"{marketplace_header}\n{marketplace_row}\n"
        return (
            f"Marketplace `atready`\n/synthetic/marketplace.json\n\n{plugin_header}\n{plugin_row}\n"
        )

    monkeypatch.setattr(beta_setup, "_run", fake_run)
    commands = {"codex": "/tools/codex"}
    assert beta_setup._marketplace_roots(commands) == {"atready": marketplace_root.resolve()}
    assert beta_setup._plugin_row(commands) == (
        "installed, enabled",
        "0.2.0",
        plugin_path.resolve(),
    )


def test_codex_plugin_table_accepts_an_installed_disabled_plugin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    plugin_path = tmp_path / "marketplace" / "plugins" / "atready"
    header = f"{'PLUGIN':<32}{'STATUS':<22}{'VERSION':<10}PATH"
    row = f"{'atready@atready':<32}{'installed, disabled':<22}{'0.2.0':<10}{plugin_path}"
    monkeypatch.setattr(beta_setup, "_run", lambda argv, cwd=None: f"{header}\n{row}\n")

    assert beta_setup._plugin_row({"codex": "/tools/codex"}) == (
        "installed, disabled",
        "0.2.0",
        plugin_path.resolve(),
    )


@pytest.mark.parametrize("version", ["", "not-a-version"])
def test_codex_plugin_table_rejects_an_invalid_disabled_plugin_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, version: str
) -> None:
    plugin_path = tmp_path / "marketplace" / "plugins" / "atready"
    header = f"{'PLUGIN':<32}{'STATUS':<22}{'VERSION':<10}PATH"
    row = f"{'atready@atready':<32}{'installed, disabled':<22}{version:<10}{plugin_path}"
    monkeypatch.setattr(beta_setup, "_run", lambda argv, cwd=None: f"{header}\n{row}\n")

    with pytest.raises(beta_setup.BetaSetupError, match="malformed row"):
        beta_setup._plugin_row({"codex": "/tools/codex"})


@pytest.mark.parametrize("subject", ["marketplace", "plugin"])
def test_codex_listing_tables_reject_malformed_output(
    monkeypatch: pytest.MonkeyPatch, subject: str
) -> None:
    malformed = "not a supported table\n"
    monkeypatch.setattr(beta_setup, "_run", lambda argv, cwd=None: malformed)
    with pytest.raises(beta_setup.BetaSetupError, match="unexpected table header"):
        if subject == "marketplace":
            beta_setup._marketplace_roots({"codex": "codex"})
        else:
            beta_setup._plugin_row({"codex": "codex"})


def test_runtime_contract_uses_the_exact_executable_and_plugin_version(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = tmp_path / "atready"
    source = _launcher_source(tmp_path)
    calls: list[list[str]] = []

    def fake_run(argv: list[str], *, cwd: Path | None = None) -> str:
        assert cwd is None
        calls.append(argv)
        return json.dumps(_doctor_payload())

    monkeypatch.setattr(beta_setup, "_run", fake_run)
    beta_setup._verify_runtime_contract(
        executable,
        source=source,
        plugin_version="0.2.0",
        runtime_version="0.1.4",
    )
    assert calls == [
        [
            str(executable),
            "doctor",
            "--plugin-version",
            "0.2.0",
            "--plugin-contract",
            "1",
            "--require-feature",
            "inventory.read.v1",
            "--require-feature",
            "routing.plan-only.v1",
            "--json",
        ]
    ]


def test_beta_launcher_requirements_accept_exact_metadata_bounds(tmp_path: Path) -> None:
    version = "1.1." + "9" * (beta_setup._MAX_PRODUCT_VERSION_CHARACTERS - len("1.1."))
    features = tuple(
        [f"feature-{index:03d}" for index in range(beta_setup._MAX_REQUIRED_FEATURE_IDS - 1)]
        + ["z" * beta_setup._MAX_FEATURE_ID_CHARACTERS]
    )

    assert beta_setup._launcher_requirements(
        _launcher_source(tmp_path, version=version, features=features)
    ) == (version, 1, features)


@pytest.mark.parametrize(
    ("version", "features"),
    [
        ("01.2.3", ("inventory.read.v1",)),
        ("1.2.3+", ("inventory.read.v1",)),
        (
            "1.1." + "9" * (beta_setup._MAX_PRODUCT_VERSION_CHARACTERS - len("1.1.") + 1),
            ("inventory.read.v1",),
        ),
        ("1.2.3", ("z" * (beta_setup._MAX_FEATURE_ID_CHARACTERS + 1),)),
        (
            "1.2.3",
            tuple(
                f"feature-{index:03d}" for index in range(beta_setup._MAX_REQUIRED_FEATURE_IDS + 1)
            ),
        ),
    ],
)
def test_beta_launcher_requirements_reject_invalid_or_oversized_metadata(
    tmp_path: Path, version: str, features: tuple[str, ...]
) -> None:
    source = _launcher_source(tmp_path, version=version, features=features)

    with pytest.raises(beta_setup.BetaSetupError, match=r"launcher has (?:an )?invalid"):
        beta_setup._launcher_requirements(source)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("compatible", False),
        ("inventory_read", True),
        ("missing_features", ["routing.plan-only.v1"]),
        ("network_accessed", True),
        ("plugin_contract_version", True),
        ("plugin_version", "0.2.1"),
        ("product", "wrong-product"),
        ("runtime_contract_version", True),
        ("runtime_version", "0.1.5"),
        ("status", "incompatible"),
        ("writes_performed", True),
        ("runtime_features", ["routing.plan-only.v1", "inventory.read.v1"]),
        ("unexpected", "field"),
    ],
)
def test_runtime_contract_rejects_each_unsafe_or_drifting_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, field: str, invalid: object
) -> None:
    source = _launcher_source(tmp_path)
    payload = _doctor_payload()
    payload[field] = invalid
    monkeypatch.setattr(beta_setup, "_run", lambda argv, cwd=None: json.dumps(payload))

    with pytest.raises(beta_setup.BetaSetupError, match="doctor"):
        beta_setup._verify_runtime_contract(
            tmp_path / "atready",
            source=source,
            plugin_version="0.2.0",
            runtime_version="0.1.4",
        )


@pytest.mark.parametrize(
    "raw",
    ["", " " * (beta_setup._MAX_DOCTOR_CHARACTERS + 1)],
    ids=["empty", "oversized"],
)
def test_runtime_contract_rejects_empty_or_oversized_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, raw: str
) -> None:
    source = _launcher_source(tmp_path)
    monkeypatch.setattr(beta_setup, "_run", lambda argv, cwd=None: raw)

    with pytest.raises(beta_setup.BetaSetupError, match="invalid bounded report"):
        beta_setup._verify_runtime_contract(
            tmp_path / "atready",
            source=source,
            plugin_version="0.2.0",
            runtime_version="0.1.4",
        )


def test_runtime_contract_rejects_a_missing_required_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = _launcher_source(tmp_path)
    payload = _doctor_payload()
    del payload["runtime_features"]
    monkeypatch.setattr(beta_setup, "_run", lambda argv, cwd=None: json.dumps(payload))

    with pytest.raises(beta_setup.BetaSetupError, match="unexpected report shape"):
        beta_setup._verify_runtime_contract(
            tmp_path / "atready",
            source=source,
            plugin_version="0.2.0",
            runtime_version="0.1.4",
        )


def test_state_round_trip_is_value_free_and_strict(tmp_path: Path) -> None:
    payload = beta_setup._state_payload(
        repository=REPOSITORY,
        source_sha=SHA,
        run_id="123",
        runtime_version="0.1.4",
        plugin_version="0.2.0",
        source=tmp_path / "releases" / SHA / "source",
        candidate=tmp_path / "releases" / SHA / "candidate",
        inventory=tmp_path / "test-state" / "inventory.yaml",
    )
    beta_setup._write_state(tmp_path, payload)
    assert beta_setup._load_state(tmp_path) == payload
    assert not ({"token", "credential", "account", "inventory_contents"} & payload.keys())

    state_path = tmp_path / beta_setup._STATE_NAME
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["unexpected"] = "field"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(beta_setup.BetaSetupError, match="unexpected shape"):
        beta_setup._load_state(tmp_path)


def test_install_orchestrates_verified_candidate_before_mutating_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "isolated-beta"
    uv_bin = tmp_path / "uv-bin"
    uv_bin.mkdir()
    executable = uv_bin / "atready"
    events: list[str] = []

    monkeypatch.setattr(
        beta_setup,
        "_require_commands",
        lambda: {"gh": "gh", "git": "git", "uv": "uv", "codex": "codex"},
    )
    monkeypatch.setattr(beta_setup, "_uv_bin", lambda commands: uv_bin)
    monkeypatch.setattr(beta_setup, "_marketplace_roots", lambda commands: {})

    def fake_run(argv: list[str], *, cwd: Path | None = None) -> str:
        assert cwd is None
        if argv[1:3] == ["init", "--path"]:
            Path(argv[3]).write_text("synthetic", encoding="utf-8")
        return ""

    monkeypatch.setattr(beta_setup, "_run", fake_run)
    monkeypatch.setattr(
        beta_setup,
        "_verify_workflow",
        lambda *args, **kwargs: events.append("workflow"),
    )

    def stage(*args: object, **kwargs: object) -> tuple[Path, Path, str, str]:
        events.append("stage")
        source = root / "releases" / SHA / "source"
        candidate = root / "releases" / SHA / "candidate"
        candidate.mkdir(parents=True)
        return source, candidate, "0.1.4", "0.2.0"

    monkeypatch.setattr(beta_setup, "_stage_candidate", stage)
    monkeypatch.setattr(
        beta_setup,
        "_install_wheel",
        lambda commands, wheel: events.append("wheel"),
    )
    monkeypatch.setattr(
        beta_setup,
        "_configure_plugin",
        lambda commands, source: events.append("plugin"),
    )
    monkeypatch.setattr(
        beta_setup,
        "_verify_installed",
        lambda *args, **kwargs: events.append(f"verify:{kwargs['run_acceptance']}") or executable,
    )

    beta_setup.install(
        Namespace(
            repository=REPOSITORY,
            source_sha=SHA,
            run_id="123",
            beta_root=root,
        )
    )

    assert events == ["workflow", "stage", "wheel", "plugin", "verify:True"]
    state = beta_setup._load_state(root)
    assert state["source_sha"] == SHA
    assert state["inventory"] == str(root / "test-state" / "inventory.yaml")


def test_update_preserves_inventory_and_records_only_after_full_verification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "isolated-beta"
    root.mkdir()
    previous_source = root / "releases" / SHA / "source"
    previous_candidate = root / "releases" / SHA / "candidate"
    previous_candidate.mkdir(parents=True)
    inventory = root / "test-state" / "inventory.yaml"
    inventory.parent.mkdir()
    inventory.write_text("synthetic", encoding="utf-8")
    beta_setup._write_state(
        root,
        beta_setup._state_payload(
            repository=REPOSITORY,
            source_sha=SHA,
            run_id="123",
            runtime_version="0.1.4",
            plugin_version="0.2.0",
            source=previous_source,
            candidate=previous_candidate,
            inventory=inventory,
        ),
    )
    events: list[str] = []
    commands = {"gh": "gh", "git": "git", "uv": "uv", "codex": "codex"}
    monkeypatch.setattr(beta_setup, "_require_commands", lambda: commands)
    monkeypatch.setattr(
        beta_setup,
        "_verified_state_candidate",
        lambda *args: (previous_source, previous_candidate, "0.1.4", "0.2.0"),
    )
    monkeypatch.setattr(
        beta_setup,
        "_verify_installed",
        lambda *args, **kwargs: (
            events.append(f"verify:{kwargs['runtime_version']}:{kwargs['plugin_version']}")
            or Path("qm")
        ),
    )
    monkeypatch.setattr(
        beta_setup,
        "_verify_workflow",
        lambda *args, **kwargs: events.append("workflow"),
    )

    def stage(*args: object, **kwargs: object) -> tuple[Path, Path, str, str]:
        events.append("stage")
        source = root / "releases" / NEW_SHA / "source"
        candidate = root / "releases" / NEW_SHA / "candidate"
        candidate.mkdir(parents=True)
        return source, candidate, "0.1.4", "0.2.1"

    monkeypatch.setattr(beta_setup, "_stage_candidate", stage)
    monkeypatch.setattr(
        beta_setup,
        "_install_wheel",
        lambda commands, wheel: events.append("wheel"),
    )
    monkeypatch.setattr(
        beta_setup,
        "_remove_plugin_configuration",
        lambda commands: events.append("remove"),
    )
    monkeypatch.setattr(
        beta_setup,
        "_configure_plugin",
        lambda commands, source: events.append("plugin"),
    )

    beta_setup.update(
        Namespace(
            repository=REPOSITORY,
            source_sha=NEW_SHA,
            run_id="456",
            beta_root=root,
        )
    )

    assert events == [
        "verify:0.1.4:0.2.0",
        "workflow",
        "stage",
        "wheel",
        "remove",
        "plugin",
        "verify:0.1.4:0.2.1",
    ]
    state = beta_setup._load_state(root)
    assert state["source_sha"] == NEW_SHA
    assert state["run_id"] == "456"
    assert state["runtime_version"] == "0.1.4"
    assert state["plugin_version"] == "0.2.1"
    assert state["inventory"] == str(inventory)
    assert inventory.read_text(encoding="utf-8") == "synthetic"


def test_update_state_commit_failure_restores_previous_pair_and_old_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "isolated-beta"
    root.mkdir()
    source = root / "releases" / SHA / "source"
    candidate = root / "releases" / SHA / "candidate"
    candidate.mkdir(parents=True)
    inventory = root / "test-state" / "inventory.yaml"
    inventory.parent.mkdir()
    inventory.write_text("synthetic", encoding="utf-8")
    old_state = beta_setup._state_payload(
        repository=REPOSITORY,
        source_sha=SHA,
        run_id="123",
        runtime_version="0.1.4",
        plugin_version="0.2.0",
        source=source,
        candidate=candidate,
        inventory=inventory,
    )
    beta_setup._write_state(root, old_state)
    events: list[str] = []
    commands = {"gh": "gh", "git": "git", "uv": "uv", "codex": "codex"}
    monkeypatch.setattr(beta_setup, "_require_commands", lambda: commands)
    monkeypatch.setattr(
        beta_setup,
        "_verified_state_candidate",
        lambda *args: (source, candidate, "0.1.4", "0.2.0"),
    )
    monkeypatch.setattr(
        beta_setup,
        "_verify_installed",
        lambda *args, **kwargs: (
            events.append(f"verify:{kwargs['runtime_version']}:{kwargs['plugin_version']}")
            or Path("qm")
        ),
    )
    monkeypatch.setattr(beta_setup, "_verify_workflow", lambda *args, **kwargs: None)

    def stage(*args: object, **kwargs: object) -> tuple[Path, Path, str, str]:
        new_source = root / "releases" / NEW_SHA / "source"
        new_candidate = root / "releases" / NEW_SHA / "candidate"
        new_candidate.mkdir(parents=True)
        return new_source, new_candidate, "0.1.4", "0.2.1"

    monkeypatch.setattr(beta_setup, "_stage_candidate", stage)
    monkeypatch.setattr(beta_setup, "_install_wheel", lambda *args: events.append("wheel"))
    monkeypatch.setattr(
        beta_setup, "_remove_plugin_configuration", lambda *args: events.append("remove")
    )
    monkeypatch.setattr(beta_setup, "_configure_plugin", lambda *args: events.append("configure"))
    monkeypatch.setattr(
        beta_setup,
        "_write_state",
        lambda *args: (_ for _ in ()).throw(OSError("synthetic state fsync failure")),
    )
    monkeypatch.setattr(
        beta_setup,
        "_clear_atready_configuration",
        lambda *args: events.append("clear-new"),
    )
    monkeypatch.setattr(
        beta_setup, "_restore_exact_beta", lambda *args: events.append("restore-old")
    )

    with pytest.raises(beta_setup.BetaSetupError, match="previous beta was restored"):
        beta_setup.update(
            Namespace(
                repository=REPOSITORY,
                source_sha=NEW_SHA,
                run_id="456",
                beta_root=root,
            )
        )

    assert events == [
        "verify:0.1.4:0.2.0",
        "wheel",
        "remove",
        "configure",
        "verify:0.1.4:0.2.1",
        "clear-new",
        "restore-old",
    ]
    assert json.loads((root / beta_setup._STATE_NAME).read_text(encoding="utf-8")) == old_state
    assert inventory.read_text(encoding="utf-8") == "synthetic"


def test_exact_failed_update_candidate_can_be_reverified_and_reused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "isolated-beta"
    release = root / "releases" / NEW_SHA
    source = release / "source"
    candidate = release / "candidate"
    (source / "scripts").mkdir(parents=True)
    candidate.mkdir()
    (source / "scripts" / "beta_setup.py").write_bytes(SCRIPT.read_bytes())
    (source / "scripts" / "release_bundle.py").write_text("# verified by fake run\n")
    manifest = source / "plugins" / "atready" / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({"name": "atready", "version": "0.2.1"}), encoding="utf-8")
    (candidate / "release-receipt.json").write_text(
        json.dumps({"runtime_version": "0.1.4", "plugin_version": "0.2.1"}),
        encoding="utf-8",
    )
    (candidate / "project_atready-0.1.4-py3-none-any.whl").write_bytes(b"wheel")
    (release / beta_setup._STAGED_NAME).write_text(
        json.dumps({"repository": REPOSITORY, "run_id": "456", "source_sha": NEW_SHA}),
        encoding="utf-8",
    )
    calls: list[list[str]] = []

    def fake_run(argv: list[str], *, cwd: Path | None = None) -> str:
        assert cwd is None
        calls.append(argv)
        if "rev-parse" in argv:
            return f"{NEW_SHA}\n"
        return ""

    monkeypatch.setattr(beta_setup, "_run", fake_run)
    result = beta_setup._stage_candidate(
        {"git": "git"},
        root=root,
        repository=REPOSITORY,
        source_sha=NEW_SHA,
        run_id="456",
    )

    assert result == (source, candidate, "0.1.4", "0.2.1")
    assert any("status" in call for call in calls)
    assert any("release_bundle.py" in " ".join(call) for call in calls)


def test_retry_refuses_a_retained_candidate_with_different_helper_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    release = tmp_path / "releases" / NEW_SHA
    source = release / "source"
    candidate = release / "candidate"
    (source / "scripts").mkdir(parents=True)
    candidate.mkdir()
    (source / "scripts" / "beta_setup.py").write_bytes(b"different helper bytes")
    (release / beta_setup._STAGED_NAME).write_text(
        json.dumps({"repository": REPOSITORY, "run_id": "456", "source_sha": NEW_SHA}),
        encoding="utf-8",
    )

    def fake_run(argv: list[str], *, cwd: Path | None = None) -> str:
        if "rev-parse" in argv:
            return f"{NEW_SHA}\n"
        return ""

    monkeypatch.setattr(beta_setup, "_run", fake_run)
    with pytest.raises(beta_setup.BetaSetupError, match="byte-match"):
        beta_setup._stage_candidate(
            {"git": "git"},
            root=tmp_path,
            repository=REPOSITORY,
            source_sha=NEW_SHA,
            run_id="456",
        )


def test_retry_refuses_retained_candidate_from_a_different_run(tmp_path: Path) -> None:
    release = tmp_path / "releases" / NEW_SHA
    release.mkdir(parents=True)
    (release / beta_setup._STAGED_NAME).write_text(
        json.dumps({"repository": REPOSITORY, "run_id": "999", "source_sha": NEW_SHA}),
        encoding="utf-8",
    )
    with pytest.raises(beta_setup.BetaSetupError, match="does not match this exact retry"):
        beta_setup._stage_candidate(
            {"git": "git"},
            root=tmp_path,
            repository=REPOSITORY,
            source_sha=NEW_SHA,
            run_id="456",
        )


def test_failed_candidate_staging_removes_only_its_temporary_directory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "isolated-beta"
    root.mkdir()

    def fail_clone(argv: list[str], *, cwd: Path | None = None) -> str:
        raise beta_setup.BetaSetupError("synthetic clone failure")

    monkeypatch.setattr(beta_setup, "_run", fail_clone)
    with pytest.raises(beta_setup.BetaSetupError, match="synthetic clone failure"):
        beta_setup._stage_candidate(
            {"gh": "gh", "git": "git"},
            root=root,
            repository=REPOSITORY,
            source_sha=NEW_SHA,
            run_id="456",
        )

    assert not (root / "releases").exists()


def test_failed_candidate_staging_preserves_a_preexisting_release_container(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "isolated-beta"
    sibling = root / "releases" / SHA
    sibling.mkdir(parents=True)

    def fail_clone(argv: list[str], *, cwd: Path | None = None) -> str:
        raise beta_setup.BetaSetupError("synthetic clone failure")

    monkeypatch.setattr(beta_setup, "_run", fail_clone)
    with pytest.raises(beta_setup.BetaSetupError, match="synthetic clone failure"):
        beta_setup._stage_candidate(
            {"gh": "gh", "git": "git"},
            root=root,
            repository=REPOSITORY,
            source_sha=NEW_SHA,
            run_id="456",
        )

    assert sibling.is_dir()


def test_remove_preserves_beta_files_and_inventory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "isolated-beta"
    source = root / "releases" / SHA / "source"
    candidate = root / "releases" / SHA / "candidate"
    candidate.mkdir(parents=True)
    inventory = root / "test-state" / "inventory.yaml"
    inventory.parent.mkdir()
    inventory.write_text("synthetic", encoding="utf-8")
    beta_setup._write_state(
        root,
        beta_setup._state_payload(
            repository=REPOSITORY,
            source_sha=SHA,
            run_id="123",
            runtime_version="0.1.4",
            plugin_version="0.2.0",
            source=source,
            candidate=candidate,
            inventory=inventory,
        ),
    )
    uv_bin = tmp_path / "uv-bin"
    uv_bin.mkdir()
    events: list[str] = []
    commands = {"gh": "gh", "git": "git", "uv": "uv", "codex": "codex"}
    monkeypatch.setattr(beta_setup, "_require_commands", lambda: commands)
    monkeypatch.setattr(
        beta_setup,
        "_verified_state_candidate",
        lambda *args: (source, candidate, "0.1.4", "0.2.0"),
    )
    monkeypatch.setattr(
        beta_setup,
        "_verify_installed",
        lambda *args, **kwargs: events.append("verify") or Path("qm"),
    )
    monkeypatch.setattr(
        beta_setup,
        "_remove_plugin_configuration",
        lambda commands: events.append("remove-plugin"),
    )
    monkeypatch.setattr(beta_setup, "_marketplace_roots", lambda commands: {})
    monkeypatch.setattr(beta_setup, "_uv_bin", lambda commands: uv_bin)

    def fake_run(argv: list[str], *, cwd: Path | None = None) -> str:
        assert cwd is None
        assert argv == ["uv", "tool", "uninstall", "project-atready"]
        events.append("remove-runtime")
        return ""

    monkeypatch.setattr(beta_setup, "_run", fake_run)
    beta_setup.remove(Namespace(beta_root=root))

    assert events == ["verify", "remove-plugin", "remove-runtime"]
    assert root.is_dir()
    assert candidate.is_dir()
    assert inventory.read_text(encoding="utf-8") == "synthetic"


def test_partial_plugin_removal_restores_exact_previous_beta(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "isolated-beta"
    source = root / "releases" / SHA / "source"
    candidate = root / "releases" / SHA / "candidate"
    candidate.mkdir(parents=True)
    inventory = root / "test-state" / "inventory.yaml"
    inventory.parent.mkdir()
    inventory.write_text("synthetic", encoding="utf-8")
    state = beta_setup._state_payload(
        repository=REPOSITORY,
        source_sha=SHA,
        run_id="123",
        runtime_version="0.1.4",
        plugin_version="0.2.0",
        source=source,
        candidate=candidate,
        inventory=inventory,
    )
    beta_setup._write_state(root, state)
    events: list[str] = []
    commands = {"gh": "gh", "git": "git", "uv": "uv", "codex": "codex"}
    monkeypatch.setattr(beta_setup, "_require_commands", lambda: commands)
    monkeypatch.setattr(
        beta_setup,
        "_verified_state_candidate",
        lambda *args: (source, candidate, "0.1.4", "0.2.0"),
    )
    monkeypatch.setattr(
        beta_setup,
        "_verify_installed",
        lambda *args, **kwargs: events.append("verify-old") or Path("qm"),
    )

    def partial_remove(*args: object) -> None:
        events.append("plugin-removed-marketplace-remains")
        raise beta_setup.BetaSetupError("synthetic marketplace removal failure")

    monkeypatch.setattr(beta_setup, "_remove_plugin_configuration", partial_remove)
    monkeypatch.setattr(
        beta_setup, "_restore_exact_beta", lambda *args: events.append("restore-exact-old")
    )

    with pytest.raises(beta_setup.BetaSetupError, match="exact previous beta was restored"):
        beta_setup.remove(Namespace(beta_root=root))

    assert events == [
        "verify-old",
        "plugin-removed-marketplace-remains",
        "restore-exact-old",
    ]
    assert beta_setup._load_state(root) == state
    assert inventory.read_text(encoding="utf-8") == "synthetic"


def test_restore_plugin_configuration_repairs_partial_plugin_removal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "release" / "source"
    expected_plugin = (source / "plugins" / "atready").resolve()
    commands = {"codex": "codex"}
    calls: list[list[str]] = []
    monkeypatch.setattr(
        beta_setup,
        "_marketplace_roots",
        lambda commands: {"atready": source.resolve()},
    )
    monkeypatch.setattr(
        beta_setup,
        "_plugin_row",
        lambda commands: ("not installed", "", expected_plugin),
    )

    def fake_run(argv: list[str], *, cwd: Path | None = None) -> str:
        assert cwd is None
        calls.append(argv)
        return ""

    monkeypatch.setattr(beta_setup, "_run", fake_run)
    beta_setup._restore_plugin_configuration(commands, source)

    assert calls == [["codex", "plugin", "add", "atready@atready"]]


def test_restore_plugin_configuration_reenables_an_installed_disabled_plugin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "release" / "source"
    expected_plugin = (source / "plugins" / "atready").resolve()
    commands = {"codex": "codex"}
    calls: list[list[str]] = []
    monkeypatch.setattr(
        beta_setup,
        "_marketplace_roots",
        lambda commands: {"atready": source.resolve()},
    )
    monkeypatch.setattr(
        beta_setup,
        "_plugin_row",
        lambda commands: ("installed, disabled", "0.2.0", expected_plugin),
    )
    monkeypatch.setattr(
        beta_setup,
        "_run",
        lambda argv, cwd=None: calls.append(argv) or "",
    )

    beta_setup._restore_plugin_configuration(commands, source)

    assert calls == [
        ["codex", "plugin", "remove", "atready@atready"],
        ["codex", "plugin", "add", "atready@atready"],
    ]


@pytest.mark.parametrize("status", ["installed, enabled", "installed, disabled"])
def test_clear_configuration_removes_either_installed_plugin_state(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: str
) -> None:
    source = tmp_path / "source"
    commands = {"codex": "codex"}
    calls: list[list[str]] = []
    monkeypatch.setattr(
        beta_setup,
        "_marketplace_roots",
        lambda commands: {"atready": source.resolve()},
    )
    monkeypatch.setattr(
        beta_setup,
        "_plugin_row",
        lambda commands: (status, "0.2.0", source / "plugins" / "atready"),
    )
    monkeypatch.setattr(beta_setup, "_run", lambda argv, cwd=None: calls.append(argv) or "")

    beta_setup._clear_atready_configuration(commands)

    assert calls == [
        ["codex", "plugin", "remove", "atready@atready"],
        ["codex", "plugin", "marketplace", "remove", "atready"],
    ]


@pytest.mark.parametrize("status", ["installed, enabled", "installed, disabled"])
def test_new_install_rollback_removes_either_installed_plugin_state_and_runtime(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, status: str
) -> None:
    source = tmp_path / "source"
    uv_bin = tmp_path / "uv-bin"
    uv_bin.mkdir()
    beta_setup._executable(uv_bin).write_text("synthetic", encoding="utf-8")
    commands = {"codex": "codex", "uv": "uv"}
    calls: list[list[str]] = []
    monkeypatch.setattr(
        beta_setup,
        "_marketplace_roots",
        lambda commands: {"atready": source.resolve()},
    )
    monkeypatch.setattr(
        beta_setup,
        "_plugin_row",
        lambda commands: (status, "0.2.0", source / "plugins" / "atready"),
    )
    monkeypatch.setattr(beta_setup, "_uv_bin", lambda commands: uv_bin)
    monkeypatch.setattr(beta_setup, "_run", lambda argv, cwd=None: calls.append(argv) or "")

    beta_setup._rollback_new_install(commands)

    assert calls == [
        ["codex", "plugin", "remove", "atready@atready"],
        ["codex", "plugin", "marketplace", "remove", "atready"],
        ["uv", "tool", "uninstall", "project-atready"],
    ]


def test_exact_restore_reinstalls_runtime_then_restores_and_verifies_plugin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    source = tmp_path / "release" / "source"
    candidate = tmp_path / "release" / "candidate"
    candidate.mkdir(parents=True)
    wheel = candidate / "project_atready-0.1.4-py3-none-any.whl"
    wheel.write_bytes(b"wheel")
    state = {
        "runtime_version": "0.1.4",
        "plugin_version": "0.2.0",
    }
    commands = {"uv": "uv"}
    uv_bin = tmp_path / "uv-bin"
    uv_bin.mkdir()
    events: list[str] = []
    monkeypatch.setattr(
        beta_setup,
        "_verified_state_candidate",
        lambda *args: (source, candidate, "0.1.4", "0.2.0"),
    )
    monkeypatch.setattr(beta_setup, "_uv_bin", lambda commands: uv_bin)
    monkeypatch.setattr(
        beta_setup,
        "_install_wheel",
        lambda commands, selected: events.append(f"runtime:{selected.name}"),
    )
    monkeypatch.setattr(
        beta_setup,
        "_restore_plugin_configuration",
        lambda commands, selected: events.append(f"plugin:{selected}"),
    )
    monkeypatch.setattr(
        beta_setup,
        "_verify_installed",
        lambda *args, **kwargs: events.append("verified") or Path("qm"),
    )

    beta_setup._restore_exact_beta(commands, state)

    assert events == [
        "runtime:project_atready-0.1.4-py3-none-any.whl",
        f"plugin:{source}",
        "verified",
    ]


def test_setup_never_contains_remote_pipe_or_github_access_mutation() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "curl" not in text
    assert "permission=pull" not in text
    assert "/collaborators/" not in text
    assert "gh api" not in text
    assert "shell=True" not in text
