from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from services import profile_service
from services import register_service

router = Router()
log = logging.getLogger(__name__)


async def _reply_myinfo(*, message: Message, tg_id: int) -> None:
    register_service.clear_waiting_register_input(tg_id=tg_id)
    res = profile_service.get_my_profile_by_tg_id(tg_id=tg_id)
    await message.reply(text=res.message)
    log.info("[PROFILE_MYINFO] tg_id=%s ok=%s error_code=%s", tg_id, res.ok, res.error_code)


@router.message(F.text == "我的信息")
async def myinfo_message(message: Message) -> None:
    user = message.from_user
    if not user or message.chat.type != "private":
        return
    await _reply_myinfo(message=message, tg_id=int(user.id))


@router.callback_query(F.data == "profile:myinfo")
async def myinfo_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return

    user = callback.from_user
    if not user:
        return

    await _reply_myinfo(message=callback.message, tg_id=int(user.id))

