from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import webhook_app
from repositories.telegram_update_inbox_repo import UpdateClaim


class FakeRequest:
    def __init__(self, data):
        self._data = data
        self.headers = {"x-omniai-unified-bot-secret-token": "test-secret"}

    async def json(self):
        return self._data


class FakeDispatcher:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.calls = []

    async def feed_update(self, bot, update):
        self.calls.append((bot, update))
        if self.error:
            raise self.error


def _prepare(monkeypatch, *, claim: UpdateClaim, dispatcher: FakeDispatcher):
    monkeypatch.setenv("WEBHOOK_SECRET_TOKEN", "test-secret")
    monkeypatch.setattr(
        webhook_app.Update,
        "model_validate",
        lambda data, context: SimpleNamespace(update_id=data["update_id"]),
    )
    monkeypatch.setattr(
        webhook_app.telegram_update_inbox_repo,
        "claim_update",
        lambda **kwargs: claim,
    )
    monkeypatch.setattr(webhook_app, "_registration_session_state", lambda *args, **kwargs: None)
    webhook_app.app.state.bot = object()
    webhook_app.app.state.dp = dispatcher
    webhook_app.app.state.bot_owner = "ux_assistant"


def test_completed_update_is_not_dispatched_again(monkeypatch):
    dispatcher = FakeDispatcher()
    _prepare(
        monkeypatch,
        claim=UpdateClaim(state="completed"),
        dispatcher=dispatcher,
    )

    result = asyncio.run(
        webhook_app.telegram_webhook(FakeRequest({"update_id": 1001}))
    )

    assert result == {"ok": True, "duplicate": True}
    assert dispatcher.calls == []


def test_claimed_update_completes_only_after_dispatch(monkeypatch):
    dispatcher = FakeDispatcher()
    _prepare(
        monkeypatch,
        claim=UpdateClaim(state="claimed", claim_token="claim"),
        dispatcher=dispatcher,
    )
    completions = []
    monkeypatch.setattr(
        webhook_app.telegram_update_inbox_repo,
        "complete_update",
        lambda **kwargs: completions.append(kwargs) or True,
    )

    result = asyncio.run(
        webhook_app.telegram_webhook(FakeRequest({"update_id": 1002}))
    )

    assert result == {"ok": True}
    assert len(dispatcher.calls) == 1
    assert completions[0]["bot_owner"] == "ux_assistant"


def test_failed_dispatch_marks_update_retryable_and_propagates(monkeypatch):
    dispatcher = FakeDispatcher(error=RuntimeError("handler failed"))
    _prepare(
        monkeypatch,
        claim=UpdateClaim(state="claimed", claim_token="claim"),
        dispatcher=dispatcher,
    )
    failures = []
    monkeypatch.setattr(
        webhook_app.telegram_update_inbox_repo,
        "fail_update",
        lambda **kwargs: failures.append(kwargs) or True,
    )

    with pytest.raises(RuntimeError, match="handler failed"):
        asyncio.run(
            webhook_app.telegram_webhook(FakeRequest({"update_id": 1003}))
        )

    assert failures[0]["error_code"] == "RuntimeError"


def test_busy_update_returns_retryable_http_error(monkeypatch):
    dispatcher = FakeDispatcher()
    _prepare(
        monkeypatch,
        claim=UpdateClaim(state="busy"),
        dispatcher=dispatcher,
    )

    response = asyncio.run(
        webhook_app.telegram_webhook(FakeRequest({"update_id": 1004}))
    )

    assert response.status_code == 409
    assert dispatcher.calls == []


def test_boolean_update_id_is_rejected(monkeypatch):
    dispatcher = FakeDispatcher()
    _prepare(
        monkeypatch,
        claim=UpdateClaim(state="claimed", claim_token="claim"),
        dispatcher=dispatcher,
    )

    response = asyncio.run(
        webhook_app.telegram_webhook(FakeRequest({"update_id": True}))
    )

    assert response.status_code == 400
    assert dispatcher.calls == []


def test_webhook_update_never_activates_notification_delivery(monkeypatch):
    dispatcher = FakeDispatcher()
    _prepare(
        monkeypatch,
        claim=UpdateClaim(state="claimed", claim_token="claim"),
        dispatcher=dispatcher,
    )
    monkeypatch.setattr(
        webhook_app,
        "get_cursor",
        lambda: (_ for _ in ()).throw(
            AssertionError("webhook update must not mutate delivery ownership")
        ),
    )
    monkeypatch.setattr(
        webhook_app.telegram_update_inbox_repo,
        "complete_update",
        lambda **kwargs: True,
    )

    result = asyncio.run(
        webhook_app.telegram_webhook(FakeRequest({
            "update_id": 1005,
            "message": {"chat": {"id": 42, "type": "private"}},
        }))
    )

    assert result == {"ok": True}
    assert len(dispatcher.calls) == 1
