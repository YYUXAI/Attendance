from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery

from infra.bot_owner import load_attendance_bot_owner
from services import register_service


_REGISTRATION_CALLBACK_PREFIXES = (
    "reg:begin",
    "reg:confirm:",
    "reg:cancel:",
)


class PrivateAttendanceCallbackSessionExitMiddleware(BaseMiddleware):
    """Selecting another private feature ends the active registration flow."""

    async def __call__(
        self,
        handler: Callable[[CallbackQuery, Dict[str, Any]], Awaitable[Any]],
        event: CallbackQuery,
        data: Dict[str, Any],
    ) -> Any:
        callback_data = (event.data or "").strip()
        chat = event.message.chat if event.message is not None else None
        if (
            chat is not None
            and chat.type == "private"
            and callback_data
            and not callback_data.startswith(_REGISTRATION_CALLBACK_PREFIXES)
        ):
            register_service.clear_waiting_register_input(
                bot_owner=load_attendance_bot_owner(),
                tg_id=int(event.from_user.id),
            )
        return await handler(event, data)
