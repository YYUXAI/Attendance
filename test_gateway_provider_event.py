from __future__ import annotations

import os
from pathlib import Path

import psycopg2
from fastapi.testclient import TestClient

from gateway_provider.app import (
    AttendanceGatewayProviderConfig,
    create_attendance_gateway_provider_app,
)


_TEST_GATEWAY_CREDENTIAL = "gateway-to-attendance-test-credential"


def _database_url() -> str:
    value = (os.environ.get("ATTENDANCE_TEST_DATABASE_URL") or "").strip()
    if not value:
        raise RuntimeError("ATTENDANCE_TEST_DATABASE_URL is required")
    return value


def _apply_gateway_provider_migration() -> None:
    migration = (Path(__file__).parent / "migrations" / "0003_gateway_provider.sql").read_text(
        encoding="utf-8"
    )
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(migration)
            cursor.execute(
                "DELETE FROM gateway_processed_events WHERE event_id = %s",
                ("evt-attendance-1001",),
            )


def test_attendance_command_returns_namespaced_menu_action() -> None:
    _apply_gateway_provider_migration()
    app = create_attendance_gateway_provider_app(
        AttendanceGatewayProviderConfig(
            database_url=_database_url(),
            gateway_bearer_token=_TEST_GATEWAY_CREDENTIAL,
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


def _provider_client() -> TestClient:
    return TestClient(
        create_attendance_gateway_provider_app(
            AttendanceGatewayProviderConfig(
                database_url=_database_url(),
                gateway_bearer_token=_TEST_GATEWAY_CREDENTIAL,
            )
        )
    )


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
