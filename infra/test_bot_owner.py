from __future__ import annotations

import pytest

from infra.bot_owner import load_attendance_bot_owner


def test_legacy_runtime_keeps_legacy_owner_default(monkeypatch) -> None:
    monkeypatch.delenv("ATTENDANCE_BOT_OWNER", raising=False)

    assert load_attendance_bot_owner() == "legacy_attendance"


def test_unified_webhook_requires_explicit_unified_owner(monkeypatch) -> None:
    monkeypatch.delenv("ATTENDANCE_BOT_OWNER", raising=False)

    with pytest.raises(RuntimeError, match="requires ATTENDANCE_BOT_OWNER=ux_assistant"):
        load_attendance_bot_owner(require_unified=True)


def test_unknown_owner_fails_closed(monkeypatch) -> None:
    monkeypatch.setenv("ATTENDANCE_BOT_OWNER", "unknown")

    with pytest.raises(RuntimeError, match="must be one of"):
        load_attendance_bot_owner()
