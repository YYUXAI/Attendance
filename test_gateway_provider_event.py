from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

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
                "DELETE FROM gateway_processed_events WHERE event_id LIKE %s",
                ("evt-attendance-%",),
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
                "DELETE FROM employee_shift_calendar WHERE employee_id = %s",
                ("74808",),
            )
            cursor.execute(
                "DELETE FROM employee_shift_config WHERE employee_id = %s",
                ("74808",),
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
                SET created_at = clock_timestamp() - interval '20 minutes',
                    last_activity_at = clock_timestamp() - interval '16 minutes',
                    inactivity_expires_at = clock_timestamp() - interval '1 minute',
                    absolute_expires_at = clock_timestamp() - interval '1 minute',
                    preview_expires_at = clock_timestamp() - interval '1 minute'
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
