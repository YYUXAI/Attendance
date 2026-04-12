from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import Message

from services import checkin_service


router = Router()
log = logging.getLogger(__name__)

def _extract_file_id(message: Message) -> str | None:
    if message.document:
        return message.document.file_id
    if message.photo:
        largest = max(message.photo, key=lambda p: (p.file_size or 0, p.width, p.height))
        return largest.file_id
    return None


def _has_checkin_tag(message: Message) -> bool:
    text = message.text or ""
    caption = message.caption or ""
    return ("#打卡" in text) or ("#打卡" in caption)


async def _handle_checkin_message(message: Message) -> None:
    if not message.from_user:
        log.info("[CHECKIN_HANDLER_RETURN] tg_id=None reason=no_from_user")
        return

    text = message.text or message.caption or ""
    has_hashtag = "#打卡" in text
    file_id = _extract_file_id(message)

    prepared = checkin_service.validate_and_prepare(
        tg_id=message.from_user.id,
        chat_id=message.chat.id,
        has_hashtag=has_hashtag,
        file_id=file_id,
    )

    if not isinstance(prepared, tuple):
        await message.reply(text=prepared.message)
        log.info(
            "[CHECKIN_HANDLER_RETURN] tg_id=%s reason=validate_failed_replied",
            message.from_user.id,
        )
        return

    employee_id, shift_id, english_name, department_name, cin, cout, tz = prepared
    clock_time_utc = checkin_service.persist_clock_record(
        tg_id=message.from_user.id,
        chat_id=message.chat.id,
        file_id=file_id,  # type: ignore[arg-type]
        employee_id=employee_id,
        shift_id=shift_id,
    )
    body = checkin_service.format_success_message(
        english_name=english_name,
        employee_id=employee_id,
        department_name=department_name,
        shift_checkin_time=cin,
        shift_checkout_time=cout,
        timezone_name=tz,
        clock_time_utc=clock_time_utc,
        file_id=file_id,  # type: ignore[arg-type]
    )
    await message.reply(text=body)
    log.info("[CHECKIN_HANDLER_RETURN] tg_id=%s reason=success_replied", message.from_user.id)


CHECKIN_FILTER = F.chat.type.in_({"group", "supergroup"}) & (
    F.text.contains("#打卡") | F.caption.contains("#打卡")
)


@router.message(CHECKIN_FILTER)
async def checkin_message_handler(message: Message) -> None:
    tid = message.from_user.id if message.from_user else None
    log.info(
        "[CHECKIN_HANDLER_ENTER] tg_id=%s chat_type=%s chat_id=%s has_text=%s has_caption=%s",
        tid,
        message.chat.type,
        message.chat.id,
        message.text is not None,
        message.caption is not None,
    )
    if not _has_checkin_tag(message):
        log.info("[CHECKIN_HANDLER_RETURN] tg_id=%s reason=no_checkin_tag", tid)
        return
    await _handle_checkin_message(message)


@router.edited_message(CHECKIN_FILTER)
async def checkin_edited_message_handler(message: Message) -> None:
    tid = message.from_user.id if message.from_user else None
    log.info(
        "[CHECKIN_EDIT_HANDLER_ENTER] tg_id=%s chat_type=%s chat_id=%s",
        tid,
        message.chat.type,
        message.chat.id,
    )
    if not _has_checkin_tag(message):
        log.info("[CHECKIN_EDIT_HANDLER_RETURN] tg_id=%s reason=no_checkin_tag", tid)
        return
    await _handle_checkin_message(message)
