from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import threading
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

import psycopg2
import pytest
from fastapi.testclient import TestClient

import gateway_provider.app as gateway_provider_app_module
import gateway_provider.export_module as gateway_export_module
import gateway_provider.admin_export_module as gateway_admin_export_module
from gateway_provider.app import (
    AttendanceGatewayProviderConfig,
    create_attendance_gateway_provider_app,
)
from services import register_service
from tasks.provider_scheduler import (
    ProviderSchedulerConfig,
    run_deferred_interaction_cycle,
)
from gateway_provider.gateway_file_client import GatewayFileReader
from infra.attendance_group_policy import group_policy_fingerprint, normalize_group_policies


_TEST_GATEWAY_CREDENTIAL = "gateway-to-attendance-test-credential"
_TEST_ATTENDANCE_TO_GATEWAY_CREDENTIAL = "attendance-to-gateway-test-credential"
_TEST_UNUSED_GATEWAY_BASE_URL = "http://127.0.0.1:19089"
_TEST_SHIFT_WEB_PUBLIC_URL = "https://attendance.example.test"


def _set_group_policy(
    monkeypatch: pytest.MonkeyPatch,
    *,
    capabilities: list[str] | None = None,
) -> None:
    groups = [{
        "title": "Mutable title",
        "roster": "main",
        "capabilities": capabilities or ["standard-checkin"],
    }]
    policies = normalize_group_policies(groups)
    monkeypatch.setenv("ATTENDANCE_GROUPS_JSON", json.dumps(groups))
    monkeypatch.setenv("ATTENDANCE_GROUPS_FINGERPRINT", group_policy_fingerprint(policies))


@pytest.fixture(autouse=True)
def _default_group_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_group_policy(monkeypatch)


def _database_url() -> str:
    value = (os.environ.get("ATTENDANCE_TEST_DATABASE_URL") or "").strip()
    if not value:
        raise RuntimeError("ATTENDANCE_TEST_DATABASE_URL is required")
    return value


def _apply_gateway_provider_migration() -> None:
    migration_directory = Path(__file__).parent / "migrations"
    migrations = [
        (migration_directory / name).read_text(encoding="utf-8")
        for name in (
                "0003_gateway_provider.sql",
                "0004_registration_provider.sql",
                "0005_webapp_sessions.sql",
                "0006_delivery_receipts.sql",
                "0007_admin_export_parity.sql",
                "0008_worker_checkin_recovery.sql",
                "0009_durable_provider_worker.sql",
            "0010_scheduler_fencing_and_sheets_outbox.sql",
            "0011_worker_action_dependencies.sql",
            "0012_attendance_group_policy_and_business_facts.sql",
        )
    ]
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            for migration in migrations:
                cursor.execute(migration)
            cursor.execute("DELETE FROM attendance_admin_export_sessions")
            cursor.execute("DELETE FROM attendance_registration_sessions")
            cursor.execute(
                "DELETE FROM temporary_leave_records WHERE tg_id IN (%s, %s)",
                (81001, 81002),
            )
            cursor.execute(
                "DELETE FROM effective_leave_days WHERE employee_id = %s",
                ("74808",),
            )
            cursor.execute(
                "DELETE FROM gateway_processed_events WHERE event_id LIKE %s",
                ("evt-attendance-%",),
            )
            cursor.execute(
                "DELETE FROM attendance_worker_schedule_runs "
                "WHERE job_kind IN ("
                "'CHECKIN_SHEETS_SYNC', 'CHECKIN_PROCESS', "
                "'ADMIN_EXPORT_PROCESS')"
            )
            cursor.execute(
                "DELETE FROM attendance_worker_actions "
                "WHERE owner_key LIKE 'deferred-event:%'"
            )
            cursor.execute(
                "DELETE FROM attendance_gateway_delivery_receipts "
                "WHERE related_event_id LIKE 'evt-attendance-%'"
            )
            cursor.execute(
                "DELETE FROM admin_list WHERE admin_employee_id = %s",
                ("74808",),
            )
            cursor.execute(
                "DELETE FROM registrations WHERE tg_id IN (%s, %s) OR employee_id = %s",
                (81001, 81002, "74808"),
            )
            cursor.execute(
                "DELETE FROM clock_records WHERE employee_id = %s",
                ("74808",),
            )
            cursor.execute(
                "DELETE FROM employee_shift_roster WHERE employee_id = %s",
                ("74808",),
            )
            cursor.execute(
                "DELETE FROM employee_shift_calendar WHERE employee_id = %s",
                ("74808",),
            )
            cursor.execute(
                "DELETE FROM employee_shift_config WHERE employee_id = %s",
                ("74808",),
            )


def _deferred_scheduler_config() -> ProviderSchedulerConfig:
    return ProviderSchedulerConfig(
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
    )


def _record_event_action_delivered(
    *, event_id: str, action_id: str, message_id: int = 9001
) -> None:
    payload = {
        "protocolVersion": "1.0",
        "receiptId": f"receipt-{action_id}",
        "provider": "ATTENDANCE",
        "actionId": action_id,
        "relatedEventId": event_id,
        "status": "DELIVERED",
        "attemptedAt": "2026-08-08T08:00:01.000Z",
        "telegramResult": {
            "accepted": True,
            "messageId": message_id,
        },
    }
    request_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO attendance_gateway_delivery_receipts (
                    receipt_id, action_id, related_event_id, correlation_id,
                    request_hash, status, receipt_payload, processed_at
                ) VALUES (%s, %s, %s, NULL, %s, 'DELIVERED', %s::jsonb,
                          clock_timestamp())
                """,
                (
                    payload["receiptId"],
                    action_id,
                    event_id,
                    request_hash,
                    json.dumps(payload),
                ),
            )


def _record_event_action_terminal(
    *, event_id: str, action_id: str, status: str
) -> None:
    failure_code = "NETWORK_UNKNOWN" if status == "UNCERTAIN" else "INVALID_ACTION"
    payload = {
        "protocolVersion": "1.0",
        "receiptId": f"receipt-{action_id}",
        "provider": "ATTENDANCE",
        "actionId": action_id,
        "relatedEventId": event_id,
        "status": status,
        "attemptedAt": "2026-08-08T08:00:01.000Z",
        "failure": {"code": failure_code, "terminal": True},
    }
    request_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO attendance_gateway_delivery_receipts (
                    receipt_id, action_id, related_event_id, correlation_id,
                    request_hash, status, receipt_payload, processed_at
                ) VALUES (%s, %s, %s, NULL, %s, %s, %s::jsonb,
                          clock_timestamp())
                """,
                (
                    payload["receiptId"],
                    action_id,
                    event_id,
                    request_hash,
                    status,
                    json.dumps(payload),
                ),
            )


def _apply_provider_health_migrations() -> None:
    _apply_gateway_provider_migration()
    migration_directory = Path(__file__).parent / "migrations"
    migrations = [
        (migration_directory / name).read_text(encoding="utf-8")
        for name in ("0005_webapp_sessions.sql", "0006_delivery_receipts.sql")
    ]
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            for migration in migrations:
                cursor.execute(migration)
            cursor.execute(
                "DELETE FROM attendance_gateway_delivery_receipts"
            )
            cursor.execute(
                "DELETE FROM attendance_worker_actions"
            )
            cursor.execute(
                "DELETE FROM attendance_worker_schedule_runs"
            )


def test_provider_health_and_readiness_verify_owned_database() -> None:
    _apply_provider_health_migrations()
    client = _provider_client()

    health = client.get("/healthz")
    readiness = client.get("/readyz")

    assert health.status_code == 200
    assert health.json() == {"ok": True, "status": "HEALTHY"}
    assert readiness.status_code == 200
    assert readiness.json() == {
        "ok": True,
        "gatewayProtocolFingerprint": (
            "sha256:3a90c0f00bae06f7fb14ddafc969acfff076de116324eb1745532393a2930061"
        ),
        "status": "READY",
        "database": True,
        "requiredTables": {
            "gatewayProcessedEvents": True,
            "deliveryReceipts": True,
            "businessTruth": True,
            "webappSessions": True,
            "workerActions": True,
            "workerSchedules": True,
        },
        "operational": {
            "permanentDeliveryFailures": 0,
            "uncertainDeliveries": 0,
            "workerPermanentFailures": 0,
            "workerUncertain": 0,
            "workerPending": 0,
            "workerAcceptanceRetry": 0,
            "workerExpiredLeases": 0,
            "workerStaleBacklog": 0,
            "schedulerRetrying": 0,
            "schedulerFailed": 0,
            "schedulerExpiredLeases": 0,
            "schedulerStaleBacklog": 0,
        },
    }


def test_provider_readiness_exposes_terminal_delivery_failures() -> None:
    _apply_provider_health_migrations()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM attendance_gateway_delivery_receipts "
                "WHERE receipt_id = 'receipt-health-terminal-0001'"
            )


            cursor.execute(
                """
                INSERT INTO attendance_gateway_delivery_receipts (
                    receipt_id, action_id, related_event_id, correlation_id,
                    request_hash, status, receipt_payload, processed_at
                )
                VALUES (
                    'receipt-health-terminal-0001',
                    'action-health-terminal-0001',
                    NULL,
                    'health-terminal-correlation',
                    %s,
                    'PERMANENTLY_FAILED',
                    '{}'::jsonb,
                    clock_timestamp()
                )
                """,
                ("a" * 64,),
            )

    readiness = _provider_client().get("/readyz")

    assert readiness.status_code == 503
    assert readiness.json()["operational"]["permanentDeliveryFailures"] == 1
    assert readiness.json()["operational"]["uncertainDeliveries"] == 0
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM attendance_gateway_delivery_receipts "
                "WHERE receipt_id = 'receipt-health-terminal-0001'"
            )


def test_provider_readiness_fails_for_worker_terminal_without_gateway_receipt() -> None:
    _apply_provider_health_migrations()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO attendance_worker_actions (
                    action_id, correlation_id, action_kind, owner_key,
                    action_payload, status, attempt_count, last_error_code,
                    created_at, terminal_at, next_attempt_at, updated_at,
                    max_attempts
                ) VALUES (
                    'action.health.terminal.0001',
                    'health.worker.terminal.0001',
                    'SEND_MESSAGE',
                    'health:terminal:0001',
                    '{}'::jsonb,
                    'UNDELIVERABLE',
                    1,
                    'GATEWAY_HTTP_400',
                    clock_timestamp(),
                    clock_timestamp(),
                    clock_timestamp(),
                    clock_timestamp(),
                    3
                )
                """
            )

    readiness = _provider_client().get("/readyz")

    assert readiness.status_code == 503
    assert readiness.json()["operational"]["workerPermanentFailures"] == 1


def test_provider_readiness_allows_fresh_scheduler_retry() -> None:
    _apply_provider_health_migrations()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO attendance_worker_schedule_runs (
                    run_key, job_kind, status, attempt_count,
                    next_attempt_at, last_error_code, created_at,
                    updated_at, payload, lease_version
                ) VALUES (
                    'health:fresh-retry:0001',
                    'HEALTH_TEST',
                    'RETRYING',
                    1,
                    clock_timestamp() + interval '1 minute',
                    'TEST_RETRY',
                    clock_timestamp(),
                    clock_timestamp(),
                    '{}'::jsonb,
                    1
                )
                """
            )

    readiness = _provider_client().get("/readyz")

    assert readiness.status_code == 200
    assert readiness.json()["operational"]["schedulerRetrying"] == 1
    assert readiness.json()["operational"]["schedulerStaleBacklog"] == 0
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM attendance_worker_schedule_runs "
                "WHERE run_key = 'health:fresh-retry:0001'"
            )


def test_provider_readiness_exposes_expired_lease_and_stale_scheduler() -> None:
    _apply_provider_health_migrations()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO attendance_worker_actions (
                    action_id, correlation_id, action_kind, owner_key,
                    action_payload, status, attempt_count, created_at,
                    next_attempt_at, updated_at, lease_owner,
                    lease_expires_at, max_attempts
                ) VALUES (
                    'action.health.expired.0001',
                    'health.worker.expired.0001',
                    'SEND_MESSAGE',
                    'health:expired:0001',
                    '{}'::jsonb,
                    'CLAIMED',
                    1,
                    clock_timestamp() - interval '10 minutes',
                    clock_timestamp() - interval '10 minutes',
                    clock_timestamp() - interval '10 minutes',
                    'health-worker',
                    clock_timestamp() - interval '1 minute',
                    3
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO attendance_worker_schedule_runs (
                    run_key, job_kind, status, attempt_count,
                    next_attempt_at, last_error_code, created_at,
                    updated_at, payload, lease_version
                ) VALUES (
                    'health:retrying:0001',
                    'HEALTH_TEST',
                    'RETRYING',
                    1,
                    clock_timestamp() - interval '10 minutes',
                    'TEST_RETRY',
                    clock_timestamp() - interval '10 minutes',
                    clock_timestamp() - interval '10 minutes',
                    '{}'::jsonb,
                    1
                )
                """
            )

    readiness = _provider_client().get("/readyz")

    assert readiness.status_code == 503
    assert readiness.json()["operational"] == {
        "permanentDeliveryFailures": 0,
        "uncertainDeliveries": 0,
        "workerPermanentFailures": 0,
        "workerUncertain": 0,
        "workerPending": 0,
        "workerAcceptanceRetry": 0,
        "workerExpiredLeases": 1,
        "workerStaleBacklog": 0,
        "schedulerRetrying": 1,
        "schedulerFailed": 0,
        "schedulerExpiredLeases": 0,
        "schedulerStaleBacklog": 1,
    }
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM attendance_worker_actions "
                "WHERE action_id = 'action.health.expired.0001'"
            )
            cursor.execute(
                "DELETE FROM attendance_worker_schedule_runs "
                "WHERE run_key = 'health:retrying:0001'"
            )


def test_provider_health_fails_closed_when_database_is_unavailable() -> None:
    app = create_attendance_gateway_provider_app(
        AttendanceGatewayProviderConfig(
            database_url=(
                "postgresql://health:health@127.0.0.1:1/unavailable"
            ),
            gateway_to_attendance_bearer_token=_TEST_GATEWAY_CREDENTIAL,
            gateway_internal_base_url=_TEST_UNUSED_GATEWAY_BASE_URL,
            attendance_to_gateway_bearer_token=(
                _TEST_ATTENDANCE_TO_GATEWAY_CREDENTIAL
            ),
            shift_web_app_public_url=_TEST_SHIFT_WEB_PUBLIC_URL,
        )
    )

    health = TestClient(app).get("/healthz")
    readiness = TestClient(app).get("/readyz")

    assert health.status_code == 503
    assert health.json() == {"ok": False, "status": "UNHEALTHY"}
    assert readiness.status_code == 503
    assert readiness.json() == {
        "ok": False,
        "gatewayProtocolFingerprint": (
            "sha256:3a90c0f00bae06f7fb14ddafc969acfff076de116324eb1745532393a2930061"
        ),
        "status": "NOT_READY",
        "database": False,
        "requiredTables": {
            "gatewayProcessedEvents": False,
            "deliveryReceipts": False,
            "businessTruth": False,
            "webappSessions": False,
            "workerActions": False,
            "workerSchedules": False,
        },
        "operational": {
            "permanentDeliveryFailures": None,
            "uncertainDeliveries": None,
            "workerPermanentFailures": None,
            "workerUncertain": None,
            "workerPending": None,
            "workerAcceptanceRetry": None,
            "workerExpiredLeases": None,
            "workerStaleBacklog": None,
            "schedulerRetrying": None,
            "schedulerFailed": None,
            "schedulerExpiredLeases": None,
            "schedulerStaleBacklog": None,
        },
    }


def test_attendance_command_restores_the_exact_private_menu_sequence() -> None:
    _apply_gateway_provider_migration()
    app = create_attendance_gateway_provider_app(
        AttendanceGatewayProviderConfig(
            database_url=_database_url(),
            gateway_to_attendance_bearer_token=_TEST_GATEWAY_CREDENTIAL,
            gateway_internal_base_url=_TEST_UNUSED_GATEWAY_BASE_URL,
            attendance_to_gateway_bearer_token=(
                _TEST_ATTENDANCE_TO_GATEWAY_CREDENTIAL
            ),
            shift_web_app_public_url=_TEST_SHIFT_WEB_PUBLIC_URL,
        )
    )

    response = TestClient(app).post(
        "/integration/gateway/v1/events",
        headers={
            "Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"
        },
        json=_attendance_command_event(),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["protocolVersion"] == "1.0"
    assert payload["eventId"] == "evt-attendance-1001"
    assert payload["result"] == "PROCESSED"
    assert payload["session"] == {"directive": "RELEASE"}
    assert payload["actions"] == [
        {
            "actionId": "evt-attendance-1001.menu-remove",
            "type": "SEND_MESSAGE",
            "chatId": 81001,
            "replyToMessageId": 501,
            "text": "旧版底部菜单已收起。",
            "replyMarkup": {"removeKeyboard": True},
        },
        {
            "actionId": "evt-attendance-1001.menu",
            "type": "SEND_MESSAGE",
            "chatId": 81001,
            "replyToMessageId": 501,
            "text": "请选择功能（使用输入框下方按钮；输入 / 可打开命令）：",
            "replyMarkup": {
                "inlineKeyboard": [
                    [
                        {"text": "注册", "callbackData": "att:register"},
                        {"text": "个人", "callbackData": "att:profile"},
                    ]
                ]
            },
        }
    ]


def test_gateway_private_reachability_ref_is_accepted_as_opaque_event_context() -> None:
    _apply_gateway_provider_migration()
    event = _attendance_command_event()
    event["privateReachabilityRef"] = "private-reachability.active-81001"

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=event,
    )

    assert response.status_code == 200, response.text
    assert response.json()["result"] == "PROCESSED"
    assert all(
        action.get("chatId") == 81001
        for action in response.json()["actions"]
    )
    assert all(
        "reachabilityRef" not in action
        for action in response.json()["actions"]
    )


def test_gateway_private_reachability_binding_rejects_provider_installation() -> None:
    event = _attendance_command_event()
    event["installationRef"] = "telegram-installation.attendance-active"
    client = TestClient(
        create_attendance_gateway_provider_app(
            AttendanceGatewayProviderConfig(
                database_url="postgresql://invalid:invalid@127.0.0.1:1/invalid",
                gateway_to_attendance_bearer_token=_TEST_GATEWAY_CREDENTIAL,
                gateway_internal_base_url=_TEST_UNUSED_GATEWAY_BASE_URL,
                attendance_to_gateway_bearer_token=(
                    _TEST_ATTENDANCE_TO_GATEWAY_CREDENTIAL
                ),
                shift_web_app_public_url=_TEST_SHIFT_WEB_PUBLIC_URL,
            )
        )
    )

    response = client.post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=event,
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_admin_attendance_menu_exposes_namespaced_export_action() -> None:
    _apply_gateway_provider_migration()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id, english_name, tg_id, registered_chat_id
                ) VALUES (%s, %s, %s, %s)
                """,
                ("74808", "GRANDFOR", 81001, 81001),
            )
            cursor.execute(
                "INSERT INTO admin_list (admin_employee_id) VALUES (%s)",
                ("74808",),
            )

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_attendance_command_event(),
    )

    assert response.status_code == 200, response.text
    keyboard = response.json()["actions"][1]["replyMarkup"]["inlineKeyboard"]
    assert keyboard[1] == [
        {"text": "导出", "callbackData": "att:export"},
        {
            "text": "班表",
            "webAppUrl": (
                "https://attendance.example.test/shift-app/index.html"
                "?year_month=2026-08"
            ),
        },
    ]
    assert len(keyboard) == 2


def test_admin_export_schema_and_queries_use_only_current_owner_truth() -> None:
    _apply_gateway_provider_migration()

    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT to_regclass('public.qc_results'), "
                "to_regclass('public.audit_results')"
            )
            assert cursor.fetchone() == (None, None)
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public'
                  AND table_name = 'effective_leave_days'
                  AND column_name IN (
                      'shift_id', 'leave_reason',
                      'application_remark', 'application_id'
                  )
                """
            )
            assert cursor.fetchall() == []


def test_admin_export_csvs_encode_exact_current_owner_rows() -> None:
    _apply_gateway_provider_migration()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id, english_name, tg_id, registered_chat_id, shift_id
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                ("74808", "GRANDFOR", 81002, -10081002, 12),
            )
            cursor.execute(
                """
                INSERT INTO clock_records (
                    chat_id, file_id, tg_id, employee_id, shift_id,
                    clock_time, clock_action
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (-10081002, "clock-file-1", 81002, "74808", 12,
                 datetime(2026, 8, 2, 1, 0, tzinfo=timezone.utc), "签到"),
            )
            cursor.execute(
                """
                INSERT INTO temporary_leave_records (
                    employee_id, english_name, tg_id, chat_id, leave_at,
                    back_at, duration_minutes, reason, remark_required, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                ("74808", "GRANDFOR", 81002, -10081002,
                 datetime(2026, 8, 3, 2, 0, tzinfo=timezone.utc),
                 datetime(2026, 8, 3, 2, 15, tzinfo=timezone.utc),
                 15, "吃饭", False, "CLOSED"),
            )
            cursor.execute(
                """
                INSERT INTO effective_leave_days (employee_id, leave_date)
                VALUES (%s, %s)
                """,
                ("74808", "2026-08-04"),
            )
            files = gateway_admin_export_module.prepare_three_csv_exports(
                cursor,
                shift_id=12,
                start_date=datetime(2026, 8, 1).date(),
                end_date=datetime(2026, 8, 7).date(),
            )

    assert [name for name, _body in files] == [
        "clock_records_shift_12_2026-08-01_to_2026-08-07.csv",
        "temporary_leave_records_shift_12_2026-08-01_to_2026-08-07.csv",
        "effective_leave_days_shift_12_2026-08-01_to_2026-08-07.csv",
    ]
    decoded = [body.decode("utf-8-sig") for _name, body in files]
    assert decoded[0].splitlines()[0] == (
        "id,employee_id,shift_id,clock_time,clock_action,tg_id,chat_id,file_id"
    )
    assert ",74808,12," in decoded[0]
    assert decoded[1].splitlines()[0] == (
        "id,employee_id,shift_id,english_name,tg_id,chat_id,leave_at,back_at,"
        "duration_minutes,reason,remark_required,status"
    )
    assert ",74808,12,GRANDFOR," in decoded[1]
    assert decoded[2].splitlines()[0] == "id,employee_id,shift_id,leave_date"
    assert ",74808,12,2026-08-04" in decoded[2]


def test_shift_callback_restores_the_old_web_app_fallback() -> None:
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
    event = _registration_callback_event()
    telegram_update = event["telegramUpdate"]
    assert isinstance(telegram_update, dict)
    callback = telegram_update["callback_query"]
    assert isinstance(callback, dict)
    callback["data"] = "att:shift"

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=event,
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"] == [
        {
            "actionId": "evt-attendance-register-1002.callback",
            "type": "ANSWER_CALLBACK",
            "callbackQueryId": "callback-1002",
        },
        {
            "actionId": "evt-attendance-register-1002.reply",
            "type": "SEND_MESSAGE",
            "chatId": 81002,
            "replyToMessageId": 502,
            "text": "请点下方「打开班表配置」进入编辑页：",
            "replyMarkup": {
                "inlineKeyboard": [[{
                    "text": "打开班表配置",
                    "webAppUrl": (
                        "https://attendance.example.test/shift-app/index.html"
                        "?year_month=2026-08"
                    ),
                }]]
            },
        },
    ]


def test_shift_callback_rejects_non_admin() -> None:
    _apply_gateway_provider_migration()
    event = _registration_callback_event()
    telegram_update = event["telegramUpdate"]
    assert isinstance(telegram_update, dict)
    callback = telegram_update["callback_query"]
    assert isinstance(callback, dict)
    callback["data"] = "att:shift"

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=event,
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"] == [
        {
            "actionId": "evt-attendance-register-1002.callback",
            "type": "ANSWER_CALLBACK",
            "callbackQueryId": "callback-1002",
        },
        {
            "actionId": "evt-attendance-register-1002.reply",
            "type": "SEND_MESSAGE",
            "chatId": 81002,
            "replyToMessageId": 502,
            "text": "无权限操作",
        },
    ]


def test_shift_callback_reports_unconfigured_web_app() -> None:
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
    event = _registration_callback_event()
    telegram_update = event["telegramUpdate"]
    assert isinstance(telegram_update, dict)
    callback = telegram_update["callback_query"]
    assert isinstance(callback, dict)
    callback["data"] = "att:shift"
    app = create_attendance_gateway_provider_app(
        AttendanceGatewayProviderConfig(
            database_url=_database_url(),
            gateway_to_attendance_bearer_token=_TEST_GATEWAY_CREDENTIAL,
            gateway_internal_base_url=_TEST_UNUSED_GATEWAY_BASE_URL,
            attendance_to_gateway_bearer_token=(
                _TEST_ATTENDANCE_TO_GATEWAY_CREDENTIAL
            ),
            shift_web_app_public_url="",
        )
    )

    response = TestClient(app).post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=event,
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"][1] == {
        "actionId": "evt-attendance-register-1002.reply",
        "type": "SEND_MESSAGE",
        "chatId": 81002,
        "replyToMessageId": 502,
        "text": (
            "班表 Web 未配置：请在 .env 设置 SHIFT_WEB_APP_PUBLIC_URL\n"
            "（须为 Telegram 可访问的 HTTPS 地址）"
        ),
    }


@pytest.mark.parametrize(
    ("message_fields", "expected_file_line"),
    [
        ({"text": "/test"}, ""),
        (
            {
                "caption": "/test",
                "document": {"file_id": "document-file-701"},
            },
            "\nfile_id：document-file-701",
        ),
        (
            {
                "caption": "/test@ParityBot",
                "photo": [
                    {"file_id": "photo-small-701"},
                    {"file_id": "photo-large-701"},
                ],
            },
            "\nfile_id：photo-large-701",
        ),
    ],
)
def test_admin_diagnostic_restores_exact_text_caption_and_attachment_behavior(
    message_fields: dict[str, object],
    expected_file_line: str,
) -> None:
    _apply_gateway_provider_migration()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id, english_name, tg_id, registered_chat_id
                ) VALUES (%s, %s, %s, %s)
                """,
                ("74808", "GRANDFOR", 87099, -10087001),
            )
            cursor.execute(
                "INSERT INTO admin_list (admin_employee_id) VALUES (%s)",
                ("74808",),
            )
    event = _group_action_command_event("ignored")
    event["eventId"] = "evt-attendance-admin-test-701"
    event["receivedAt"] = "2026-08-08T09:00:00Z"
    telegram_update = event["telegramUpdate"]
    assert isinstance(telegram_update, dict)
    message = telegram_update["message"]
    assert isinstance(message, dict)
    message["from"] = {
        "id": 87099,
        "is_bot": False,
        "first_name": "Parity",
        "username": "parity_admin",
    }
    message.pop("text", None)
    message.update(message_fields)

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=event,
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"][0]["text"] == (
        "telegram_id：87099\n\n"
        "用户名：@parity_admin\n"
        "chat_id：-10081002\n"
        "utc_now：2026-08-08 09:00:00"
        f"{expected_file_line}"
    )


def test_group_start_restores_the_exact_reply_keyboard_menu() -> None:
    _apply_gateway_provider_migration()

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_group_action_command_event("/start"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"] == [
        {
            "actionId": "evt-attendance-group-1203.menu",
            "type": "SEND_MESSAGE",
            "chatId": -10081002,
            "replyToMessageId": 703,
            "text": "功能菜单（底部按钮或 /start）",
            "replyMarkup": {
                "keyboard": [
                    [{"text": "签到"}, {"text": "签退"}],
                    [{"text": "离岗"}, {"text": "返岗"}],
                ],
                "resizeKeyboard": True,
                "isPersistent": True,
                "inputFieldPlaceholder": "选下方按钮或输入消息",
            },
        }
    ]


def test_homepage_attendance_button_reuses_the_private_menu_and_answers_callback() -> None:
    _apply_gateway_provider_migration()
    event = _profile_callback_event()
    event["eventId"] = "evt-attendance-menu-1101"
    callback = event["telegramUpdate"]["callback_query"]
    callback["data"] = "att:menu"

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=event,
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["session"] == {"directive": "RELEASE"}
    assert payload["actions"] == [
        {
            "actionId": "evt-attendance-menu-1101.callback",
            "type": "ANSWER_CALLBACK",
            "callbackQueryId": "callback-1101",
        },
        {
            "actionId": "evt-attendance-menu-1101.menu-remove",
            "type": "SEND_MESSAGE",
            "chatId": 81002,
            "replyToMessageId": 502,
            "text": "旧版底部菜单已收起。",
            "replyMarkup": {"removeKeyboard": True},
        },
        {
            "actionId": "evt-attendance-menu-1101.menu",
            "type": "SEND_MESSAGE",
            "chatId": 81002,
            "replyToMessageId": 502,
            "text": "请选择功能（使用输入框下方按钮；输入 / 可打开命令）：",
            "replyMarkup": {
                "inlineKeyboard": [[
                    {"text": "注册", "callbackData": "att:register"},
                    {"text": "个人", "callbackData": "att:profile"},
                ]]
            },
        },
    ]


@pytest.mark.parametrize("entry", ["command", "callback"])
def test_private_menu_entry_clears_only_the_actor_registration_waiting_state(
    entry: str,
) -> None:
    _apply_gateway_provider_migration()
    target_tg_id = 81001 if entry == "command" else 81002
    other_tg_id = 81002 if entry == "command" else 81001
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            register_service.mark_waiting_register_input(
                cursor,
                tg_id=target_tg_id,
                private_chat_id=target_tg_id,
            )
            register_service.mark_waiting_register_input(
                cursor,
                tg_id=other_tg_id,
                private_chat_id=other_tg_id,
            )

    event = (
        _attendance_command_event()
        if entry == "command"
        else _profile_callback_event()
    )
    if entry == "callback":
        event["eventId"] = "evt-attendance-menu-clear-1101"
        event["telegramUpdate"]["callback_query"]["data"] = "att:menu"

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=event,
    )

    assert response.status_code == 200, response.text
    assert response.json()["session"] == {"directive": "RELEASE"}
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT tg_id
                FROM attendance_registration_sessions
                WHERE tg_id IN (%s, %s)
                ORDER BY tg_id
                """,
                (target_tg_id, other_tg_id),
            )
            assert cursor.fetchall() == [(other_tg_id,)]


@pytest.mark.parametrize(
    ("event_number", "update_kind"),
    [
        (1210, "unknown_command"),
        (1211, "reply_text"),
        (1212, "mention_text"),
        (1214, "edited_message"),
    ],
)
def test_owned_group_non_attendance_input_is_silently_ignored(
    event_number: int,
    update_kind: str,
) -> None:
    _apply_gateway_provider_migration()
    event = _group_action_command_event("ordinary text")
    event["eventId"] = f"evt-attendance-group-ignored-{event_number}"
    telegram_update = event["telegramUpdate"]
    telegram_update["update_id"] = event_number
    message = telegram_update["message"]
    message["message_id"] = event_number
    if update_kind == "unknown_command":
        message["text"] = "/unknown"
    elif update_kind == "reply_text":
        message["text"] = "ordinary reply"
        message["reply_to_message"] = {
            "message_id": 700,
            "date": 1786176000,
            "chat": message["chat"],
            "from": {
                "id": 90001,
                "is_bot": True,
                "first_name": "Gateway",
            },
            "text": "bot prompt",
        }
    elif update_kind == "mention_text":
        message["text"] = "@uxassistant_bot unrelated"
    else:
        telegram_update["edited_message"] = telegram_update.pop("message")

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=event,
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "protocolVersion": "1.0",
        "eventId": f"evt-attendance-group-ignored-{event_number}",
        "result": "PROCESSED",
        "session": {"directive": "UNCHANGED"},
        "actions": [],
    }


def test_group_media_without_checkin_caption_restores_old_visible_copy() -> None:
    _apply_gateway_provider_migration()
    event = _group_action_command_event("ordinary text")
    event["eventId"] = "evt-attendance-group-media-no-matter-1213"
    telegram_update = event["telegramUpdate"]
    telegram_update["update_id"] = 1213
    message = telegram_update["message"]
    message["message_id"] = 1213
    message.pop("text", None)
    message["document"] = {
        "file_id": "unrelated-document",
        "file_unique_id": "unrelated-document-unique",
        "file_name": "unrelated.txt",
    }

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=event,
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"] == [{
        "actionId": "evt-attendance-group-media-no-matter-1213.reply",
        "type": "SEND_MESSAGE",
        "chatId": -10081002,
        "replyToMessageId": 1213,
        "text": (
            "打卡未处理：请用「↗ 签到/签退」模板发送，"
            "或确保图片说明里包含「签到」或「签退」。"
        ),
    }]


def _attendance_command_event() -> dict[str, object]:
    return {
        "protocolVersion": "1.0",
        "eventId": "evt-attendance-1001",
        "target": "ATTENDANCE",
        "routeReason": "COMMAND",
        "conversationId": "telegram:private:81001",
        "receivedAt": "2026-08-08T07:00:00Z",
        "telegramUpdate": {
            "update_id": 1001,
            "message": {
                "message_id": 501,
                "date": 1786172400,
                "chat": {"id": 81001, "type": "private"},
                "from": {
                    "id": 81001,
                    "is_bot": False,
                    "first_name": "Contract",
                },
                "text": "/attendance",
            },
        },
    }


def _provider_client(
    gateway_base_url: str = _TEST_UNUSED_GATEWAY_BASE_URL,
) -> TestClient:
    return TestClient(
        create_attendance_gateway_provider_app(
            AttendanceGatewayProviderConfig(
                database_url=_database_url(),
                gateway_to_attendance_bearer_token=_TEST_GATEWAY_CREDENTIAL,
                gateway_internal_base_url=gateway_base_url,
                attendance_to_gateway_bearer_token=(
                    _TEST_ATTENDANCE_TO_GATEWAY_CREDENTIAL
                ),
                shift_web_app_public_url=_TEST_SHIFT_WEB_PUBLIC_URL,
            )
        )
    )


@contextmanager
def _gateway_file_server(
    *,
    file_ref: str,
    payload: bytes,
) -> Iterator[tuple[str, list[str | None]]]:
    authorizations: list[str | None] = []
    digest = base64.b64encode(hashlib.sha256(payload).digest()).decode("ascii")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            authorizations.append(self.headers.get("Authorization"))
            if self.path != f"/internal/v1/telegram-files/{file_ref}":
                self.send_error(404)
                return
            if self.headers.get("Authorization") != (
                f"Bearer {_TEST_ATTENDANCE_TO_GATEWAY_CREDENTIAL}"
            ):
                self.send_error(401)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Digest", f"sha-256={digest}")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}", authorizations
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_gateway_bearer_is_required() -> None:
    _apply_gateway_provider_migration()

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        json=_attendance_command_event(),
    )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "UNAUTHORIZED",
            "message": "Gateway 凭据无效。",
        }
    }


@pytest.mark.parametrize(
    ("callback_data", "event_number"),
    [
        ("rest:apply", 1221),
        ("temporary_leave:approve:legacy", 1222),
        ("qc:confirm:legacy", 1223),
        ("notification:retry:legacy", 1224),
    ],
    ids=[
        "leave-application",
        "temporary-leave-approval",
        "qc",
        "legacy-notification",
    ],
)
def test_retired_private_callbacks_fail_closed_without_persisting_event(
    callback_data: str,
    event_number: int,
) -> None:
    _apply_gateway_provider_migration()
    event = _export_callback_event(callback_data, event_number=event_number)

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=event,
    )

    assert response.status_code == 409, response.text
    assert response.json() == {
        "error": {
            "code": "ROUTE_OWNERSHIP_MISMATCH",
            "message": "事件不属于 Attendance 路由。",
            "details": {
                "provider": "ATTENDANCE",
                "eventId": f"evt-attendance-export-{event_number}",
            },
        }
    }
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM gateway_processed_events WHERE event_id = %s",
                (f"evt-attendance-export-{event_number}",),
            )
            assert cursor.fetchone() == (0,)


def test_attendance_summary_owns_its_shell_copy_and_actions() -> None:
    _apply_gateway_provider_migration()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO organizations (department_name) VALUES (%s) RETURNING id",
                ("Gateway Contract Department",),
            )
            organization_id = cursor.fetchone()[0]
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id, english_name, tg_id, registered_chat_id, organization_id
                ) VALUES (%s, %s, %s, %s, %s)
                """,
                ("74808", "GRANDFOR", 81001, 81001, organization_id),
            )

    client = _provider_client()
    authorized = client.get(
        "/integration/gateway/v1/attendance-summary",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        params={"telegramUserId": 81001},
    )
    unregistered = client.get(
        "/integration/gateway/v1/attendance-summary",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        params={"telegramUserId": 81999},
    )
    unauthorized = client.get(
        "/integration/gateway/v1/attendance-summary",
        params={"telegramUserId": 81001},
    )

    assert authorized.status_code == 200, authorized.text
    assert authorized.json() == {
        "protocolVersion": "1.0",
        "shellPresentation": {
            "lines": [
                {"order": 200, "text": "组织归属：Gateway Contract Department"},
                {"order": 300, "text": "考勤资料：已绑定"},
            ],
            "actionRows": [
                {
                    "order": 100,
                    "buttons": [{"text": "考勤菜单", "callbackData": "att:menu"}],
                }
            ],
        },
    }
    assert unregistered.status_code == 200, unregistered.text
    assert unregistered.json() == {
        "protocolVersion": "1.0",
        "shellPresentation": {
            "lines": [
                {"order": 200, "text": "组织归属：未设置"},
                {"order": 300, "text": "考勤资料：未绑定"},
            ],
            "actionRows": [
                {
                    "order": 100,
                    "buttons": [{"text": "考勤菜单", "callbackData": "att:menu"}],
                },
                {
                    "order": 300,
                    "buttons": [
                        {"text": "绑定考勤资料", "callbackData": "att:register"}
                    ],
                },
            ],
        },
    }
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "UNAUTHORIZED"


def test_attendance_summary_failure_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_summary_read(**_kwargs: object) -> object:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        gateway_provider_app_module,
        "read_attendance_summary",
        fail_summary_read,
    )

    response = _provider_client().get(
        "/integration/gateway/v1/attendance-summary",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        params={"telegramUserId": 81001},
    )

    assert response.status_code == 500, response.text
    assert response.json() == {
        "error": {
            "code": "INTERNAL_ERROR",
            "message": "Attendance 汇总读取失败。",
        }
    }


def test_authentication_precedes_request_body_validation() -> None:
    _apply_gateway_provider_migration()

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        json={"not": "a gateway event"},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_duplicate_event_returns_the_stored_deterministic_actions() -> None:
    _apply_gateway_provider_migration()
    client = _provider_client()
    headers = {"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"}

    first = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_attendance_command_event(),
    )
    duplicate = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_attendance_command_event(),
    )

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json() == {**first.json(), "result": "DUPLICATE"}


def test_reusing_event_id_for_different_request_fails_closed() -> None:
    _apply_gateway_provider_migration()
    client = _provider_client()
    headers = {"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"}
    changed_event = _attendance_command_event()
    changed_event["receivedAt"] = "2026-08-08T07:00:01Z"

    first = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_attendance_command_event(),
    )
    conflict = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=changed_event,
    )

    assert first.status_code == 200
    assert conflict.status_code == 409
    assert conflict.json() == {
        "error": {
            "code": "EVENT_ID_CONFLICT",
            "message": "eventId 已绑定到不同请求。",
            "details": {
                "provider": "ATTENDANCE",
                "eventId": "evt-attendance-1001",
            },
        }
    }


def test_registration_callback_acquires_a_conversation_session() -> None:
    _apply_gateway_provider_migration()
    client = _provider_client()

    response = client.post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_registration_callback_event(),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["session"] == {"directive": "ACQUIRE", "ttlSeconds": 900}
    assert payload["actions"] == [
        {
            "actionId": "evt-attendance-register-1002.callback",
            "type": "ANSWER_CALLBACK",
            "callbackQueryId": "callback-1002",
        },
        {
            "actionId": "evt-attendance-register-1002.reply",
            "type": "SEND_MESSAGE",
            "chatId": 81002,
            "replyToMessageId": 502,
            "text": (
                "请私聊发送一行（不要复制「请输入」「示例」等提示）：\n"
                "英文名$工号\n"
                "例如：GRANDFOR$74808"
            ),
        },
    ]


@pytest.mark.parametrize(
    "text",
    [
        "注册",
        "绑定考勤资料",
        "/attendance_register",
        "/attendance_register@uxassistant_bot",
    ],
)
def test_private_registration_text_entries_restore_the_old_prompt(text: str) -> None:
    _apply_gateway_provider_migration()
    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_registration_begin_message_event(text),
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["session"] == {"directive": "ACQUIRE", "ttlSeconds": 900}
    assert payload["actions"] == [{
        "actionId": "evt-attendance-register-message-1008.reply",
        "type": "SEND_MESSAGE",
        "chatId": 81002,
        "replyToMessageId": 508,
        "text": (
            "请私聊发送一行（不要复制「请输入」「示例」等提示）：\n"
            "英文名$工号\n"
            "例如：GRANDFOR$74808"
        ),
    }]


@pytest.mark.parametrize(
    ("event_number", "text", "expected_text"),
    [
        (1010, "个人", "你还未完成注册，请先注册后再查看我的信息。"),
        (1011, "我的信息", "你还未完成注册，请先注册后再查看我的信息。"),
        (1012, "导出", "无权限操作"),
        (1013, "班表", "无权限操作"),
        (1014, "班次", "无权限操作"),
    ],
)
def test_registration_session_menu_text_escapes_restore_old_handlers(
    event_number: int,
    text: str,
    expected_text: str,
) -> None:
    _apply_gateway_provider_migration()
    client = _provider_client()
    headers = {"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"}
    begin = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_registration_callback_event(),
    )
    response = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_registration_session_message_event(
            event_number=event_number,
            text=text,
        ),
    )

    assert begin.status_code == 200, begin.text
    assert response.status_code == 200, response.text
    assert response.json()["session"] == {"directive": "RELEASE"}
    assert response.json()["actions"] == [{
        "actionId": f"evt-attendance-register-{event_number}.reply",
        "type": "SEND_MESSAGE",
        "chatId": 81002,
        "replyToMessageId": event_number,
        "text": expected_text,
    }]


def test_registration_migration_repeat_preserves_an_active_session() -> None:
    _apply_gateway_provider_migration()
    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_registration_callback_event(),
    )
    assert response.status_code == 200
    migration = (
        Path(__file__).parent / "migrations" / "0004_registration_provider.sql"
    ).read_text(encoding="utf-8")

    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(migration)
            cursor.execute(
                "SELECT tg_id, stage FROM attendance_registration_sessions WHERE tg_id = %s",
                (81002,),
            )
            assert cursor.fetchone() == (81002, "awaiting_input")


def _registration_callback_event() -> dict[str, object]:
    return {
        "protocolVersion": "1.0",
        "eventId": "evt-attendance-register-1002",
        "target": "ATTENDANCE",
        "routeReason": "CALLBACK_NAMESPACE",
        "conversationId": "telegram:private:81002",
        "receivedAt": "2026-08-08T07:01:00Z",
        "telegramUpdate": {
            "update_id": 1002,
            "callback_query": {
                "id": "callback-1002",
                "from": {
                    "id": 81002,
                    "is_bot": False,
                    "first_name": "Register",
                },
                "message": {
                    "message_id": 502,
                    "date": 1786172460,
                    "chat": {"id": 81002, "type": "private"},
                    "text": "考勤功能",
                },
                "chat_instance": "instance-1002",
                "data": "att:register",
            },
        },
    }


def _registration_begin_message_event(text: str) -> dict[str, object]:
    return {
        "protocolVersion": "1.0",
        "eventId": "evt-attendance-register-message-1008",
        "target": "ATTENDANCE",
        "routeReason": "COMMAND",
        "conversationId": "telegram:private:81002",
        "receivedAt": "2026-08-08T07:01:00Z",
        "telegramUpdate": {
            "update_id": 1008,
            "message": {
                "message_id": 508,
                "date": 1786172460,
                "chat": {"id": 81002, "type": "private"},
                "from": {
                    "id": 81002,
                    "is_bot": False,
                    "first_name": "Register",
                    "username": "contract_register",
                },
                "text": text,
            },
        },
    }


def _registration_session_message_event(
    *,
    event_number: int,
    text: str,
) -> dict[str, object]:
    return {
        "protocolVersion": "1.0",
        "eventId": f"evt-attendance-register-{event_number}",
        "target": "ATTENDANCE",
        "routeReason": "CONVERSATION_SESSION",
        "conversationId": "telegram:private:81002",
        "receivedAt": "2026-08-08T07:02:00Z",
        "telegramUpdate": {
            "update_id": event_number,
            "message": {
                "message_id": event_number,
                "date": 1786172520,
                "chat": {"id": 81002, "type": "private"},
                "from": {
                    "id": 81002,
                    "is_bot": False,
                    "first_name": "Register",
                },
                "text": text,
            },
        },
    }


def _profile_callback_event() -> dict[str, object]:
    event = _registration_callback_event()
    event["eventId"] = "evt-attendance-profile-1101"
    telegram_update = event["telegramUpdate"]
    assert isinstance(telegram_update, dict)
    telegram_update["update_id"] = 1101
    callback = telegram_update["callback_query"]
    assert isinstance(callback, dict)
    callback["id"] = "callback-1101"
    callback["data"] = "att:profile"
    return event


def _export_callback_event(
    data: str,
    *,
    event_number: int,
    tg_id: int = 81002,
) -> dict[str, object]:
    event = _registration_callback_event()
    event["eventId"] = f"evt-attendance-export-{event_number}"
    event["receivedAt"] = "2026-08-08T08:00:00Z"
    telegram_update = event["telegramUpdate"]
    assert isinstance(telegram_update, dict)
    telegram_update["update_id"] = event_number
    callback = telegram_update["callback_query"]
    assert isinstance(callback, dict)
    callback["id"] = f"callback-{event_number}"
    callback["data"] = data
    sender = callback["from"]
    assert isinstance(sender, dict)
    sender["id"] = tg_id
    message = callback["message"]
    assert isinstance(message, dict)
    message["message_id"] = event_number
    message["chat"] = {"id": tg_id, "type": "private"}
    return event


def _group_action_callback_event(
    data: str,
    *,
    event_number: int = 1201,
    received_at: str = "2026-08-08T08:00:00Z",
) -> dict[str, object]:
    return {
        "protocolVersion": "1.0",
        "eventId": f"evt-attendance-group-{event_number}",
        "target": "ATTENDANCE",
        "routeReason": "CALLBACK_NAMESPACE",
        "conversationId": "telegram:chat:-10081002",
        "receivedAt": received_at,
        "telegramUpdate": {
            "update_id": event_number,
            "callback_query": {
                "id": f"callback-{event_number}",
                "from": {
                    "id": 81002,
                    "is_bot": False,
                    "first_name": "Group",
                },
                "message": {
                    "message_id": 701,
                    "date": 1786176000,
                    "chat": {
                        "id": -10081002,
                        "type": "supergroup",
                        "title": "Mutable title",
                    },
                    "text": "考勤操作",
                },
                "chat_instance": "instance-1201",
                "data": data,
            },
        },
    }


def _inline_query_event() -> dict[str, object]:
    return {
        "protocolVersion": "1.0",
        "eventId": "evt-attendance-inline-1202",
        "target": "ATTENDANCE",
        "routeReason": "INLINE_QUERY",
        "conversationId": "telegram:inline:81002",
        "receivedAt": "2026-08-08T08:01:00Z",
        "telegramUpdate": {
            "update_id": 1202,
            "inline_query": {
                "id": "inline-1202",
                "from": {
                    "id": 81002,
                    "is_bot": False,
                    "first_name": "Inline",
                },
                "query": "#打卡",
                "offset": "",
            },
        },
    }


def _group_action_command_event(text: str) -> dict[str, object]:
    return {
        "protocolVersion": "1.0",
        "eventId": "evt-attendance-group-1203",
        "target": "ATTENDANCE",
        "routeReason": "GROUP_OWNER",
        "groupRouteRef": "telegram-group-route.attendance-test",
        "groupClassification": "ATTENDANCE",
        "conversationId": "telegram:chat:-10081002",
        "receivedAt": "2026-08-08T08:02:00Z",
        "telegramUpdate": {
            "update_id": 1203,
            "message": {
                "message_id": 703,
                "date": 1786176120,
                "chat": {
                    "id": -10081002,
                    "type": "supergroup",
                    "title": "Mutable title",
                },
                "from": {
                    "id": 81002,
                    "is_bot": False,
                    "first_name": "Group",
                },
                "text": text,
            },
        },
    }


def _group_report_event(
    *,
    event_number: int,
    text: str,
    received_at: str,
    tg_id: int = 81002,
) -> dict[str, object]:
    return {
        "protocolVersion": "1.0",
        "eventId": f"evt-attendance-report-{event_number}",
        "target": "ATTENDANCE",
        "routeReason": "GROUP_OWNER",
        "groupRouteRef": "telegram-group-route.attendance-test",
        "groupClassification": "ATTENDANCE",
        "conversationId": "telegram:chat:-10081002",
        "receivedAt": received_at,
        "telegramUpdate": {
            "update_id": event_number,
            "message": {
                "message_id": event_number,
                "date": 1786176000 + event_number,
                "chat": {
                    "id": -10081002,
                    "type": "supergroup",
                    "title": "Mutable title",
                },
                "from": {
                    "id": tg_id,
                    "is_bot": False,
                    "first_name": "Report",
                },
                "text": text,
            },
        },
    }


def _group_checkin_event(
    *,
    event_number: int,
    file_ref: str,
    tg_id: int = 81002,
    edited: bool = False,
) -> dict[str, object]:
    update_key = "edited_message" if edited else "message"
    return {
        "protocolVersion": "1.0",
        "eventId": f"evt-attendance-checkin-{event_number}",
        "target": "ATTENDANCE",
        "routeReason": "GROUP_OWNER",
        "groupRouteRef": "telegram-group-route.attendance-test",
        "groupClassification": "ATTENDANCE",
        "conversationId": "telegram:chat:-10081002",
        "receivedAt": "2026-08-08T08:00:01Z",
        "telegramUpdate": {
            "update_id": event_number,
            update_key: {
                "message_id": event_number,
                "date": 1786176000,
                "chat": {
                    "id": -10081002,
                    "type": "supergroup",
                    "title": "Mutable title",
                },
                "from": {
                    "id": tg_id,
                    "is_bot": False,
                    "first_name": "Checkin",
                },
                "caption": (
                    "#打卡\n英文名：GRANDFOR\n工号：74808\n事项：签到"
                ),
                "photo": [
                    {
                        "file_id": "gateway-private-telegram-file-id",
                        "file_unique_id": "gateway-private-unique-id",
                        "width": 1280,
                        "height": 720,
                        "file_size": 20,
                    }
                ],
            },
        },
        "telegramFiles": [
            {
                "fileRef": file_ref,
                "kind": "PHOTO",
                "mimeType": "image/jpeg",
                "sizeBytes": 20,
            }
        ],
    }


def _registration_text_event() -> dict[str, object]:
    return {
        "protocolVersion": "1.0",
        "eventId": "evt-attendance-register-1003",
        "target": "ATTENDANCE",
        "routeReason": "CONVERSATION_SESSION",
        "conversationId": "telegram:private:81002",
        "receivedAt": "2026-08-08T07:02:00Z",
        "telegramUpdate": {
            "update_id": 1003,
            "message": {
                "message_id": 503,
                "date": 1786172520,
                "chat": {"id": 81002, "type": "private"},
                "from": {
                    "id": 81002,
                    "is_bot": False,
                    "first_name": "Register",
                    "username": "contract_register",
                },
                "text": "GRANDFOR$74808",
            },
        },
    }


def _registration_finish_event(
    callback_data: str,
    *,
    event_number: int = 1004,
    tg_id: int = 81002,
) -> dict[str, object]:
    return {
        "protocolVersion": "1.0",
        "eventId": f"evt-attendance-register-{event_number}",
        "target": "ATTENDANCE",
        "routeReason": "CALLBACK_NAMESPACE",
        "conversationId": f"telegram:private:{tg_id}",
        "receivedAt": "2026-08-08T07:03:00Z",
        "telegramUpdate": {
            "update_id": event_number,
            "callback_query": {
                "id": f"callback-{event_number}",
                "from": {
                    "id": tg_id,
                    "is_bot": False,
                    "first_name": "Register",
                    "username": "contract_register",
                },
                "message": {
                    "message_id": 504,
                    "date": 1786172580,
                    "chat": {"id": tg_id, "type": "private"},
                    "text": "请确认",
                },
                "chat_instance": f"instance-{event_number}",
                "data": callback_data,
            },
        },
    }


def test_registration_session_text_returns_a_namespaced_preview() -> None:
    _apply_gateway_provider_migration()
    client = _provider_client()
    headers = {"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"}

    begin = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_registration_callback_event(),
    )
    preview = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json={
            "protocolVersion": "1.0",
            "eventId": "evt-attendance-register-1003",
            "target": "ATTENDANCE",
            "routeReason": "CONVERSATION_SESSION",
            "conversationId": "telegram:private:81002",
            "receivedAt": "2026-08-08T07:02:00Z",
            "telegramUpdate": {
                "update_id": 1003,
                "message": {
                    "message_id": 503,
                    "date": 1786172520,
                    "chat": {"id": 81002, "type": "private"},
                    "from": {
                        "id": 81002,
                        "is_bot": False,
                        "first_name": "Register",
                    },
                    "text": "GRANDFOR$74808",
                },
            },
        },
    )

    assert begin.status_code == 200
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["session"] == {"directive": "ACQUIRE", "ttlSeconds": 900}
    action = payload["actions"][0]
    assert action["type"] == "SEND_MESSAGE"
    assert action["text"] == "请确认：\n\n英文名：GRANDFOR\n工号：74808\n"
    buttons = action["replyMarkup"]["inlineKeyboard"][0]
    confirm_data = buttons[0]["callbackData"]
    cancel_data = buttons[1]["callbackData"]
    assert confirm_data.startswith("att:register:confirm:")
    assert cancel_data == confirm_data.replace(
        "att:register:confirm:",
        "att:register:cancel:",
    )


def test_gateway_can_idempotently_end_the_owned_private_registration_session() -> None:
    _apply_gateway_provider_migration()
    client = _provider_client()
    headers = {"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"}
    begin = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_registration_callback_event(),
    )
    assert begin.status_code == 200, begin.text

    first = client.post(
        "/integration/gateway/v1/private-registration-session/end",
        headers=headers,
        json={
            "protocolVersion": "1.0",
            "telegramUserId": "81002",
            "privateChatId": "81002",
        },
    )
    second = client.post(
        "/integration/gateway/v1/private-registration-session/end",
        headers=headers,
        json={
            "protocolVersion": "1.0",
            "telegramUserId": "81002",
            "privateChatId": "81002",
        },
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json() == {"protocolVersion": "1.0", "status": "ENDED"}
    assert second.json() == first.json()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM attendance_registration_sessions WHERE tg_id = %s",
                (81002,),
            )
            assert cursor.fetchone() == (0,)


def test_provider_does_not_expose_noncanonical_registration_session_status() -> None:
    client = _provider_client()
    headers = {"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"}
    response = client.post(
        "/integration/gateway/v1/private-registration-session/status",
        headers=headers,
        json={
            "protocolVersion": "1.0",
            "telegramUserId": "81002",
            "privateChatId": "81002",
        },
    )
    assert response.status_code == 404


def test_provider_rejects_a_concurrently_locked_event_without_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gateway_provider import event_module
    from gateway_provider.contracts import GatewayEventRequest

    class Cursor:
        def execute(self, _query: str, _params: object) -> None:
            return None

        def fetchone(self) -> tuple[bool]:
            return (False,)

        def __enter__(self) -> "Cursor":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

        def __enter__(self) -> "Connection":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(event_module.psycopg2, "connect", lambda _url: Connection())
    module = event_module.AttendanceGatewayEventModule(
        "postgresql://parity.invalid/attendance",
        object(),
        shift_web_app_public_url="https://attendance.example.test",
    )
    request = GatewayEventRequest.model_validate(
        _registration_callback_event(),
        strict=True,
    )

    with pytest.raises(RuntimeError, match="busy"):
        module.process_event(request)


def test_provider_exposes_event_lock_contention_as_retryable_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gateway_provider import event_module

    _apply_gateway_provider_migration()

    def raise_busy(
        _module: event_module.AttendanceGatewayEventModule,
        request: object,
    ) -> object:
        event_id = getattr(request, "eventId")
        raise event_module.GatewayEventBusyError(str(event_id))

    monkeypatch.setattr(
        event_module.AttendanceGatewayEventModule,
        "process_event",
        raise_busy,
    )

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_registration_callback_event(),
    )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "1"
    assert response.json() == {
        "error": {
            "code": "EVENT_BUSY",
            "message": "Attendance 事件正在处理中，请重试。",
            "details": {
                "provider": "ATTENDANCE",
                "eventId": "evt-attendance-register-1002",
            },
        }
    }


def test_profile_callback_reads_the_bound_attendance_identity() -> None:
    _apply_gateway_provider_migration()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id,
                    english_name,
                    tg_id,
                    tg_username,
                    registered_chat_id
                )
                VALUES (%s, %s, %s, %s, %s)
                """,
                ("74808", "GRANDFOR", 81002, "profile_contract", 81002),
            )

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_profile_callback_event(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["session"] == {"directive": "RELEASE"}
    assert response.json()["actions"] == [
        {
            "actionId": "evt-attendance-profile-1101.callback",
            "type": "ANSWER_CALLBACK",
            "callbackQueryId": "callback-1101",
        },
        {
            "actionId": "evt-attendance-profile-1101.reply",
            "type": "SEND_MESSAGE",
            "chatId": 81002,
            "replyToMessageId": 502,
            "text": "姓名：GRANDFOR\n工号：74808\n班次：未配置",
        },
    ]


def test_profile_callback_reports_an_unregistered_actor_explicitly() -> None:
    _apply_gateway_provider_migration()

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_profile_callback_event(),
    )

    assert response.status_code == 200, response.text
    assert response.json()["session"] == {"directive": "RELEASE"}
    assert response.json()["actions"][1]["text"] == (
        "你还未完成注册，请先注册后再查看我的信息。"
    )


def test_profile_callback_uses_current_shift_and_month_stat_policy() -> None:
    _apply_gateway_provider_migration()
    now = datetime.now(timezone.utc).astimezone(ZoneInfo("Asia/Shanghai"))
    year_month = now.strftime("%Y-%m")
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
                """
                INSERT INTO employee_shift_config (
                    year_month,
                    employee_id,
                    english_name,
                    shift_time_range,
                    shift_checkin_time,
                    shift_checkout_time,
                    monthly_rest_days
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    year_month,
                    "74808",
                    "GRANDFOR",
                    "09:00~18:00",
                    "09:00:00",
                    "18:00:00",
                    ",".join(str(day) for day in range(1, 32)),
                ),
            )

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_profile_callback_event(),
    )

    assert response.status_code == 200, response.text
    text = response.json()["actions"][1]["text"]
    assert "班次：09:00 - 18:00" in text
    assert "本月已出勤天数：0天" in text
    assert "本月缺卡次数：0次" in text
    assert "本月迟到次数：0次" in text
    assert "本月早退次数：0次" in text


def test_admin_export_callback_returns_deterministic_gateway_document_bytes() -> None:
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
    client = _provider_client()
    headers = {"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"}

    first = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_export_callback_event(
            "att:export:today",
            event_number=1501,
        ),
    )
    second = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_export_callback_event(
            "att:export:today",
            event_number=1502,
        ),
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["actions"][0] == {
        "actionId": "evt-attendance-export-1501.callback",
        "type": "ANSWER_CALLBACK",
        "callbackQueryId": "callback-1501",
    }
    assert [action["type"] for action in first.json()["actions"]] == [
        "ANSWER_CALLBACK",
        "SEND_MESSAGE",
    ]
    assert [action["type"] for action in second.json()["actions"]] == [
        "ANSWER_CALLBACK",
        "SEND_MESSAGE",
    ]
    for event_number in (1501, 1502):
        _record_event_action_delivered(
            event_id=f"evt-attendance-export-{event_number}",
            action_id=f"evt-attendance-export-{event_number}.progress",
        )
    assert run_deferred_interaction_cycle(
        _deferred_scheduler_config(),
        worker_id="export-deterministic-after-progress-receipts",
        now=datetime(2026, 8, 8, 8, 0, 2, tzinfo=timezone.utc),
    ) == (2, 4)
    documents: list[dict[str, object]] = []
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            for event_number in (1501, 1502):
                cursor.execute(
                    """
                    SELECT action_payload->'action'
                    FROM attendance_worker_actions
                    WHERE owner_key LIKE %s
                      AND action_payload->'action'->>'type' = 'SEND_DOCUMENT'
                    """,
                    (f"deferred-event:evt-attendance-export-{event_number}:%",),
                )
                documents.append(cursor.fetchone()[0])
    first_document, second_document = documents
    assert first_document["type"] == "SEND_DOCUMENT"
    assert first_document["chatId"] == 81002
    assert first_document["replyToMessageId"] == 1501
    assert first_document["document"]["source"] == "BYTES"
    assert first_document["document"]["fileName"] == "2026-08-08.xlsx"
    assert first_document["document"]["mimeType"] == (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    assert first_document["document"]["contentBase64"] == (
        second_document["document"]["contentBase64"]
    )
    body = base64.b64decode(first_document["document"]["contentBase64"], validate=True)
    with zipfile.ZipFile(io.BytesIO(body)) as workbook:
        assert workbook.testzip() is None
        assert "xl/workbook.xml" in workbook.namelist()


def test_admin_export_preserves_old_progress_document_delete_trace() -> None:
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
        json=_export_callback_event("att:export:today", event_number=1504),
    )

    assert response.status_code == 200, response.text
    actions = response.json()["actions"]
    assert [action["type"] for action in actions] == [
        "ANSWER_CALLBACK",
        "SEND_MESSAGE",
    ]
    assert actions[1] == {
        "actionId": "evt-attendance-export-1504.progress",
        "type": "SEND_MESSAGE",
        "chatId": 81002,
        "replyToMessageId": 1504,
        "text": "正在生成今日考勤导出（2026-08-08～2026-08-08），请稍候…",
    }
    assert run_deferred_interaction_cycle(
        _deferred_scheduler_config(),
        worker_id="export-before-progress-receipt",
        now=datetime(2026, 8, 8, 8, 0, 1, tzinfo=timezone.utc),
    ) == (0, 0)
    _record_event_action_delivered(
        event_id="evt-attendance-export-1504",
        action_id="evt-attendance-export-1504.progress",
        message_id=9504,
    )
    assert run_deferred_interaction_cycle(
        _deferred_scheduler_config(),
        worker_id="export-after-progress-receipt",
        now=datetime(2026, 8, 8, 8, 0, 2, tzinfo=timezone.utc),
    ) == (1, 2)
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT action_payload->'action', predecessor_action_id
                FROM attendance_worker_actions
                WHERE owner_key LIKE %s
                ORDER BY owner_key
                """,
                ("deferred-event:evt-attendance-export-1504:%",),
            )
            terminal_rows = cursor.fetchall()
            terminal_actions = [row[0] for row in terminal_rows]
    assert [action["type"] for action in terminal_actions] == [
        "SEND_DOCUMENT",
        "DELETE_MESSAGE",
    ]
    assert terminal_actions[1] == {
        "actionId": "evt-attendance-export-1504.progress-delete",
        "type": "DELETE_MESSAGE",
        "chatId": 81002,
        "messageId": 9504,
    }
    assert terminal_rows[0][1] is None
    assert terminal_rows[1][1] == terminal_actions[0]["actionId"]


@pytest.mark.parametrize(
    "terminal_status",
    ("PERMANENTLY_FAILED", "UNCERTAIN", "SUPERSEDED"),
)
def test_terminal_progress_receipt_fails_deferred_run_without_business_work(
    monkeypatch: pytest.MonkeyPatch,
    terminal_status: str,
) -> None:
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
    event_number = {
        "PERMANENTLY_FAILED": 1510,
        "UNCERTAIN": 1511,
        "SUPERSEDED": 1512,
    }[terminal_status]
    event_id = f"evt-attendance-export-{event_number}"
    progress_action_id = f"{event_id}.progress"
    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_export_callback_event("att:export:today", event_number=event_number),
    )
    assert response.status_code == 200, response.text

    async def must_not_collect(**_kwargs: object) -> list[object]:
        raise AssertionError("terminal progress feedback must stop business work")

    monkeypatch.setattr(
        gateway_export_module.attendance_export_service,
        "collect_rows_for_range",
        must_not_collect,
    )
    _record_event_action_terminal(
        event_id=event_id,
        action_id=progress_action_id,
        status=terminal_status,
    )

    assert run_deferred_interaction_cycle(
        _deferred_scheduler_config(),
        worker_id=f"terminal-progress-{terminal_status.lower()}",
        now=datetime(2026, 8, 8, 8, 0, 2, tzinfo=timezone.utc),
    ) == (1, 0)
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, last_error_code, completed_at IS NOT NULL
                FROM attendance_worker_schedule_runs
                WHERE run_key = %s
                """,
                (f"deferred-export:{event_id}",),
            )
            assert cursor.fetchone() == (
                "FAILED",
                f"PROGRESS_ACTION_{terminal_status}",
                True,
            )
    readiness = _provider_client().get("/readyz")
    assert readiness.status_code == 503
    assert readiness.json()["operational"]["schedulerFailed"] == 1
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "DELETE FROM attendance_worker_schedule_runs WHERE run_key = %s",
                (f"deferred-export:{event_id}",),
            )
            cursor.execute(
                "DELETE FROM attendance_gateway_delivery_receipts "
                "WHERE receipt_id = %s",
                (f"receipt-{progress_action_id}",),
            )


def test_admin_export_failure_preserves_old_error_and_progress_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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

    async def fail_export(**_kwargs: object) -> list[object]:
        raise RuntimeError("deterministic export failure")

    monkeypatch.setattr(
        gateway_export_module.attendance_export_service,
        "collect_rows_for_range",
        fail_export,
    )
    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_export_callback_event("att:export:today", event_number=1505),
    )

    assert response.status_code == 200, response.text
    actions = response.json()["actions"]
    assert [action["type"] for action in actions] == [
        "ANSWER_CALLBACK",
        "SEND_MESSAGE",
    ]
    _record_event_action_delivered(
        event_id="evt-attendance-export-1505",
        action_id="evt-attendance-export-1505.progress",
        message_id=9505,
    )
    assert run_deferred_interaction_cycle(
        _deferred_scheduler_config(),
        worker_id="export-failure-after-progress-receipt",
        now=datetime(2026, 8, 8, 8, 0, 2, tzinfo=timezone.utc),
    ) == (1, 2)
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT action_payload->'action'
                FROM attendance_worker_actions
                WHERE owner_key LIKE %s
                ORDER BY owner_key
                """,
                ("deferred-event:evt-attendance-export-1505:%",),
            )
            terminal_actions = [row[0] for row in cursor.fetchall()]
    assert terminal_actions[0]["text"] == (
        "导出失败，请稍后重试或联系管理员查看服务日志。"
    )
    assert terminal_actions[1]["messageId"] == 9505
    assert "messageIdSourceActionId" not in terminal_actions[1]


def test_non_admin_export_callback_fails_explicitly() -> None:
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

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_export_callback_event("att:export", event_number=1503),
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"][1]["text"] == "无权限操作"
    assert "replyMarkup" not in response.json()["actions"][1]


def test_registered_group_signin_callback_returns_a_fill_input_action() -> None:
    _apply_gateway_provider_migration()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id, english_name, tg_id, registered_chat_id
                ) VALUES (%s, %s, %s, %s)
                """,
                ("74808", "GRANDFOR", 81002, -10081002),
            )

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_group_action_callback_event("att:signin"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["session"] == {"directive": "UNCHANGED"}
    assert response.json()["actions"] == [
        {
            "actionId": "evt-attendance-group-1201.callback",
            "type": "ANSWER_CALLBACK",
            "callbackQueryId": "callback-1201",
        },
        {
            "actionId": "evt-attendance-group-1201.reply",
            "type": "SEND_MESSAGE",
            "chatId": -10081002,
            "replyToMessageId": 701,
            "text": "请点击下方按钮操作",
            "replyMarkup": {
                "inlineKeyboard": [
                    [
                        {
                            "text": "签到",
                            "switchInlineQueryCurrentChat": (
                                "#打卡\n英文名：GRANDFOR\n工号：74808\n事项：签到"
                            ),
                        }
                    ]
                ]
            },
        },
    ]


def test_remote_group_signin_restores_the_copy_fallback_and_exact_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _apply_gateway_provider_migration()
    _set_group_policy(monkeypatch, capabilities=["remote-diff-checkin"])
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id, english_name, tg_id, registered_chat_id
                ) VALUES (%s, %s, %s, %s)
                """,
                ("74808", "GRANDFOR", 81002, -10081002),
            )

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_group_action_command_event("/signin"),
    )

    assert response.status_code == 200, response.text
    reply = response.json()["actions"][0]
    draft = "#打卡\n英文名：GRANDFOR\n工号：74808\n事项：签到"
    assert reply["text"] == (
        "请点击 ↗ 填入模板；发截图时请「回复本条消息」发送（群隐私模式下否则 Bot 收不到）。"
        "若无法 ↗，请点「复制」后粘贴并回复本条发送。"
    )
    assert reply["replyMarkup"] == {
        "inlineKeyboard": [[
            {"text": "签到", "switchInlineQueryCurrentChat": draft},
            {"text": "复制", "copyText": draft},
        ]]
    }


def test_leave_copy_fallback_chat_restores_the_copy_button_and_exact_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _apply_gateway_provider_migration()
    _set_group_policy(monkeypatch, capabilities=["leave-back-copy-fallback"])
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id, english_name, tg_id, registered_chat_id
                ) VALUES (%s, %s, %s, %s)
                """,
                ("74808", "GRANDFOR", 81002, -10081002),
            )

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_group_action_callback_event("att:leave"),
    )

    assert response.status_code == 200, response.text
    reply = response.json()["actions"][1]
    draft = "\n#离岗报备\n人员：GRANDFOR\n时间：16:00:00\n原因："
    assert reply["text"] == (
        "请点击 ↗ 填入模板；发截图时请「回复本条消息」发送（群隐私模式下否则 Bot 收不到）。"
        "若无法 ↗，请点「复制」后粘贴并回复本条发送。"
    )
    assert reply["replyMarkup"] == {
        "inlineKeyboard": [[
            {"text": "离岗", "switchInlineQueryCurrentChat": draft},
            {"text": "复制", "copyText": draft},
        ]]
    }


def test_inline_query_is_answered_by_attendance_without_business_mutation() -> None:
    _apply_gateway_provider_migration()

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_inline_query_event(),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "protocolVersion": "1.0",
        "eventId": "evt-attendance-inline-1202",
        "result": "PROCESSED",
        "session": {"directive": "UNCHANGED"},
        "actions": [
            {
                "actionId": "evt-attendance-inline-1202.answer",
                "type": "ANSWER_INLINE_QUERY",
                "inlineQueryId": "inline-1202",
                "results": [],
                "cacheTimeSeconds": 0,
                "isPersonal": True,
            }
        ],
    }


def test_unregistered_group_action_does_not_offer_a_false_fill_template() -> None:
    _apply_gateway_provider_migration()

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_group_action_callback_event("att:signout"),
    )

    assert response.status_code == 200, response.text
    reply = response.json()["actions"][1]
    assert reply["text"] == "请先私聊机器人完成注册（英文名$工号）。"
    assert reply["replyMarkup"] == {
        "inlineKeyboard": [[
            {"text": "签退", "callbackData": "att:signout"},
        ]]
    }


def test_unregistered_group_leave_keeps_the_old_registration_callback() -> None:
    _apply_gateway_provider_migration()

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_group_action_callback_event("att:leave"),
    )

    assert response.status_code == 200, response.text
    reply = response.json()["actions"][1]
    assert reply["text"] == "请先私聊机器人完成注册（英文名$工号）。"
    assert reply["replyMarkup"] == {
        "inlineKeyboard": [[
            {"text": "离岗", "callbackData": "att:leave"},
        ]]
    }


@pytest.mark.parametrize("command", ["/signin", "签到"])
def test_group_attendance_command_returns_the_same_registered_fill_action(
    command: str,
) -> None:
    _apply_gateway_provider_migration()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id, english_name, tg_id, registered_chat_id
                ) VALUES (%s, %s, %s, %s)
                """,
                ("74808", "GRANDFOR", 81002, -10081002),
            )

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_group_action_command_event(command),
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"] == [
        {
            "actionId": "evt-attendance-group-1203.reply",
            "type": "SEND_MESSAGE",
            "chatId": -10081002,
            "replyToMessageId": 703,
            "text": "请点击下方按钮操作",
            "replyMarkup": {
                "inlineKeyboard": [
                    [
                        {
                            "text": "签到",
                            "switchInlineQueryCurrentChat": (
                                "#打卡\n英文名：GRANDFOR\n工号：74808\n事项：签到"
                            ),
                        }
                    ]
                ]
            },
        }
    ]


def test_group_leave_command_returns_the_registered_leave_fill_action() -> None:
    _apply_gateway_provider_migration()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id, english_name, tg_id, registered_chat_id
                ) VALUES (%s, %s, %s, %s)
                """,
                ("74808", "GRANDFOR", 81002, -10081002),
            )

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_group_action_command_event("/leave"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"] == [
        {
            "actionId": "evt-attendance-group-1203.reply",
            "type": "SEND_MESSAGE",
            "chatId": -10081002,
            "replyToMessageId": 703,
            "text": "请点击下方按钮操作",
            "replyMarkup": {
                "inlineKeyboard": [
                    [
                        {
                            "text": "离岗",
                            "switchInlineQueryCurrentChat": (
                                "\n#离岗报备\n人员：GRANDFOR\n时间：16:02:00\n原因："
                            ),
                        }
                    ]
                ]
            },
        }
    ]


@pytest.mark.parametrize(
    "command",
    ["/att_signin", "/att_signout", "/att_leave", "/att_back"],
)
def test_group_attendance_ignores_non_v1_command_aliases(command: str) -> None:
    _apply_gateway_provider_migration()

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_group_action_command_event(command),
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "protocolVersion": "1.0",
        "eventId": "evt-attendance-group-1203",
        "result": "PROCESSED",
        "session": {"directive": "UNCHANGED"},
        "actions": [],
    }


def test_group_export_text_restores_private_only_guidance() -> None:
    _apply_gateway_provider_migration()

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_group_action_command_event("导出"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"] == [{
        "actionId": "evt-attendance-group-1203.reply",
        "type": "SEND_MESSAGE",
        "chatId": -10081002,
        "replyToMessageId": 703,
        "text": "导出仅支持私聊中使用。",
    }]


def test_group_registration_callback_restores_private_chat_guidance() -> None:
    _apply_gateway_provider_migration()

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_group_action_callback_event("att:register", event_number=1212),
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"] == [
        {
            "actionId": "evt-attendance-group-1212.callback",
            "type": "ANSWER_CALLBACK",
            "callbackQueryId": "callback-1212",
        },
        {
            "actionId": "evt-attendance-group-1212.reply",
            "type": "SEND_MESSAGE",
            "chatId": -10081002,
            "replyToMessageId": 701,
            "text": "请先私聊机器人，再点击【注册】完成注册。",
        },
    ]


def test_switch_attendance_group_updates_registered_chat() -> None:
    _apply_gateway_provider_migration()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id, english_name, tg_id, registered_chat_id
                ) VALUES (%s, %s, %s, %s)
                """,
                ("74808", "GRANDFOR", 81002, -10081000),
            )

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_group_action_callback_event("att:switch_group", event_number=1210),
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"] == [
        {
            "actionId": "evt-attendance-group-1210.callback",
            "type": "ANSWER_CALLBACK",
            "callbackQueryId": "callback-1210",
        },
        {
            "actionId": "evt-attendance-group-1210.reply",
            "type": "SEND_MESSAGE",
            "chatId": -10081002,
            "replyToMessageId": 701,
            "text": "已记录本群为考勤群，请重新发送打卡截图。",
        },
    ]
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT registered_chat_id FROM registrations WHERE tg_id = %s",
                (81002,),
            )
            assert cursor.fetchone() == (-10081002,)


def test_switch_attendance_group_does_not_create_registration() -> None:
    _apply_gateway_provider_migration()

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_group_action_callback_event("att:switch_group", event_number=1211),
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"][1]["text"] == "您尚未注册。"
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM registrations WHERE tg_id = %s", (81002,))
            assert cursor.fetchone() == (0,)


def test_group_leave_and_back_reports_mutate_one_record_idempotently() -> None:
    _apply_gateway_provider_migration()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id, english_name, tg_id, registered_chat_id
                ) VALUES (%s, %s, %s, %s)
                """,
                ("74808", "GRANDFOR", 81002, -10081002),
            )
    client = _provider_client()
    headers = {"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"}
    leave_event = _group_report_event(
        event_number=1301,
        text="#离岗报备\n人员：GRANDFOR\n时间：16:00:00\n原因：客户来电",
        received_at="2026-08-08T08:00:00Z",
    )
    back_event = _group_report_event(
        event_number=1302,
        text="#返岗报备\n人员：GRANDFOR\n时间：16:25:00\n原因：处理完成",
        received_at="2026-08-08T08:25:00Z",
    )

    leave = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=leave_event,
    )
    duplicate_leave = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=leave_event,
    )
    back = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=back_event,
    )

    assert leave.status_code == 200, leave.text
    assert leave.json()["actions"] == []
    assert duplicate_leave.json() == {**leave.json(), "result": "DUPLICATE"}
    assert back.status_code == 200, back.text
    assert back.json()["actions"] == []
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, reason, duration_minutes, remark_required,
                       leave_at, back_at
                FROM temporary_leave_records
                WHERE employee_id = %s AND chat_id = %s
                """,
                ("74808", -10081002),
            )
            rows = cursor.fetchall()
    assert len(rows) == 1
    assert rows[0][:4] == ("CLOSED", "客户来电", 25, False)
    assert rows[0][4].isoformat() == "2026-08-08T08:00:00+00:00"
    assert rows[0][5].isoformat() == "2026-08-08T08:25:00+00:00"


@pytest.mark.parametrize(
    ("text", "event_number"),
    [
        ("#离岗报备\n原因：未注册", 1303),
        ("#返岗报备\n原因：未注册", 1304),
    ],
    ids=["leave", "back"],
)
def test_unregistered_group_leave_and_back_reports_keep_the_old_silence(
    text: str,
    event_number: int,
) -> None:
    _apply_gateway_provider_migration()

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_group_report_event(
            event_number=event_number,
            text=text,
            received_at="2026-08-08T09:00:00Z",
        ),
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"] == []
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM temporary_leave_records WHERE tg_id = %s",
                (81002,),
            )
            assert cursor.fetchone() == (0,)


def test_leave_and_back_callbacks_render_current_business_drafts() -> None:
    _apply_gateway_provider_migration()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id, english_name, tg_id, registered_chat_id
                ) VALUES (%s, %s, %s, %s)
                """,
                ("74808", "GRANDFOR", 81002, -10081002),
            )
    client = _provider_client()
    headers = {"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"}

    leave_callback = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_group_action_callback_event("att:leave"),
    )
    client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_group_report_event(
            event_number=1301,
            text="#离岗报备\n原因：客户来电",
            received_at="2026-08-08T08:00:00Z",
        ),
    )
    back_callback = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_group_action_callback_event(
            "att:back",
            event_number=1204,
            received_at="2026-08-08T08:25:00Z",
        ),
    )

    assert leave_callback.status_code == 200, leave_callback.text
    leave_button = leave_callback.json()["actions"][1]["replyMarkup"][
        "inlineKeyboard"
    ][0][0]
    assert leave_button == {
        "text": "离岗",
        "switchInlineQueryCurrentChat": (
            "\n#离岗报备\n人员：GRANDFOR\n时间：16:00:00\n原因："
        ),
    }
    assert back_callback.status_code == 200, back_callback.text
    back_button = back_callback.json()["actions"][1]["replyMarkup"][
        "inlineKeyboard"
    ][0][0]
    assert back_button == {
        "text": "返岗",
        "switchInlineQueryCurrentChat": (
            "\n#返岗报备\n人员：GRANDFOR\n时间：16:25:00\n"
            "离岗时长：25分钟\n提示：你已超时\n原因："
        ),
    }


@pytest.mark.parametrize("edited", [False, True], ids=["message", "edited-message"])
def test_group_photo_checkin_reads_gateway_file_and_persists_once(
    monkeypatch: pytest.MonkeyPatch,
    edited: bool,
) -> None:
    _apply_gateway_provider_migration()
    monkeypatch.setenv("CHECKIN_AI_ENABLED", "false")
    monkeypatch.setenv("TEST_GROUP_GOOGLE_SHEETS_ENABLED", "false")
    monkeypatch.setenv("BBQ_GOOGLE_SHEETS_ENABLED", "true")
    _set_group_policy(monkeypatch, capabilities=["bbq-google-sheets"])
    monkeypatch.setenv("BBQ_GOOGLE_SHEETS_SPREADSHEET_ID", "sheet-bbq-1401")
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id, english_name, tg_id, registered_chat_id
                ) VALUES (%s, %s, %s, %s)
                """,
                ("74808", "GRANDFOR", 81002, -10081002),
            )
            cursor.execute(
                """
                INSERT INTO employee_shift_roster (
                    year_month, source, employee_id
                ) VALUES (%s, %s, %s)
                """,
                ("2026-08", "main", "74808"),
            )
    file_ref = "tgf_0123456789abcdef0123456789abcdef01234567"
    event = _group_checkin_event(
        event_number=1401,
        file_ref=file_ref,
        edited=edited,
    )

    with _gateway_file_server(
        file_ref=file_ref,
        payload=b"gateway-image-bytes",
    ) as (gateway_base_url, authorizations):
        client = _provider_client(gateway_base_url)
        headers = {"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"}
        response = client.post(
            "/integration/gateway/v1/events",
            headers=headers,
            json=event,
        )
        duplicate = client.post(
            "/integration/gateway/v1/events",
            headers=headers,
            json=event,
        )
        assert authorizations == []
        assert run_deferred_interaction_cycle(
            _deferred_scheduler_config(),
            worker_id="checkin-before-progress-receipt",
            now=datetime(2026, 8, 8, 8, 0, 1, tzinfo=timezone.utc),
            file_reader=GatewayFileReader(
                base_url=gateway_base_url,
                bearer_token=_TEST_ATTENDANCE_TO_GATEWAY_CREDENTIAL,
            ),
        ) == (0, 0)
        _record_event_action_delivered(
            event_id="evt-attendance-checkin-1401",
            action_id="evt-attendance-checkin-1401.progress",
        )
        assert run_deferred_interaction_cycle(
            _deferred_scheduler_config(),
            worker_id="checkin-after-progress-receipt",
            now=datetime(2026, 8, 8, 8, 0, 2, tzinfo=timezone.utc),
            file_reader=GatewayFileReader(
                base_url=gateway_base_url,
                bearer_token=_TEST_ATTENDANCE_TO_GATEWAY_CREDENTIAL,
            ),
        ) == (1, 1)
        with psycopg2.connect(_database_url()) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE attendance_worker_schedule_runs
                    SET status = 'RETRYING', lease_owner = NULL,
                        lease_expires_at = NULL, next_attempt_at = %s,
                        updated_at = %s
                    WHERE run_key = %s
                    """,
                    (
                        datetime(2026, 8, 8, 8, 0, 2, tzinfo=timezone.utc),
                        datetime(2026, 8, 8, 8, 0, 2, tzinfo=timezone.utc),
                        "deferred-checkin:evt-attendance-checkin-1401",
                    ),
                )
        assert run_deferred_interaction_cycle(
            _deferred_scheduler_config(),
            worker_id="checkin-restart-after-outbox-commit",
            now=datetime(2026, 8, 8, 8, 0, 3, tzinfo=timezone.utc),
            file_reader=GatewayFileReader(
                base_url=gateway_base_url,
                bearer_token=_TEST_ATTENDANCE_TO_GATEWAY_CREDENTIAL,
            ),
        ) == (1, 0)

    assert response.status_code == 200, response.text
    assert response.json()["actions"] == [
        {
            "actionId": "evt-attendance-checkin-1401.progress",
            "type": "SEND_MESSAGE",
            "chatId": -10081002,
            "replyToMessageId": 1401,
            "text": "已收到签到截图，正在识别，请稍候…",
        }
    ]
    assert duplicate.json() == {**response.json(), "result": "DUPLICATE"}
    assert authorizations == [
        f"Bearer {_TEST_ATTENDANCE_TO_GATEWAY_CREDENTIAL}"
    ]
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT file_id, employee_id, clock_time, clock_action,
                       source_chat_id, source_message_id
                FROM clock_records
                WHERE employee_id = %s
                """,
                ("74808",),
            )
            rows = cursor.fetchall()
            cursor.execute(
                """
                SELECT run_key, job_kind, status, payload
                FROM attendance_worker_schedule_runs
                WHERE job_kind = 'CHECKIN_SHEETS_SYNC'
                ORDER BY run_key
                """
            )
            sheets_jobs = cursor.fetchall()
            cursor.execute(
                """
                SELECT action_payload->'action'
                FROM attendance_worker_actions
                WHERE owner_key LIKE %s
                ORDER BY owner_key
                """,
                ("deferred-event:evt-attendance-checkin-1401:%",),
            )
            terminal_actions = [row[0] for row in cursor.fetchall()]
    assert rows == [
        (
            file_ref,
            "74808",
            datetime(2026, 8, 8, 8, 0, tzinfo=timezone.utc),
            "签到",
            -10081002,
            1401,
        )
    ]
    assert sheets_jobs == [
        (
            "checkin-sheets:BBQ:10081002:1401",
            "CHECKIN_SHEETS_SYNC",
            "PENDING",
            {"chatId": -10081002, "syncKind": "BBQ"},
        )
    ]
    assert terminal_actions == [{
        "actionId": "evt-attendance-checkin-1401.reply",
        "type": "SEND_MESSAGE",
        "chatId": -10081002,
        "replyToMessageId": 1401,
        "text": "签到成功",
    }]


def test_group_photo_checkin_outside_roster_fails_without_false_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _apply_gateway_provider_migration()
    monkeypatch.setenv("CHECKIN_AI_ENABLED", "false")
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registrations (
                    employee_id, english_name, tg_id, registered_chat_id
                ) VALUES (%s, %s, %s, %s)
                """,
                ("74808", "GRANDFOR", 81002, -10081002),
            )
    file_ref = "tgf_1123456789abcdef0123456789abcdef01234567"

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_group_checkin_event(event_number=1402, file_ref=file_ref),
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"][0]["text"] == (
        "打卡失败：您不在本群当前班表，未记账。"
    )
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM clock_records WHERE employee_id = %s",
                ("74808",),
            )
            assert cursor.fetchone() == (0,)


def test_registration_confirmation_binds_the_pre_registered_employee() -> None:
    _apply_gateway_provider_migration()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO registrations (employee_id, english_name)
                VALUES (%s, %s)
                ON CONFLICT (employee_id) DO UPDATE SET
                    tg_id = NULL,
                    tg_username = NULL,
                    registered_chat_id = NULL,
                    english_name = EXCLUDED.english_name
                """,
                ("74808", "GRANDFOR"),
            )
    client = _provider_client()
    headers = {"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"}
    begin = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_registration_callback_event(),
    )
    preview = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_registration_text_event(),
    )
    confirm_data = preview.json()["actions"][0]["replyMarkup"]["inlineKeyboard"][0][0][
        "callbackData"
    ]

    confirmation_event = _registration_finish_event(confirm_data)
    confirmation = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=confirmation_event,
    )
    duplicate = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=confirmation_event,
    )

    assert begin.status_code == 200
    assert preview.status_code == 200
    assert confirmation.status_code == 200, confirmation.text
    payload = confirmation.json()
    assert duplicate.status_code == 200
    assert duplicate.json() == {**payload, "result": "DUPLICATE"}
    assert payload["session"] == {"directive": "RELEASE"}
    assert payload["actions"] == [
        {
            "actionId": "evt-attendance-register-1004.callback",
            "type": "ANSWER_CALLBACK",
            "callbackQueryId": "callback-1004",
        },
        {
            "actionId": "evt-attendance-register-1004.reply",
            "type": "SEND_MESSAGE",
            "chatId": 81002,
            "replyToMessageId": 504,
            "text": "您成功注册",
        },
    ]
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tg_id, tg_username, registered_chat_id FROM registrations WHERE employee_id = %s",
                ("74808",),
            )
            assert cursor.fetchone() == (81002, "contract_register", 81002)
            cursor.execute(
                "SELECT COUNT(*) FROM attendance_registration_sessions WHERE tg_id = %s",
                (81002,),
            )
            assert cursor.fetchone() == (0,)


def test_registration_confirmation_rejects_a_different_telegram_owner() -> None:
    _apply_gateway_provider_migration()
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO registrations (employee_id, english_name) VALUES (%s, %s)",
                ("74808", "GRANDFOR"),
            )
    client = _provider_client()
    headers = {"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"}
    client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_registration_callback_event(),
    )
    preview = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_registration_text_event(),
    )
    confirm_data = preview.json()["actions"][0]["replyMarkup"]["inlineKeyboard"][0][0][
        "callbackData"
    ]

    mismatch = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_registration_finish_event(confirm_data, event_number=1005, tg_id=81001),
    )

    assert mismatch.status_code == 200, mismatch.text
    assert mismatch.json()["session"] == {"directive": "RELEASE"}
    assert mismatch.json()["actions"][1]["text"] == (
        "该确认不属于当前账户，请重新点击【注册】。"
    )
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tg_id FROM registrations WHERE employee_id = %s",
                ("74808",),
            )
            assert cursor.fetchone() == (None,)
            cursor.execute(
                "SELECT tg_id FROM attendance_registration_sessions WHERE tg_id = %s",
                (81002,),
            )
            assert cursor.fetchone() == (81002,)


def test_registration_cancel_releases_the_session_without_binding() -> None:
    _apply_gateway_provider_migration()
    client = _provider_client()
    headers = {"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"}
    client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_registration_callback_event(),
    )
    preview = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_registration_text_event(),
    )
    cancel_data = preview.json()["actions"][0]["replyMarkup"]["inlineKeyboard"][0][1][
        "callbackData"
    ]

    cancelled = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_registration_finish_event(cancel_data, event_number=1006),
    )

    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["session"] == {"directive": "RELEASE"}
    assert cancelled.json()["actions"][1]["text"] == "已取消"
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM attendance_registration_sessions WHERE tg_id = %s",
                (81002,),
            )
            assert cursor.fetchone() == (0,)


def test_expired_registration_confirmation_fails_closed_and_releases() -> None:
    _apply_gateway_provider_migration()
    client = _provider_client()
    headers = {"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"}
    client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_registration_callback_event(),
    )
    preview = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_registration_text_event(),
    )
    confirm_data = preview.json()["actions"][0]["replyMarkup"]["inlineKeyboard"][0][0][
        "callbackData"
    ]
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                    UPDATE attendance_registration_sessions
                    SET created_at = snapshot.now - interval '20 minutes',
                        last_activity_at = snapshot.now - interval '16 minutes',
                        inactivity_expires_at = snapshot.now - interval '1 minute',
                        absolute_expires_at = snapshot.now - interval '1 minute',
                        preview_expires_at = snapshot.now - interval '1 minute'
                    FROM (SELECT clock_timestamp() AS now) AS snapshot
                    WHERE tg_id = %s
                """,
                (81002,),
            )

    expired = client.post(
        "/integration/gateway/v1/events",
        headers=headers,
        json=_registration_finish_event(confirm_data, event_number=1007),
    )

    assert expired.status_code == 200, expired.text
    assert expired.json()["session"] == {"directive": "RELEASE"}
    assert expired.json()["actions"][1]["text"] == (
        "确认已失效，请重新点击【注册】。"
    )
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM attendance_registration_sessions WHERE tg_id = %s",
                (81002,),
            )
            assert cursor.fetchone() == (0,)
