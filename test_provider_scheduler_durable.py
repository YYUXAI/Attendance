from __future__ import annotations

import base64
import codecs
import json
import os
import threading
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import psycopg2
import pytest

from infra.db import database_url_scope
from infra.google_sheets_config import GoogleSheetsConfig
from services import google_sheets_shift_sync_service
from tasks import provider_scheduler
from repositories import worker_schedule_repo
from tasks.provider_scheduler import ProviderSchedulerConfig, run_scheduler_cycle


_TARGET_DATE = date(2099, 8, 8)
_NOW = datetime(2099, 8, 8, 15, 40, tzinfo=timezone.utc)
_CHAT_ID = -10087091
_NOTIFY_ROUTE_KEY = "group-route.attendance.daily-report"
_EMPLOYEE_ID = "74891"


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
                "WHERE run_key LIKE %s OR run_key LIKE %s OR run_key LIKE %s "
                "OR job_kind = 'CHECKIN_SHEETS_SYNC'",
                (
                    f"group-summary:{_TARGET_DATE.isoformat()}%",
                    f"daily-report:{_TARGET_DATE.isoformat()}%",
                    "sheets-sync:2099-08:%",
                ),
            )
            cursor.execute(
                "DELETE FROM attendance_worker_actions WHERE action_id IN (%s, %s)",
                (
                    f"attendance.group-summary.{_TARGET_DATE.isoformat()}.{abs(_CHAT_ID)}",
                    f"attendance.daily-report.{_TARGET_DATE.isoformat()}",
                ),
            )
            cursor.execute("DELETE FROM clock_records WHERE employee_id = %s", (_EMPLOYEE_ID,))
            cursor.execute(
                "DELETE FROM employee_shift_config WHERE employee_id = %s",
                (_EMPLOYEE_ID,),
            )
            cursor.execute("DELETE FROM registrations WHERE employee_id = %s", (_EMPLOYEE_ID,))
            cursor.execute("DELETE FROM shifts WHERE attendance_group_id = %s", (_CHAT_ID,))
            cursor.execute(
                """
                INSERT INTO shifts (
                    checkin_time, checkout_time, timezone, attendance_group_id
                ) VALUES ('09:00', '18:00', 'Asia/Shanghai', %s)
                RETURNING id
                """,
                (_CHAT_ID,),
            )
            shift_id = int(cursor.fetchone()[0])
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id, tg_id, english_name, tg_username,
                    registered_at, registered_chat_id, shift_id
                ) VALUES (%s, 87091, 'Alice', 'alice', %s, %s, %s)
                """,
                (_EMPLOYEE_ID, _NOW, _CHAT_ID, shift_id),
            )
            cursor.execute(
                """
                INSERT INTO employee_shift_config (
                    year_month, employee_id, english_name, shift_time_range,
                    shift_checkin_time, shift_checkout_time, monthly_rest_days,
                    region_code, shift_timezone
                ) VALUES ('2099-08', %s, 'Alice', '09:00 - 18:00',
                          '09:00', '18:00', '', 'CN', 'Asia/Shanghai')
                """,
                (_EMPLOYEE_ID,),
            )
            cursor.executemany(
                """
                INSERT INTO clock_records (
                    chat_id, file_id, tg_id, employee_id, shift_id,
                    clock_time, clock_action, source_chat_id, source_message_id
                ) VALUES (%s, %s, 87091, %s, %s, %s, %s, %s, %s)
                """,
                (
                    (
                        _CHAT_ID,
                        "scheduler-signin",
                        _EMPLOYEE_ID,
                        shift_id,
                        datetime(2099, 8, 8, 1, 0, tzinfo=timezone.utc),
                        "签到",
                        _CHAT_ID,
                        91001,
                    ),
                    (
                        _CHAT_ID,
                        "scheduler-signout",
                        _EMPLOYEE_ID,
                        shift_id,
                        datetime(2099, 8, 8, 10, 0, tzinfo=timezone.utc),
                        "签退",
                        _CHAT_ID,
                        91002,
                    ),
                ),
            )


def _config() -> ProviderSchedulerConfig:
    return ProviderSchedulerConfig(
        database_url=_database_url(),
        poll_interval_seconds=1,
        lease_seconds=30,
        group_summary_enabled=True,
        group_summary_hour=23,
        group_summary_minute=30,
        group_summary_timezone="Asia/Shanghai",
        group_summary_skip_dates=frozenset(),
        daily_report_enabled=True,
        daily_report_hour=23,
        daily_report_minute=30,
        daily_report_timezone="Asia/Shanghai",
        daily_report_route_key=_NOTIFY_ROUTE_KEY,
    )


def test_scheduler_durably_enqueues_current_summary_daily_csv_and_sheets_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_database()
    monkeypatch.setenv("CHECKIN_EXPORT_CHAT_IDS", str(_CHAT_ID))
    monkeypatch.setenv("GOOGLE_SHEETS_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_SHEETS_SYNC_INTERVAL_SECONDS", "3600")
    sheets_calls: list[str] = []

    class SheetsResult:
        ok = True
        message = "ok"

    def sheets_sync() -> SheetsResult:
        sheets_calls.append("sync")
        return SheetsResult()

    first = run_scheduler_cycle(
        _config(), worker_id="scheduler-a", now=_NOW, sheets_sync=sheets_sync
    )
    second = run_scheduler_cycle(
        _config(), worker_id="scheduler-b", now=_NOW, sheets_sync=sheets_sync
    )

    assert first.claimed_runs == 3
    assert first.enqueued_actions == 2
    assert second.claimed_runs == 0
    assert second.enqueued_actions == 0
    assert sheets_calls == ["sync"]

    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT action_kind, owner_key, action_payload
                FROM attendance_worker_actions
                WHERE action_id IN (%s, %s)
                ORDER BY action_kind
                """,
                (
                    f"attendance.group-summary.{_TARGET_DATE.isoformat()}.{abs(_CHAT_ID)}",
                    f"attendance.daily-report.{_TARGET_DATE.isoformat()}",
                ),
            )
            actions = cursor.fetchall()
            cursor.execute(
                """
                SELECT job_kind, status, attempt_count
                FROM attendance_worker_schedule_runs
                WHERE run_key LIKE %s OR run_key LIKE %s OR run_key LIKE %s
                ORDER BY job_kind
                """,
                (
                    f"group-summary:{_TARGET_DATE.isoformat()}%",
                    f"daily-report:{_TARGET_DATE.isoformat()}%",
                    "sheets-sync:2099-08:%",
                ),
            )
            schedule_runs = cursor.fetchall()

    assert [row[:2] for row in actions] == [
        ("DAILY_REPORT", _TARGET_DATE.isoformat()),
        ("GROUP_SUMMARY", f"{_TARGET_DATE.isoformat()}:{_CHAT_ID}"),
    ]
    daily = actions[0][2]
    summary = actions[1][2]
    assert daily["action"]["type"] == "SEND_GROUP_DOCUMENT"
    assert daily["action"]["routeKey"] == _NOTIFY_ROUTE_KEY
    assert daily["action"]["document"]["fileName"] == "attendance_2099-08-08.csv"
    csv_text = base64.b64decode(
        daily["action"]["document"]["contentBase64"]
    ).decode("utf-8-sig")
    assert csv_text == (
        "群名,工号,英文名,班次,上班时间,下班时间,离岗时间,状态\n"
        "群-10087091,74891,Alice,09:00 - 18:00,09:00:00,18:00:00,,正常\n"
    )
    assert summary["action"] == {
        "actionId": "attendance.group-summary.2099-08-08.10087091",
        "type": "SEND_GROUP_MESSAGE",
        "routeKey": provider_scheduler.group_route_key(_CHAT_ID),
        "text": (
            "今日考勤概览-2099/08/08\n\n"
            "1.迟到：0人\n\n"
            "2.早退：0人\n\n"
            "3.缺卡：0人\n\n"
            "4.未返岗：0人\n\n"
            "5.正常：1人\n\n"
            "6.月休：0人"
        ),
    }
    assert schedule_runs == [
        ("DAILY_REPORT", "COMPLETED", 1),
        ("GROUP_SUMMARY", "COMPLETED", 1),
        ("SHEETS_SYNC", "COMPLETED", 1),
    ]


def test_scheduler_catches_up_every_missed_local_date_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_database()
    monkeypatch.setenv("GOOGLE_SHEETS_ENABLED", "false")
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM attendance_worker_schedule_runs "
                "WHERE run_key LIKE 'group-summary:2099-08-%' "
                "OR run_key LIKE 'daily-report:2099-08-%'"
            )
    observed_group_dates: list[date] = []
    observed_daily_dates: list[date] = []

    def enqueue_summary(
        _config: ProviderSchedulerConfig,
        *,
        target_date: date,
        created_at: datetime,
    ) -> int:
        assert created_at.tzinfo is not None
        observed_group_dates.append(target_date)
        return 0

    def enqueue_daily(
        _config: ProviderSchedulerConfig,
        *,
        report_date: date,
        created_at: datetime,
    ) -> int:
        assert created_at.tzinfo is not None
        observed_daily_dates.append(report_date)
        return 0

    monkeypatch.setattr(
        provider_scheduler,
        "_enqueue_group_summaries",
        enqueue_summary,
    )
    monkeypatch.setattr(
        provider_scheduler,
        "_enqueue_daily_report",
        enqueue_daily,
    )
    config = ProviderSchedulerConfig(
        database_url=_database_url(),
        poll_interval_seconds=1,
        lease_seconds=30,
        group_summary_enabled=True,
        group_summary_hour=23,
        group_summary_minute=30,
        group_summary_timezone="Asia/Shanghai",
        group_summary_skip_dates=frozenset(),
        daily_report_enabled=True,
        daily_report_hour=23,
        daily_report_minute=30,
        daily_report_timezone="Asia/Shanghai",
        daily_report_route_key=_NOTIFY_ROUTE_KEY,
    )

    first = run_scheduler_cycle(config, worker_id="scheduler-before-outage", now=_NOW)
    recovered = run_scheduler_cycle(
        config,
        worker_id="scheduler-after-outage",
        now=_NOW + timedelta(days=3),
    )

    assert first.claimed_runs == 2
    assert recovered.claimed_runs == 6
    assert observed_group_dates == [
        date(2099, 8, 8),
        date(2099, 8, 9),
        date(2099, 8, 10),
        date(2099, 8, 11),
    ]
    assert observed_daily_dates == [
        date(2099, 8, 8),
        date(2099, 8, 9),
        date(2099, 8, 10),
        date(2099, 8, 11),
    ]


def test_scheduler_recovers_yesterday_immediately_after_midnight_before_today_due(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_database()
    monkeypatch.setenv("GOOGLE_SHEETS_ENABLED", "false")
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM attendance_worker_schedule_runs "
                "WHERE run_key LIKE 'group-summary:2099-08-%'"
            )
            cursor.execute(
                """
                INSERT INTO attendance_worker_schedule_runs (
                    run_key, job_kind, status, attempt_count,
                    next_attempt_at, created_at, completed_at, updated_at
                ) VALUES (
                    'group-summary:2099-08-07', 'GROUP_SUMMARY', 'COMPLETED', 1,
                    %s, %s, %s, %s
                )
                """,
                (_NOW, _NOW, _NOW, _NOW),
            )

    observed: list[date] = []
    monkeypatch.setattr(
        provider_scheduler,
        "_enqueue_group_summaries",
        lambda _config, *, target_date, created_at: (
            observed.append(target_date) or 0
        ),
    )
    config = ProviderSchedulerConfig(
        database_url=_database_url(),
        poll_interval_seconds=1,
        lease_seconds=30,
        group_summary_enabled=True,
        group_summary_hour=23,
        group_summary_minute=30,
        group_summary_timezone="Asia/Shanghai",
        group_summary_skip_dates=frozenset(),
        daily_report_enabled=False,
        daily_report_hour=23,
        daily_report_minute=30,
        daily_report_timezone="Asia/Shanghai",
        daily_report_route_key=None,
    )

    result = run_scheduler_cycle(
        config,
        worker_id="scheduler-after-midnight",
        now=datetime(2099, 8, 8, 16, 1, tzinfo=timezone.utc),
    )

    assert result.claimed_runs == 1
    assert observed == [date(2099, 8, 8)]


def test_schedule_claim_uses_a_fencing_token_for_same_owner_reclaim() -> None:
    _prepare_database()
    run_key = "sheets-sync:fencing:2099-08-08"
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM attendance_worker_schedule_runs WHERE run_key = %s",
                (run_key,),
            )
    first = worker_schedule_repo.claim_run(
        database_url=_database_url(),
        run_key=run_key,
        job_kind="SHEETS_SYNC",
        worker_id="same-worker",
        now=_NOW,
        lease_seconds=1,
    )
    second = worker_schedule_repo.claim_run(
        database_url=_database_url(),
        run_key=run_key,
        job_kind="SHEETS_SYNC",
        worker_id="same-worker",
        now=_NOW + timedelta(seconds=2),
        lease_seconds=30,
    )

    assert first is not None
    assert second is not None
    assert second.lease_version == first.lease_version + 1
    with pytest.raises(RuntimeError, match="lease was lost"):
        worker_schedule_repo.complete_run(
            database_url=_database_url(),
            run_key=run_key,
            worker_id="same-worker",
            lease_version=first.lease_version,
            now=_NOW + timedelta(seconds=3),
        )


def test_long_scheduler_operation_renews_lease_before_a_second_instance_can_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_database()
    monkeypatch.setenv("GOOGLE_SHEETS_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_SHEETS_SYNC_INTERVAL_SECONDS", "3600")
    run_key = f"sheets-sync:2099-08:{int(_NOW.timestamp()) // 3600}"
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM attendance_worker_schedule_runs WHERE run_key = %s",
                (run_key,),
            )
    started = threading.Event()
    release = threading.Event()
    result: list[object] = []

    class SheetsResult:
        ok = True
        message = "ok"

    def slow_sync() -> SheetsResult:
        started.set()
        assert release.wait(timeout=5)
        return SheetsResult()

    config = ProviderSchedulerConfig(
        database_url=_database_url(),
        poll_interval_seconds=1,
        lease_seconds=1,
        group_summary_enabled=False,
        group_summary_hour=23,
        group_summary_minute=30,
        group_summary_timezone="Asia/Shanghai",
        group_summary_skip_dates=frozenset(),
        daily_report_enabled=False,
        daily_report_hour=23,
        daily_report_minute=30,
        daily_report_timezone="Asia/Shanghai",
        daily_report_route_key=None,
    )
    worker = threading.Thread(
        target=lambda: result.append(
            run_scheduler_cycle(
                config,
                worker_id="scheduler-long-a",
                now=_NOW,
                sheets_sync=slow_sync,
            )
        )
    )
    worker.start()
    assert started.wait(timeout=2)
    time.sleep(1.25)

    competing = worker_schedule_repo.claim_run(
        database_url=_database_url(),
        run_key=run_key,
        job_kind="SHEETS_SYNC",
        worker_id="scheduler-long-b",
        now=_NOW + timedelta(seconds=1.25),
        lease_seconds=1,
    )
    release.set()
    worker.join(timeout=5)

    assert competing is None
    assert not worker.is_alive()
    assert result == [provider_scheduler.SchedulerCycleResult(1, 0)]


def test_scheduler_config_is_fail_closed_without_schema_or_notify_target() -> None:
    from tasks.provider_scheduler import load_scheduler_config

    with pytest.raises(RuntimeError, match="ATTENDANCE_PROVIDER_SCHEDULER_ENABLED"):
        load_scheduler_config({"ATTENDANCE_DATABASE_URL": _database_url()})
    with pytest.raises(ValueError, match="DAILY_ATTENDANCE_REPORT_ROUTE_KEY"):
        load_scheduler_config(
            {
                "ATTENDANCE_PROVIDER_SCHEDULER_ENABLED": "true",
                "ATTENDANCE_DATABASE_URL": _database_url(),
                "DAILY_ATTENDANCE_REPORT_ENABLED": "true",
                "GATEWAY_INTERNAL_BASE_URL": "http://gateway.test",
                "ATTENDANCE_TO_GATEWAY_BEARER_TOKEN": "scheduler-test-token",
            }
        )


def test_failed_scheduler_run_honors_durable_retry_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_database()
    monkeypatch.setenv("GOOGLE_SHEETS_ENABLED", "true")
    monkeypatch.setenv("GOOGLE_SHEETS_SYNC_INTERVAL_SECONDS", "3600")
    config = ProviderSchedulerConfig(
        database_url=_database_url(),
        poll_interval_seconds=1,
        lease_seconds=30,
        group_summary_enabled=False,
        group_summary_hour=23,
        group_summary_minute=30,
        group_summary_timezone="Asia/Shanghai",
        group_summary_skip_dates=frozenset(),
        daily_report_enabled=False,
        daily_report_hour=23,
        daily_report_minute=30,
        daily_report_timezone="Asia/Shanghai",
        daily_report_route_key=None,
    )
    calls: list[str] = []

    def fail_sync() -> object:
        calls.append("failed")
        raise RuntimeError("sheets unavailable")

    failed = run_scheduler_cycle(
        config, worker_id="scheduler-failed", now=_NOW, sheets_sync=fail_sync
    )
    too_soon = run_scheduler_cycle(
        config,
        worker_id="scheduler-too-soon",
        now=_NOW + timedelta(seconds=59),
        sheets_sync=fail_sync,
    )

    class SheetsResult:
        ok = True
        message = "ok"

    recovered = run_scheduler_cycle(
        config,
        worker_id="scheduler-recovered",
        now=_NOW + timedelta(seconds=61),
        sheets_sync=lambda: SheetsResult(),
    )

    assert failed.claimed_runs == 1
    assert too_soon.claimed_runs == 0
    assert recovered.claimed_runs == 1
    assert calls == ["failed"]


def test_google_sheets_sync_persists_valid_rows_and_preserves_them_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _prepare_database()
    employee_ids = ("74391", "74392")
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM employee_shift_calendar WHERE employee_id IN %s",
                (employee_ids,),
            )
            cursor.execute(
                "DELETE FROM employee_shift_roster WHERE employee_id IN %s",
                (employee_ids,),
            )
            cursor.execute(
                "DELETE FROM employee_shift_config WHERE employee_id IN %s",
                (employee_ids,),
            )

    sheet_rows = [
        ["8月排班表"],
        ["", "", "", "", "", "", "G", "13:00-22:00"],
        ["序号", "职位", "名字", "工号", "中文名", "入职时间", "一", "二"],
        ["", "", "", "", "", "", "1", "2"],
        ["UX设计组"],
        ["1", "设计师", "Alice", employee_ids[0], "艾丽丝", "2099-01-01", "G", "▲"],
        ["2", "设计师", "Bob", employee_ids[1], "鲍勃", "2099-01-01", "WG", "G"],
    ]
    monkeypatch.setattr(
        google_sheets_shift_sync_service,
        "fetch_shift_matrix_sheet",
        lambda **_kwargs: ("排班 2099-08", sheet_rows),
    )
    monkeypatch.setattr(
        google_sheets_shift_sync_service,
        "load_google_sheets_alt_config",
        lambda: None,
    )
    monkeypatch.setattr(
        google_sheets_shift_sync_service,
        "load_test_group_google_config",
        lambda: SimpleNamespace(enabled=False, shift_spreadsheet_id=""),
    )
    config = GoogleSheetsConfig(
        enabled=True,
        spreadsheet_id="sheet-2099-08",
        sheet_gid=None,
        credentials_json="credentials-not-read-by-network-seam.json",
        sync_interval_seconds=3600,
        year_month="2099-08",
    )

    with database_url_scope(_database_url()):
        result = google_sheets_shift_sync_service.sync_shifts_from_google_sheets(
            cfg=config,
            year_month="2099-08",
        )

    assert result.ok is True
    assert result.employee_count == 2
    assert result.calendar_cells == 4
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT employee_id, english_name, shift_time_range
                FROM employee_shift_config
                WHERE year_month = '2099-08' AND employee_id IN %s
                ORDER BY employee_id
                """,
                (employee_ids,),
            )
            configs_before_failure = cursor.fetchall()
            cursor.execute(
                """
                SELECT employee_id, work_date, cell_kind
                FROM employee_shift_calendar
                WHERE year_month = '2099-08' AND employee_id IN %s
                ORDER BY employee_id, work_date
                """,
                (employee_ids,),
            )
            calendar_before_failure = cursor.fetchall()

    assert configs_before_failure == [
        ("74391", "Alice", "13:00~22:00"),
        ("74392", "Bob", "13:00~01:00"),
    ]
    assert len(calendar_before_failure) == 4
    assert calendar_before_failure[1][2] == "rest"

    def source_failure(**_kwargs: object) -> object:
        raise RuntimeError("Google Sheets unavailable")

    monkeypatch.setattr(
        google_sheets_shift_sync_service,
        "fetch_shift_matrix_sheet",
        source_failure,
    )
    with database_url_scope(_database_url()):
        failed = google_sheets_shift_sync_service.sync_shifts_from_google_sheets(
            cfg=config,
            year_month="2099-08",
        )
    assert failed.ok is False

    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT employee_id, english_name, shift_time_range
                FROM employee_shift_config
                WHERE year_month = '2099-08' AND employee_id IN %s
                ORDER BY employee_id
                """,
                (employee_ids,),
            )
            assert cursor.fetchall() == configs_before_failure
