from __future__ import annotations

import pytest

import webhook_app


@pytest.mark.parametrize(
    "key",
    (
        "GOOGLE_SHEETS_ENABLED",
        "TEST_GROUP_GOOGLE_SHEETS_ENABLED",
        "BBQ_GOOGLE_SHEETS_ENABLED",
    ),
)
def test_unified_webhook_rejects_legacy_sheets_side_effect_flags(monkeypatch, key: str) -> None:
    monkeypatch.setenv(key, "true")

    with pytest.raises(RuntimeError, match="legacy Sheets side effects"):
        webhook_app._assert_unified_webhook_has_no_legacy_sheets_side_effects()


def test_unified_webhook_accepts_all_sheets_side_effect_flags_disabled(monkeypatch) -> None:
    for key in (
        "GOOGLE_SHEETS_ENABLED",
        "TEST_GROUP_GOOGLE_SHEETS_ENABLED",
        "BBQ_GOOGLE_SHEETS_ENABLED",
    ):
        monkeypatch.setenv(key, "0")

    webhook_app._assert_unified_webhook_has_no_legacy_sheets_side_effects()


def test_unified_webhook_rejects_legacy_worker_enablement(monkeypatch) -> None:
    monkeypatch.setenv("ATTENDANCE_WEBHOOK_RUN_WORKERS", "1")

    with pytest.raises(RuntimeError, match="must not start legacy workers"):
        webhook_app._assert_webhook_workers_disabled()
