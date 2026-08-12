from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import psycopg2
import pytest

from repositories import worker_schedule_repo
from tasks.provider_scheduler import (
    ProviderSchedulerConfig,
    run_checkin_sheets_sync_cycle,
)


_NOW = datetime(2099, 8, 8, 15, 40, tzinfo=timezone.utc)
_CHAT_ID = -10087141
_MESSAGE_ID = 9141


def _database_url() -> str:
    value = (os.environ.get("ATTENDANCE_TEST_DATABASE_URL") or "").strip()
    if not value:
        pytest.skip("ATTENDANCE_TEST_DATABASE_URL is required")
    return value


def _prepare_database() -> None:
    root = Path(__file__).resolve().parent
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            for name in (
                "0003_gateway_provider.sql",
                "0004_registration_provider.sql",
                "0008_worker_checkin_recovery.sql",
                "0009_durable_provider_worker.sql",
                "0010_scheduler_fencing_and_sheets_outbox.sql",
                "0011_worker_action_dependencies.sql",
            ):
                cursor.execute((root / "migrations" / name).read_text(encoding="utf-8"))
            cursor.execute(
                "DELETE FROM attendance_worker_schedule_runs "
                "WHERE run_key LIKE 'checkin-sheets:%:10087141:9141'"
            )
            cursor.execute(
                "DELETE FROM clock_records WHERE source_chat_id = %s AND source_message_id = %s",
                (_CHAT_ID, _MESSAGE_ID),
            )


def _config() -> ProviderSchedulerConfig:
    return ProviderSchedulerConfig(
        database_url=_database_url(),
        poll_interval_seconds=1,
        lease_seconds=2,
        group_summary_enabled=False,
        group_summary_hour=23,
        group_summary_minute=30,
        group_summary_timezone="Asia/Shanghai",
        group_summary_skip_dates=frozenset(),
        group_summary_route_keys={},
        daily_report_enabled=False,
        daily_report_hour=23,
        daily_report_minute=30,
        daily_report_timezone="Asia/Shanghai",
        daily_report_route_key=None,
    )


def _enqueue_job_and_clock() -> None:
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO clock_records (
                    chat_id, file_id, tg_id, employee_id, clock_time,
                    clock_action, source_chat_id, source_message_id
                ) VALUES (%s, 'outbox-file', 87141, 'outbox-employee', %s,
                          '签到', %s, %s)
                """,
                (_CHAT_ID, _NOW, _CHAT_ID, _MESSAGE_ID),
            )
            worker_schedule_repo.enqueue_run_cur(
                cursor,
                run_key="checkin-sheets:TEST_GROUP:10087141:9141",
                job_kind="CHECKIN_SHEETS_SYNC",
                payload={"chatId": _CHAT_ID, "syncKind": "TEST_GROUP"},
                now=_NOW,
            )


def test_checkin_sheets_outbox_is_commit_visible_and_restart_recoverable() -> None:
    _prepare_database()
    _enqueue_job_and_clock()
    calls: list[tuple[int, int]] = []

    async def fail_once(*, chat_id: int) -> object:
        with psycopg2.connect(_database_url()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM clock_records "
                    "WHERE source_chat_id = %s AND source_message_id = %s",
                    (chat_id, _MESSAGE_ID),
                )
                visible = int(cursor.fetchone()[0])
        calls.append((chat_id, visible))
        raise RuntimeError("sheet transport failed")

    failed = run_checkin_sheets_sync_cycle(
        _config(),
        worker_id="sheets-outbox-first-process",
        now=_NOW,
        test_group_sync=fail_once,
    )
    too_soon = run_checkin_sheets_sync_cycle(
        _config(),
        worker_id="sheets-outbox-restarted-too-soon",
        now=_NOW + timedelta(seconds=59),
        test_group_sync=fail_once,
    )

    async def succeed(*, chat_id: int) -> object:
        with psycopg2.connect(_database_url()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM clock_records "
                    "WHERE source_chat_id = %s AND source_message_id = %s",
                    (chat_id, _MESSAGE_ID),
                )
                visible = int(cursor.fetchone()[0])
        calls.append((chat_id, visible))
        return SimpleNamespace(ok=True, message="ok")

    recovered = run_checkin_sheets_sync_cycle(
        _config(),
        worker_id="sheets-outbox-restarted",
        now=_NOW + timedelta(seconds=61),
        test_group_sync=succeed,
    )
    duplicate = run_checkin_sheets_sync_cycle(
        _config(),
        worker_id="sheets-outbox-duplicate",
        now=_NOW + timedelta(seconds=62),
        test_group_sync=succeed,
    )

    assert (failed, too_soon, recovered, duplicate) == (1, 0, 1, 0)
    assert calls == [(_CHAT_ID, 1), (_CHAT_ID, 1)]
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, attempt_count, lease_owner, lease_expires_at
                FROM attendance_worker_schedule_runs
                WHERE run_key = 'checkin-sheets:TEST_GROUP:10087141:9141'
                """
            )
            assert cursor.fetchone() == ("COMPLETED", 2, None, None)


def test_checkin_sheets_outbox_rolls_back_with_the_clock_transaction() -> None:
    _prepare_database()
    connection = psycopg2.connect(_database_url())
    try:
        cursor = connection.cursor()
        worker_schedule_repo.enqueue_run_cur(
            cursor,
            run_key="checkin-sheets:TEST_GROUP:10087141:9141",
            job_kind="CHECKIN_SHEETS_SYNC",
            payload={"chatId": _CHAT_ID, "syncKind": "TEST_GROUP"},
            now=_NOW,
        )
        connection.rollback()
    finally:
        connection.close()

    with psycopg2.connect(_database_url()) as verify:
        with verify.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM attendance_worker_schedule_runs "
                "WHERE run_key = 'checkin-sheets:TEST_GROUP:10087141:9141'"
            )
            assert cursor.fetchone() == (0,)
