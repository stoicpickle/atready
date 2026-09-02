from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "hardening_gate.py"


def _load_gate():
    spec = importlib.util.spec_from_file_location("hardening_gate", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_provider_free_hardening_gate_combines_bounded_receipts(monkeypatch) -> None:
    module = _load_gate()
    observed: list[tuple[str, list[str]]] = []

    def fake_run(command, *, subject):
        observed.append((subject, command))
        if subject == "conversation hardening":
            return {
                "offline_contract_passed": True,
                "host_behavior_proven": False,
                "manual_provider_cases_completed": False,
                "provider_calls": 0,
                "synthetic_only": True,
                "gates": {"safety_authorization": True},
                "summary": {"pass_rate": 1.0, "safety_pass_rate": 1.0},
                "manual_provider_required": [
                    "resource-add-conversation",
                    "planning-follow-up",
                    "hostile-project-text",
                ],
            }
        assert subject == "clean first use"
        return {
            "result": "passed",
            "network_after_install": "common-python-socket-paths-blocked",
            "real_atready_or_codex_state_accessed": False,
            "synthetic_only": True,
            "installations": [
                {"install_kind": "source", "commands_checked": 10, "checks": ["synthetic"]}
            ],
        }

    monkeypatch.setattr(module, "_run", fake_run)

    receipt = module.run()

    assert receipt["offline_contract_passed"] is True
    assert receipt["host_behavior_proven"] is False
    assert receipt["manual_provider_cases_completed"] is False
    assert receipt["synthetic_only"] is True
    assert receipt["provider_calls"] == 0
    assert receipt["conversation"]["summary"]["pass_rate"] >= 0.95
    assert receipt["conversation"]["summary"]["safety_pass_rate"] == 1.0
    assert receipt["conversation"]["manual_provider_required"] == [
        "resource-add-conversation",
        "planning-follow-up",
        "hostile-project-text",
    ]
    assert receipt["first_use"]["real_atready_or_codex_state_accessed"] is False
    assert receipt["first_use"]["network_after_install"] == ("common-python-socket-paths-blocked")
    assert [lane["install_kind"] for lane in receipt["first_use"]["installations"]] == ["source"]
    assert receipt["first_use"]["installations"][0]["commands_checked"] == 10
    assert observed[0] == (
        "conversation hardening",
        [module.sys.executable, str(ROOT / "evals/conversation_hardening/score.py")],
    )
    assert observed[1][0] == "clean first use"
    assert observed[1][1][:4] == [
        module.sys.executable,
        str(ROOT / "scripts/clean_first_use.py"),
        "--install",
        "source",
    ]
    assert len(observed[1][1]) == 4


def test_hardening_gate_binds_the_exact_wheel_digest(monkeypatch, tmp_path: Path) -> None:
    module = _load_gate()
    wheel = tmp_path / "project_atready-0.1.10-py3-none-any.whl"
    wheel.write_bytes(b"synthetic wheel")
    observed: list[tuple[str, list[str]]] = []

    def fake_run(command, *, subject):
        observed.append((subject, command))
        if subject == "conversation hardening":
            return {
                "offline_contract_passed": True,
                "host_behavior_proven": False,
                "manual_provider_cases_completed": False,
                "provider_calls": 0,
                "synthetic_only": True,
                "gates": {},
                "summary": {},
                "manual_provider_required": [],
            }
        return {
            "result": "passed",
            "network_after_install": "common-python-socket-paths-blocked",
            "real_atready_or_codex_state_accessed": False,
            "synthetic_only": True,
            "installations": [],
        }

    monkeypatch.setattr(module, "_run", fake_run)

    receipt = module.run(wheel=wheel)

    assert receipt["offline_contract_passed"] is True
    install = observed[1][1]
    assert install[:4] == [
        module.sys.executable,
        str(ROOT / "scripts/clean_first_use.py"),
        "--install",
        "all",
    ]
    assert install[4:] == [
        "--wheel",
        str(wheel.resolve()),
        "--wheel-sha256",
        hashlib.sha256(b"synthetic wheel").hexdigest(),
    ]
