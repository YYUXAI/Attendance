from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from handlers import private_callback_session


def _private_callback(data: str):
    return SimpleNamespace(
        data=data,
        from_user=SimpleNamespace(id=42),
        message=SimpleNamespace(chat=SimpleNamespace(type="private")),
        answer=AsyncMock(),
    )


def test_active_non_registration_callback_ends_registration_session_before_handler(monkeypatch) -> None:
    cleared: list[tuple[str, int]] = []
    monkeypatch.setenv("ATTENDANCE_BOT_OWNER", "ux_assistant")
    monkeypatch.setattr(
        private_callback_session.register_service,
        "clear_waiting_register_input",
        lambda *, bot_owner, tg_id: cleared.append((bot_owner, tg_id)),
    )
    middleware = private_callback_session.PrivateAttendanceCallbackSessionExitMiddleware()
    handler = AsyncMock(return_value="handled")

    result = asyncio.run(middleware(handler, _private_callback("act:export"), {}))

    assert result == "handled"
    assert cleared == [("ux_assistant", 42)]
    handler.assert_awaited_once()


def test_registration_callbacks_do_not_get_cleared_by_feature_middleware(monkeypatch) -> None:
    cleared: list[tuple[str, int]] = []
    monkeypatch.setattr(
        private_callback_session.register_service,
        "clear_waiting_register_input",
        lambda **kwargs: cleared.append((kwargs["bot_owner"], kwargs["tg_id"])),
    )
    middleware = private_callback_session.PrivateAttendanceCallbackSessionExitMiddleware()

    for data in ("reg:begin", "reg:confirm:token", "reg:cancel:token"):
        asyncio.run(middleware(AsyncMock(), _private_callback(data), {}))

    assert cleared == []
