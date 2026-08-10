"""Personal and synthetic starter files bundled with the package."""

from __future__ import annotations

import secrets
from datetime import date
from importlib.resources import files

from atready.errors import StorageError


def _template(name: str) -> str:
    return files(__package__).joinpath(name).read_text(encoding="utf-8")


def starter_inventory(today: date | None = None) -> str:
    del today
    try:
        nonce = "nonce-v1:" + secrets.token_hex(32)
    except (OSError, RuntimeError):
        raise StorageError("cannot generate inventory revision privacy nonce") from None
    return _template("personal_inventory.yaml").replace("{{REVISION_PRIVACY_NONCE}}", nonce)


def demo_inventory(today: date | None = None) -> str:
    return _template("inventory.yaml").replace("{{TODAY}}", (today or date.today()).isoformat())


def starter_project(today: date | None = None) -> str:
    return _template("project.yaml").replace("{{TODAY}}", (today or date.today()).isoformat())
