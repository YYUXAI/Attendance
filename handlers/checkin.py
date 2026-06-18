from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import Message

from domain.clock_matter import (
    parse_employee_id_from_text,
    parse_english_name_from_text,
    parse_matter_from_text,
    validate_caption_identity_for_sender,
)
from services import checkin_ai_orchestrator, checkin_service
from services.checkin_recognition_log import log_checkin_recognition
from services.checkin_user_message import user_message_for_checkin_error
router = Router()
log = logging.getLogger(__name__)


def _extract_file_id(message: Message) -> str | None:
    if message.document:
        return message.document.file_id
    if message.photo:
        # Telegram 按尺寸升序排列，末尾为最大分辨率（勿仅按 file_size，避免选到压扁预览图）
        largest = max(
            message.photo,
            key=lambda p: ((p.width or 0) * (p.height or 0), p.file_size or 0),
        )
        return largest.file_id
    return None


async def _handle_checkin_message(message: Message, bot: Bot) -> None:
    if not message.from_user:
        log.info("[CHECKIN_HANDLER_RETURN] tg_id=None reason=no_from_user")
        return

    file_id = _extract_file_id(message)
    if not file_id:
        log.info("[CHECKIN_HANDLER_RETURN] tg_id=%s reason=no_attachment", message.from_user.id)
        return

    matter = parse_matter_from_text(message.caption)
    if matter not in {"签到", "签退"}:
        log.info(
            "[CHECKIN_HANDLER_RETURN] tg_id=%s reason=no_matter_in_caption_skip",
            message.from_user.id,
        )
        return

    prepared = checkin_service.validate_and_prepare(
        tg_id=message.from_user.id,
        chat_id=message.chat.id,
        file_id=file_id,
    )

    if not isinstance(prepared, tuple):
        await message.reply(text=prepared.message)
        log.info(
            "[CHECKIN_HANDLER_RETURN] tg_id=%s reason=validate_failed_replied code=%s",
            message.from_user.id,
            prepared.error_code,
        )
        return

    employee_id, shift_id, english_name, _department_name, _cin, _cout, _tz = prepared

    caption_err = validate_caption_identity_for_sender(
        caption=message.caption,
        english_name=english_name,
        employee_id=employee_id,
    )
    if caption_err:
        cap_en = parse_english_name_from_text(message.caption)
        cap_eid = parse_employee_id_from_text(message.caption)
        await message.reply(text=user_message_for_checkin_error(caption_err))
        log.info(
            "[CHECKIN_HANDLER_RETURN] tg_id=%s reason=caption_identity_mismatch "
            "cap_en=%r cap_eid=%r reg_en=%r reg_eid=%r",
            message.from_user.id,
            cap_en,
            cap_eid,
            english_name,
            employee_id,
        )
        return

    sent_utc = message.date
    if sent_utc is not None and sent_utc.tzinfo is None:
        from datetime import timezone

        sent_utc = sent_utc.replace(tzinfo=timezone.utc)
    # 按业务要求：截图时间统一按北京时间校验，不跟随班次时区。
    ai_out = await checkin_ai_orchestrator.resolve_clock_time_with_ai(
        bot=bot,
        file_id=file_id,
        tg_id=message.from_user.id,
        shift_timezone="Asia/Shanghai",
        message_sent_utc=sent_utc,
        caption=message.caption,
    )
    if not isinstance(ai_out, checkin_ai_orchestrator.CheckinAiResolveResult):
        try:
            await message.reply(text=ai_out.message)
        except Exception:
            await message.answer(text=ai_out.message)
        log_checkin_recognition(
            stage="handler_rejected",
            tg_id=int(message.from_user.id),
            employee_id=employee_id,
            error_code=ai_out.error_code,
        )
        log.info(
            "[CHECKIN_HANDLER_RETURN] tg_id=%s reason=ai_failed_replied code=%s",
            message.from_user.id,
            ai_out.error_code,
        )
        return

    checkin_service.persist_clock_record(
        tg_id=message.from_user.id,
        chat_id=message.chat.id,
        file_id=file_id,
        employee_id=employee_id,
        shift_id=shift_id,
        clock_time_utc=ai_out.clock_time_utc,
        clock_action=matter,
    )
    log_checkin_recognition(
        stage="saved",
        tg_id=int(message.from_user.id),
        extraction=ai_out.extraction,
        employee_id=employee_id,
        clock_time_utc=ai_out.clock_time_utc,
        matter=matter,
    )
    log.info(
        "[CHECKIN_HANDLER_RETURN] tg_id=%s reason=success_silent clock_time_utc=%s",
        message.from_user.id,
        ai_out.clock_time_utc,
    )
    try:
        await message.reply(text=f"{matter}成功")
    except Exception:
        await message.answer(text=f"{matter}成功")


CHECKIN_FILTER = F.chat.type.in_({"group", "supergroup"}) & (F.photo | F.document)


@router.message(CHECKIN_FILTER)
async def checkin_message_handler(message: Message, bot: Bot) -> None:
    tid = message.from_user.id if message.from_user else None
    log.info(
        "[CHECKIN_HANDLER_ENTER] tg_id=%s chat_type=%s chat_id=%s has_photo=%s has_document=%s",
        tid,
        message.chat.type,
        message.chat.id,
        message.photo is not None,
        message.document is not None,
    )
    await _handle_checkin_message(message, bot)


@router.edited_message(CHECKIN_FILTER)
async def checkin_edited_message_handler(message: Message, bot: Bot) -> None:
    tid = message.from_user.id if message.from_user else None
    log.info(
        "[CHECKIN_EDIT_HANDLER_ENTER] tg_id=%s chat_type=%s chat_id=%s",
        tid,
        message.chat.type,
        message.chat.id,
    )
    await _handle_checkin_message(message, bot)
