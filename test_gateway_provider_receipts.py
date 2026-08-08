from __future__ import annotations

import os
from pathlib import Path

import psycopg2
from fastapi.testclient import TestClient

from gateway_provider.app import (
    AttendanceGatewayProviderConfig,
    create_attendance_gateway_provider_app,
)


_GATEWAY_CREDENTIAL = "gateway-to-attendance-receipt-test-credential"
_ATTENDANCE_CREDENTIAL = "attendance-to-gateway-receipt-test-credential"


def _database_url() -> str:
    value = (os.environ.get("ATTENDANCE_TEST_DATABASE_URL") or "").strip()
    if not value:
        raise RuntimeError("ATTENDANCE_TEST_DATABASE_URL is required")
    return value


def _client() -> TestClient:
    return TestClient(
        create_attendance_gateway_provider_app(
            AttendanceGatewayProviderConfig(
                database_url=_database_url(),
                gateway_to_attendance_bearer_token=_GATEWAY_CREDENTIAL,
                gateway_internal_base_url="http://127.0.0.1:19081/",
                attendance_to_gateway_bearer_token=_ATTENDANCE_CREDENTIAL,
            )
        )
    )


def _prepare_database() -> None:
    root = Path(__file__).parent
    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            for name in (
                "0003_gateway_provider.sql",
                "0004_registration_provider.sql",
                "0005_webapp_sessions.sql",
                "0006_delivery_receipts.sql",
            ):
                cursor.execute((root / "migrations" / name).read_text(encoding="utf-8"))
            cursor.execute("DELETE FROM attendance_gateway_delivery_receipts")
            cursor.execute(
                "DELETE FROM gateway_processed_events WHERE event_id = %s",
                ("evt-attendance-receipt-1001",),
            )


def _create_owned_action(client: TestClient) -> None:
    response = client.post(
        "/integration/gateway/v1/events",
        headers={"Authorization": f"Bearer {_GATEWAY_CREDENTIAL}"},
        json={
            "protocolVersion": "1.0",
            "eventId": "evt-attendance-receipt-1001",
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
                        "first_name": "Receipt",
                    },
                    "text": "/attendance",
                },
            },
        },
    )
    assert response.status_code == 200, response.text


def _receipt(*, status: str = "DELIVERED") -> dict[str, object]:
    base: dict[str, object] = {
        "protocolVersion": "1.0",
        "receiptId": "rcpt.attendance.1001",
        "provider": "ATTENDANCE",
        "actionId": "evt-attendance-receipt-1001.menu",
        "relatedEventId": "evt-attendance-receipt-1001",
        "status": status,
        "attemptedAt": "2026-08-08T07:00:01Z",
    }
    if status == "DELIVERED":
        base["telegramResult"] = {
            "accepted": True,
            "chatId": 81001,
            "messageId": 91001,
        }
    else:
        base["failure"] = {"code": "TELEGRAM_ERROR", "terminal": True}
    return base


def test_delivery_receipt_is_authenticated_idempotent_and_action_scoped() -> None:
    _prepare_database()
    client = _client()
    _create_owned_action(client)
    headers = {"Authorization": f"Bearer {_GATEWAY_CREDENTIAL}"}

    processed = client.post(
        "/integration/gateway/v1/delivery-receipts",
        headers=headers,
        json=_receipt(),
    )
    duplicate = client.post(
        "/integration/gateway/v1/delivery-receipts",
        headers=headers,
        json=_receipt(),
    )
    conflict = client.post(
        "/integration/gateway/v1/delivery-receipts",
        headers=headers,
        json=_receipt(status="PERMANENTLY_FAILED"),
    )
    unknown = _receipt()
    unknown["receiptId"] = "rcpt.attendance.unknown"
    unknown["actionId"] = "evt-attendance-receipt-1001.unknown"
    not_owned = client.post(
        "/integration/gateway/v1/delivery-receipts",
        headers=headers,
        json=unknown,
    )
    unauthorized = client.post(
        "/integration/gateway/v1/delivery-receipts",
        headers={"Authorization": "Bearer invalid"},
        json=_receipt(),
    )

    assert processed.status_code == 200
    assert processed.json() == {
        "protocolVersion": "1.0",
        "receiptId": "rcpt.attendance.1001",
        "result": "PROCESSED",
    }
    assert duplicate.status_code == 200
    assert duplicate.json()["result"] == "DUPLICATE"
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "RECEIPT_ID_CONFLICT"
    assert not_owned.status_code == 404
    assert not_owned.json()["error"]["code"] == "ACTION_NOT_FOUND"
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "UNAUTHORIZED"

    with psycopg2.connect(_database_url()) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT status, receipt_payload->'telegramResult'->>'messageId'
                FROM attendance_gateway_delivery_receipts
                WHERE receipt_id = %s
                """,
                ("rcpt.attendance.1001",),
            )
            assert cursor.fetchall() == [("DELIVERED", "91001")]
