from __future__ import annotations

import base64
import hashlib
import io
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

from gateway_provider.app import (
    AttendanceGatewayProviderConfig,
    create_attendance_gateway_provider_app,
)


_TEST_GATEWAY_CREDENTIAL = "gateway-to-attendance-test-credential"
_TEST_ATTENDANCE_TO_GATEWAY_CREDENTIAL = "attendance-to-gateway-test-credential"
_TEST_UNUSED_GATEWAY_BASE_URL = "http://127.0.0.1:19089"


def _database_url() -> str:
    value = (os.environ.get("ATTENDANCE_TEST_DATABASE_URL") or "").strip()
    if not value:
        raise RuntimeError("ATTENDANCE_TEST_DATABASE_URL is required")
    return value


def _apply_gateway_provider_migration() -> None:
    migration_directory = Path(__file__).parent / "migrations"
    migrations = [
        (migration_directory / name).read_text(encoding="utf-8")
        for name in ("0003_gateway_provider.sql", "0004_registration_provider.sql")
    ]
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            for migration in migrations:
                cursor.execute(migration)
            cursor.execute("DELETE FROM attendance_registration_sessions")
            cursor.execute(
                "DELETE FROM temporary_leave_records WHERE tg_id IN (%s, %s)",
                (81001, 81002),
            )
            cursor.execute(
                "DELETE FROM gateway_processed_events WHERE event_id LIKE %s",
                ("evt-attendance-%",),
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


def _apply_provider_health_migrations() -> None:
    _apply_gateway_provider_migration()
    migration = (
        Path(__file__).parent / "migrations/0005_webapp_sessions.sql"
    ).read_text(encoding="utf-8")
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(migration)


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
        "status": "READY",
        "database": True,
        "requiredTables": {
            "gatewayProcessedEvents": True,
            "businessTruth": True,
            "webappSessions": True,
        },
    }


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
        )
    )

    health = TestClient(app).get("/healthz")
    readiness = TestClient(app).get("/readyz")

    assert health.status_code == 503
    assert health.json() == {"ok": False, "status": "UNHEALTHY"}
    assert readiness.status_code == 503
    assert readiness.json() == {
        "ok": False,
        "status": "NOT_READY",
        "database": False,
        "requiredTables": {
            "gatewayProcessedEvents": False,
            "businessTruth": False,
            "webappSessions": False,
        },
    }


def test_attendance_command_returns_namespaced_menu_action() -> None:
    _apply_gateway_provider_migration()
    app = create_attendance_gateway_provider_app(
        AttendanceGatewayProviderConfig(
            database_url=_database_url(),
            gateway_to_attendance_bearer_token=_TEST_GATEWAY_CREDENTIAL,
            gateway_internal_base_url=_TEST_UNUSED_GATEWAY_BASE_URL,
            attendance_to_gateway_bearer_token=(
                _TEST_ATTENDANCE_TO_GATEWAY_CREDENTIAL
            ),
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
    assert payload["session"] == {"directive": "UNCHANGED"}
    assert payload["actions"] == [
        {
            "actionId": "evt-attendance-1001.menu",
            "type": "SEND_MESSAGE",
            "chatId": 81001,
            "replyToMessageId": 501,
            "text": "考勤功能",
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
    keyboard = response.json()["actions"][0]["replyMarkup"]["inlineKeyboard"]
    assert keyboard[1] == [
        {"text": "导出", "callbackData": "att:export"},
    ]


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


def test_attendance_summary_reads_only_attendance_business_truth() -> None:
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
        "registrationStatus": "APPROVED",
        "organizationDepartmentName": "Gateway Contract Department",
        "profileBindingStatus": "BOUND",
    }
    assert unregistered.status_code == 200, unregistered.text
    assert unregistered.json() == {
        "protocolVersion": "1.0",
        "registrationStatus": "UNREGISTERED",
        "organizationDepartmentName": None,
        "profileBindingStatus": "UNBOUND",
    }
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "UNAUTHORIZED"


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
) -> dict[str, object]:
    return {
        "protocolVersion": "1.0",
        "eventId": f"evt-attendance-checkin-{event_number}",
        "target": "ATTENDANCE",
        "routeReason": "GROUP_OWNER",
        "conversationId": "telegram:chat:-10081002",
        "receivedAt": "2026-08-08T08:00:01Z",
        "telegramUpdate": {
            "update_id": event_number,
            "message": {
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
    first_document = first.json()["actions"][1]
    second_document = second.json()["actions"][1]
    assert first.json()["actions"][0] == {
        "actionId": "evt-attendance-export-1501.callback",
        "type": "ANSWER_CALLBACK",
        "callbackQueryId": "callback-1501",
    }
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
            "text": "请点击下方按钮填入签到模板。",
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
    assert "replyMarkup" not in reply


def test_group_attendance_command_returns_the_same_registered_fill_action() -> None:
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
        json=_group_action_command_event("/att_signin"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"] == [
        {
            "actionId": "evt-attendance-group-1203.reply",
            "type": "SEND_MESSAGE",
            "chatId": -10081002,
            "replyToMessageId": 703,
            "text": "请点击下方按钮填入签到模板。",
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
        json=_group_action_command_event("/att_leave"),
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"] == [
        {
            "actionId": "evt-attendance-group-1203.reply",
            "type": "SEND_MESSAGE",
            "chatId": -10081002,
            "replyToMessageId": 703,
            "text": "请点击下方按钮填入离岗模板。",
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


def test_unregistered_group_leave_report_fails_explicitly_without_a_record() -> None:
    _apply_gateway_provider_migration()

    response = _provider_client().post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_TEST_GATEWAY_CREDENTIAL}"},
        json=_group_report_event(
            event_number=1303,
            text="#离岗报备\n原因：未注册",
            received_at="2026-08-08T09:00:00Z",
        ),
    )

    assert response.status_code == 200, response.text
    assert response.json()["actions"][0]["text"] == (
        "请先私聊机器人完成注册（英文名$工号）。"
    )
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


def test_group_photo_checkin_reads_gateway_file_and_persists_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _apply_gateway_provider_migration()
    monkeypatch.setenv("FORMAL_GROUP_ROSTER_SOURCE_MAP", "-10081002:main")
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
            cursor.execute(
                """
                INSERT INTO employee_shift_roster (
                    year_month, source, employee_id
                ) VALUES (%s, %s, %s)
                """,
                ("2026-08", "main", "74808"),
            )
    file_ref = "tgf_0123456789abcdef0123456789abcdef01234567"
    event = _group_checkin_event(event_number=1401, file_ref=file_ref)

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

    assert response.status_code == 200, response.text
    assert response.json()["actions"] == [
        {
            "actionId": "evt-attendance-checkin-1401.reply",
            "type": "SEND_MESSAGE",
            "chatId": -10081002,
            "replyToMessageId": 1401,
            "text": "签到成功",
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


def test_group_photo_checkin_outside_roster_fails_without_false_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _apply_gateway_provider_migration()
    monkeypatch.setenv("FORMAL_GROUP_ROSTER_SOURCE_MAP", "-10081002:main")
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
