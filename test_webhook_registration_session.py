from __future__ import annotations

import asyncio

import webhook_app
from webhook_app import _registration_session_state


class _Request:
    def __init__(self, payload, *, secret="test-secret"):
        self._payload = payload
        self.headers = {"x-omniai-unified-bot-secret-token": secret}

    async def json(self):
        return self._payload


def test_private_registration_session_state_comes_from_attendance_owner(monkeypatch) -> None:
    monkeypatch.setattr(
        "webhook_app.register_service.is_waiting_register_input",
        lambda *, bot_owner, tg_id, private_chat_id: (
            bot_owner == "ux_assistant" and tg_id == 42 and private_chat_id == 42
        ),
    )

    assert _registration_session_state({
        "message": {
            "chat": {"id": 42, "type": "private"},
            "from": {"id": 42},
        },
    }, bot_owner="ux_assistant") == "active"
    assert _registration_session_state({
        "callback_query": {
            "from": {"id": 43},
            "message": {"chat": {"id": 43, "type": "private"}},
        },
    }, bot_owner="ux_assistant") == "ended"
    assert _registration_session_state({
        "message": {
            "chat": {"id": -1001, "type": "supergroup"},
            "from": {"id": 42},
        },
    }, bot_owner="ux_assistant") is None


def test_internal_session_status_reads_attendance_owner(monkeypatch) -> None:
    monkeypatch.setenv("WEBHOOK_SECRET_TOKEN", "test-secret")
    webhook_app.app.state.bot_owner = "ux_assistant"
    calls = []
    monkeypatch.setattr(
        webhook_app.register_service,
        "is_waiting_register_input",
        lambda **kwargs: calls.append(kwargs) or True,
    )

    result = asyncio.run(webhook_app.private_registration_session_status(_Request({
        "telegram_user_id": "42",
        "private_chat_id": "42",
    })))

    assert result == {"status": "active"}
    assert calls == [{
        "bot_owner": "ux_assistant",
        "tg_id": 42,
        "private_chat_id": 42,
    }]


def test_internal_session_clear_ends_attendance_owner_session(monkeypatch) -> None:
    monkeypatch.setenv("WEBHOOK_SECRET_TOKEN", "test-secret")
    webhook_app.app.state.bot_owner = "ux_assistant"
    calls = []
    monkeypatch.setattr(
        webhook_app.register_service,
        "clear_waiting_register_input",
        lambda **kwargs: calls.append(kwargs),
    )

    result = asyncio.run(webhook_app.clear_private_registration_session(_Request({
        "telegram_user_id": 43,
        "private_chat_id": 43,
    })))

    assert result == {"status": "ended"}
    assert calls == [{"bot_owner": "ux_assistant", "tg_id": 43}]


def test_internal_session_contract_rejects_unauthorized_or_invalid_requests(monkeypatch) -> None:
    monkeypatch.setenv("WEBHOOK_SECRET_TOKEN", "test-secret")
    webhook_app.app.state.bot_owner = "ux_assistant"

    unauthorized = asyncio.run(webhook_app.private_registration_session_status(
        _Request({"telegram_user_id": "42", "private_chat_id": "42"}, secret="wrong")
    ))
    invalid = asyncio.run(webhook_app.private_registration_session_status(
        _Request({"telegram_user_id": "not-an-id", "private_chat_id": "42"})
    ))
    webhook_app.app.state.bot_owner = "legacy_attendance"
    wrong_owner = asyncio.run(webhook_app.private_registration_session_status(
        _Request({"telegram_user_id": "42", "private_chat_id": "42"})
    ))

    assert unauthorized.status_code == 401
    assert invalid.status_code == 400
    assert wrong_owner.status_code == 409


def test_webhook_has_no_automatic_notification_delivery_activation() -> None:
    assert not hasattr(webhook_app, "_activate_notification_delivery_for_update")
