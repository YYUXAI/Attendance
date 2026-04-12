from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import BaseFilter
from aiogram.types import Message

from services import admin_test_service


router = Router()
log = logging.getLogger(__name__)


def _is_standard_test_command_line(s: str) -> bool:
    """
    标准命令：整段 text/caption 经 strip 后为 /test，或群内 /test@BotUserName（无额外参数、无空格）。
    """
    t = s.strip()
    if t == "/test":
        return True
    if t.startswith("/test@") and " " not in t and len(t) > len("/test@"):
        return True
    return False


class AdminTestCommandFilter(BaseFilter):
    """仅匹配当前消息 text 或 caption 上的标准 /test。"""

    async def __call__(self, message: Message) -> bool:
        if message.text is not None and _is_standard_test_command_line(message.text):
            return True
        if message.caption is not None and _is_standard_test_command_line(message.caption):
            return True
        return False


def _attachment_file_id_from_message(message: Message) -> str | None:
    """当前消息：document 优先，否则取最大尺寸 photo；不下载文件。"""
    if message.document:
        return message.document.file_id
    if message.photo:
        return message.photo[-1].file_id
    return None


@router.message(AdminTestCommandFilter())
async def admin_test_handler(message: Message) -> None:
    user = message.from_user
    if user is None:
        log.info("[ADMIN_TEST] skip: no from_user")
        return

    attachment_file_id = _attachment_file_id_from_message(message)
    text = admin_test_service.build_test_command_reply(
        tg_id=int(user.id),
        tg_username=user.username,
        chat_id=int(message.chat.id),
        attachment_file_id=attachment_file_id,
    )
    await message.reply(text=text)
