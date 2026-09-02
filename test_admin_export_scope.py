from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

import psycopg2
import pytest

import gateway_provider.export_module as gateway_export_module
from test_gateway_provider_event import (
    _apply_gateway_provider_migration,
    _database_url,
    _export_callback_event,
    _provider_client,
    _deferred_scheduler_config,
    _record_event_action_delivered,
    _seed_admin_with_export_scope,
    _TEST_GATEWAY_CREDENTIAL,
    run_deferred_interaction_cycle,
)


def test_admin_without_export_scope_is_rejected() -> None:
    _apply_gateway_provider_migration()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id, english_name, tg_id, registered_chat_id
                ) VALUES (%s, %s, %s, %s)
                """,
                ("74808", "GRANDFOR", 81002, 81002),
            )
            cursor.execute(
                "INSERT INTO admin_list (admin_employee_id) VALUES (%s)",
                ("74808",),
            )

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_export_callback_event("att:export", event_number=1601),
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"][1]["text"] == gateway_export_module.MSG_NO_EXPORT_SCOPE


def test_admin_export_uses_configured_single_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _apply_gateway_provider_migration()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            _seed_admin_with_export_scope(cursor, export_chat_id=-1004248049456)

    seen: dict[str, object] = {}

    async def capture_single_group(**kwargs: object) -> list[object]:
        seen.update(kwargs)
        return []

    monkeypatch.setattr(
        gateway_export_module.attendance_export_service,
        "collect_rows_for_single_group",
        capture_single_group,
    )

    async def must_not_collect_range(**_kwargs: object) -> list[object]:
        raise AssertionError("full-range export must not run for scoped admin")

    monkeypatch.setattr(
        gateway_export_module.attendance_export_service,
        "collect_rows_for_range",
        must_not_collect_range,
    )

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_export_callback_event("att:export:week", event_number=1602),
    )

    assert response.status_code == 200, response.text
    _record_event_action_delivered(
        event_id="evt-attendance-export-1602",
        action_id="evt-attendance-export-1602.progress",
    )
    assert run_deferred_interaction_cycle(
        _deferred_scheduler_config(),
        worker_id="scoped-export-after-progress-receipt",
        now=datetime(2026, 8, 8, 8, 0, 2, tzinfo=timezone.utc),
    ) == (1, 2)
    assert seen["chat_id"] == -1004248049456
    assert seen["start"] == date(2026, 8, 3)
    assert seen["end"] == date(2026, 8, 8)


def test_dual_scope_export_uses_its_group_and_alt_roster(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gateway_export_module,
        "is_dual_admin_export_scope",
        lambda **_kwargs: True,
    )
    seen_months: list[str] = []

    def roster_for_month(*, year_month: str, view: str) -> frozenset[str]:
        seen_months.append(year_month)
        assert view == gateway_export_module.SHIFT_VIEW_ALT
        return frozenset({f"employee-{year_month}"})

    seen: dict[str, object] = {}

    async def capture_roster_at_chat(**kwargs: object) -> list[object]:
        seen.update(kwargs)
        return []

    monkeypatch.setattr(gateway_export_module, "roster_employee_ids", roster_for_month)
    monkeypatch.setattr(
        gateway_export_module.attendance_export_service,
        "collect_rows_for_roster_at_chat",
        capture_roster_at_chat,
    )

    asyncio.run(gateway_export_module._collect_attendance_export_rows(
        export_chat_id=-1004373351741,
        start=date(2026, 7, 30),
        end=date(2026, 8, 2),
    ))

    assert set(seen_months) == {"2026-07", "2026-08"}
    assert seen == {
        "chat_id": -1004373351741,
        "start": date(2026, 7, 30),
        "end": date(2026, 8, 2),
        "roster_ids": frozenset({"employee-2026-07", "employee-2026-08"}),
    }
