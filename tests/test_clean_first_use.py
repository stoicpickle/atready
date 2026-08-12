from __future__ import annotations

import hashlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "clean_first_use.py"


def _namespace() -> dict[str, object]:
    spec = importlib.util.spec_from_file_location("clean_first_use", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return vars(module)


def test_clean_first_use_environment_replaces_real_product_state(tmp_path: Path) -> None:
    (tmp_path / "lane").mkdir()
    install = _namespace()["_isolated_install_environment"](tmp_path / "lane")
    isolated = _namespace()["_post_install_environment"](
        tmp_path / "lane",
        tmp_path / "guard",
    )

    assert install["ATREADY_HOME"].endswith("install-state-must-not-exist")
    assert install["CODEX_HOME"].endswith("codex-state-must-not-exist")
    assert install["HOME"] == str(tmp_path / "lane" / "install-home")
    assert isolated["ATREADY_HOME"] == str(tmp_path / "lane" / "state")
    assert isolated["QUARTERMASTER_HOME"].endswith("legacy-state-must-not-exist")
    assert isolated["CODEX_HOME"].endswith("codex-state-must-not-exist")
    assert isolated["PYTHONPATH"] == str(tmp_path / "guard")
    assert isolated["UV_OFFLINE"] == "1"
    assert isolated["PYTHONNOUSERSITE"] == "1"


def test_network_guard_blocks_python_socket_calls(tmp_path: Path) -> None:
    write_guard = _namespace()["_write_network_guard"]
    guard = tmp_path / "guard"
    write_guard(guard)
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(guard)
    environment["ATREADY_NETWORK_GUARD_DIR"] = str(guard)

    result = subprocess.run(
        [sys.executable, "-c", "import socket; socket.socket()"],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
        timeout=10,
    )

    assert result.returncode != 0
    assert "network disabled by AtReady clean first-use harness" in result.stderr
    assert (guard / "loaded").is_file()
    assert (guard / "attempted").read_text(encoding="utf-8") == "python-network-call\n"


def test_clean_first_use_refuses_an_existing_root(tmp_path: Path) -> None:
    run_lanes = _namespace()["run_lanes"]
    existing = tmp_path / "existing"
    existing.mkdir()

    with pytest.raises(FileExistsError):
        run_lanes(existing, ("source",), wheel=None, wheel_sha256=None)


def test_clean_first_use_help_requires_a_wheel_for_wheel_lanes() -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, str(SCRIPT), "--install", "wheel"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 2
    assert "--wheel is required for the wheel or all lane" in result.stderr


def test_clean_first_use_rejects_symlink_and_digest_mismatch(tmp_path: Path) -> None:
    wheel_sha256 = _namespace()["_wheel_sha256"]
    wheel = tmp_path / "project_atready-0.1.9-py3-none-any.whl"
    wheel.write_bytes(b"synthetic wheel bytes")
    linked = tmp_path / "linked.whl"
    try:
        linked.symlink_to(wheel)
    except OSError:
        linked = None

    assert wheel_sha256(wheel) != "0" * 64
    lane = tmp_path / "lane"
    lane.mkdir(mode=0o700)
    with pytest.raises(AssertionError, match="does not match"):
        _namespace()["_install"](
            "wheel",
            lane,
            wheel=wheel,
            wheel_sha256="0" * 64,
        )
    if linked is not None:
        with pytest.raises(AssertionError, match="symlinked"):
            wheel_sha256(linked)


@pytest.mark.skipif(os.name != "posix", reason="POSIX permits replacing an open path")
def test_wheel_install_stages_descriptor_bytes_before_path_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    namespace = _namespace()
    stage_wheel = namespace["_stage_wheel"]
    wheel = tmp_path / "project_atready-0.1.9-py3-none-any.whl"
    original = b"synthetic reviewed wheel"
    wheel.write_bytes(original)
    replacement = tmp_path / "replacement.whl"
    replacement.write_bytes(b"synthetic replacement wheel")
    lane = tmp_path / "lane"
    lane.mkdir(mode=0o700)
    real_read = os.read
    replaced = False

    def read_then_replace_path(descriptor: int, length: int) -> bytes:
        nonlocal replaced
        chunk = real_read(descriptor, length)
        if chunk and not replaced:
            replaced = True
            replacement.replace(wheel)
        return chunk

    monkeypatch.setattr(os, "read", read_then_replace_path)

    staged = stage_wheel(
        wheel,
        lane,
        expected_sha256=hashlib.sha256(original).hexdigest(),
    )

    assert replaced is True
    assert staged.read_bytes() == original
    assert wheel.read_bytes() == b"synthetic replacement wheel"
