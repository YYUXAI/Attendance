from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from domain.shared.result import ServiceResult
from infra.telegram_group_link import build_supergroup_open_url
from repositories.shifts_repo import list_by_attendance_group_id
from services import group_attendance_summary_service

log = logging.getLogger(__name__)


async def reply_wrong_group_hint(*, message: Message, bot: Bot, result: ServiceResult) -> None:
    """错群打卡：提示正确考勤群，并提供跳转 / 改用本群按钮。"""
    expected_id = result.expected_attendance_group_id
    current_id = result.current_attendance_group_id or (message.chat.id if message.chat else None)

    group_title = "您的考勤群"
    open_url: str | None = None
    if expected_id is not None:
        open_url = build_supergroup_open_url(chat_id=int(expected_id))
        try:
            chat = await bot.get_chat(int(expected_id))
            title = (getattr(chat, "title", None) or "").strip()
            if title:
                group_title = title
        except Exception as e:
            log.warning("wrong_group get_chat failed expected_id=%s: %s", expected_id, e)
        if group_title == "您的考勤群":
            group_title = await group_attendance_summary_service.resolve_group_display_name(
                bot=bot,
                chat_id=int(expected_id),
            )

    lines = [f"打卡失败，请前往考勤群「{group_title}」打卡。"]
    rows: list[list[InlineKeyboardButton]] = []
    if open_url:
        rows.append([InlineKeyboardButton(text="前往我的考勤群", url=open_url)])

    can_switch_here = False
    if current_id is not None:
        shifts_here = list_by_attendance_group_id(attendance_group_id=int(current_id))
        can_switch_here = len(shifts_here) == 1 and (
            expected_id is None or int(current_id) != int(expected_id)
        )
    if can_switch_here:
        lines.append("若您已长期在本群工作，可改用本群作为考勤群。")
        rows.append([InlineKeyboardButton(text="改用本群打卡", callback_data="act:switch_group")])

    markup = InlineKeyboardMarkup(inline_keyboard=rows) if rows else None
    await message.reply("\n".join(lines), reply_markup=markup)
