from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from services import profile_service

router = Router()
log = logging.getLogger(__name__)


@router.callback_query(F.data == "profile:myinfo")
async def myinfo_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message is None:
        return

    user = callback.from_user
    if not user:
        return

    res = profile_service.get_my_profile_by_tg_id(tg_id=int(user.id))
    await callback.message.reply(text=res.message)
    log.info("[PROFILE_MYINFO] tg_id=%s ok=%s error_code=%s", user.id, res.ok, res.error_code)

