from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.types import Message

from domain.clock_matter import (
    parse_employee_id_from_text,
    parse_english_name_from_text,
    parse_matter_from_text,
    validate_caption_for_remote_diff,
    validate_caption_identity_for_sender,
)
from infra.bot_owner import load_attendance_bot_owner
from infra.checkin_remote_diff_config import requires_remote_diff_checkin
from infra.log_redaction import redacted_ref
from infra.test_group_google_config import is_test_group_chat
from services import checkin_ai_orchestrator, checkin_service
from services.checkin_recognition_log import log_checkin_recognition
from services.checkin_user_message import user_message_for_checkin_error
from services.bbq_google_sheets_export_service import schedule_bbq_sheets_sync_after_checkin
from services.test_group_google_sheets_service import (
    schedule_test_group_sheets_sync_after_checkin,
)
router = Router()
log = logging.getLogger(__name__)


async def _reply_checkin(message: Message, text: str) -> None:
    try:
        await message.reply(text=text)
    except Exception:
        try:
            await message.answer(text=text)
        except Exception:
            log.exception(
                "checkin: failed to reply tg_ref=%s",
                redacted_ref(message.from_user.id if message.from_user else None),
            )


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
        log.info(
            "[CHECKIN_HANDLER_RETURN] tg_ref=%s reason=no_attachment",
            redacted_ref(message.from_user.id),
        )
        return

    matter = parse_matter_from_text(message.caption)
    if matter not in {"签到", "签退"}:
        log.info(
            "[CHECKIN_HANDLER_RETURN] tg_ref=%s reason=no_matter_in_caption_skip",
            redacted_ref(message.from_user.id),
        )
        await _reply_checkin(
            message,
            "打卡未处理：请用「↗ 签到/签退」模板发送，或确保图片说明里包含「签到」或「签退」。",
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
            "[CHECKIN_HANDLER_RETURN] tg_ref=%s reason=validate_failed_replied code=%s",
            redacted_ref(message.from_user.id),
            prepared.error_code,
        )
        return

    employee_id, shift_id, english_name, _department_name, _cin, _cout, _tz = prepared

    chat_id = int(message.chat.id)
    chat_title = message.chat.title if message.chat else None
    allowed, deny_reason = checkin_service.should_accept_checkin_for_chat_roster(
        chat_id=chat_id,
        employee_id=str(employee_id),
        tz_name="Asia/Shanghai",
    )
    ai_dry_run = checkin_service.should_run_ai_without_persist(
        chat_id=chat_id,
        employee_id=str(employee_id),
        roster_allowed=allowed,
        chat_title=chat_title,
    )
    if not allowed and not ai_dry_run:
        # 保持原 Attendance 行为；融合边界只负责阻止重复落账。
        success_text = f"{matter}成功"
        await message.reply(text=success_text)
        log.info(
            "[CHECKIN_HANDLER_RETURN] tg_ref=%s reason=chat_roster_denied detail=%s chat_ref=%s employee_ref=%s",
            redacted_ref(message.from_user.id),
            deny_reason,
            redacted_ref(chat_id),
            redacted_ref(employee_id),
        )
        return

    from infra.checkin_employee_id_only_config import requires_employee_id_only_checkin

    is_remote_group = requires_remote_diff_checkin(chat_id=chat_id, chat_title=chat_title)
    if is_remote_group or requires_employee_id_only_checkin(
        chat_id=chat_id, chat_title=chat_title
    ):
        caption_err = validate_caption_for_remote_diff(
            caption=message.caption,
            employee_id=employee_id,
        )
    else:
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
            "[CHECKIN_HANDLER_RETURN] tg_ref=%s reason=caption_identity_mismatch "
            "cap_name_ref=%s cap_employee_ref=%s reg_name_ref=%s reg_employee_ref=%s",
            redacted_ref(message.from_user.id),
            redacted_ref(cap_en),
            redacted_ref(cap_eid),
            redacted_ref(english_name),
            redacted_ref(employee_id),
        )
        return

    bot_owner = load_attendance_bot_owner()
    source_message_id = int(message.message_id)
    if checkin_service.has_processed_telegram_checkin(
        bot_owner=bot_owner,
        source_chat_id=chat_id,
        source_message_id=source_message_id,
    ):
        await _reply_checkin(message, "该打卡消息已处理，本次未重复记账。")
        log.info("[CHECKIN_HANDLER_RETURN] reason=telegram_source_already_processed")
        return

    if ai_dry_run:
        await _reply_checkin(
            message,
            f"已收到{matter}截图，正在 AI 识别（试跑不入库）…",
        )
    else:
        await _reply_checkin(message, f"已收到{matter}截图，正在识别，请稍候…")

    sent_utc = message.date
    if sent_utc is not None and sent_utc.tzinfo is None:
        from datetime import timezone

        sent_utc = sent_utc.replace(tzinfo=timezone.utc)
    # 按业务要求：截图时间统一按北京时间校验，不跟随班次时区。
    try:
        ai_out = await checkin_ai_orchestrator.resolve_clock_time_with_ai(
            bot=bot,
            file_id=file_id,
            tg_id=message.from_user.id,
            shift_timezone="Asia/Shanghai",
            message_sent_utc=sent_utc,
            caption=message.caption,
            chat_id=chat_id,
            chat_title=chat_title,
        )
    except Exception:
        log.exception(
            "[CHECKIN_HANDLER_RETURN] tg_ref=%s reason=ai_exception",
            redacted_ref(message.from_user.id),
        )
        err_text = "打卡失败：识别异常，请稍后重试。"
        try:
            await message.reply(text=err_text)
        except Exception:
            await message.answer(text=err_text)
        return
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
            "[CHECKIN_HANDLER_RETURN] tg_ref=%s reason=ai_failed_replied code=%s",
            redacted_ref(message.from_user.id),
            ai_out.error_code,
        )
        return

    if ai_dry_run:
        log_checkin_recognition(
            stage="ai_dry_run_ok",
            tg_id=int(message.from_user.id),
            extraction=ai_out.extraction,
            employee_id=employee_id,
            clock_time_utc=ai_out.clock_time_utc,
            matter=matter,
        )
        log.info(
            "[CHECKIN_HANDLER_RETURN] tg_ref=%s reason=ai_dry_run_success chat_ref=%s employee_ref=%s clock_time_utc=%s",
            redacted_ref(message.from_user.id),
            redacted_ref(chat_id),
            redacted_ref(employee_id),
            ai_out.clock_time_utc,
        )
        ext = ai_out.extraction
        image_name = ext.display_name if ext else None
        success_text = checkin_service.format_ai_dry_run_success_message(
            english_name=english_name or "",
            employee_id=str(employee_id),
            clock_time_utc=ai_out.clock_time_utc,
            matter=matter,
            used_ai_time=ai_out.used_ai_time,
            verified_image_user=ai_out.verified_image_user,
            image_display_name=image_name,
            timezone_name="Asia/Shanghai",
        )
        try:
            await message.reply(text=success_text)
        except Exception:
            await message.answer(text=success_text)
        return

    _, inserted = checkin_service.persist_telegram_clock_record(
        bot_owner=bot_owner,
        source_chat_id=chat_id,
        source_message_id=source_message_id,
        tg_id=message.from_user.id,
        file_id=file_id,
        employee_id=employee_id,
        shift_id=shift_id,
        clock_time_utc=ai_out.clock_time_utc,
        clock_action=matter,
    )
    if not inserted:
        await _reply_checkin(message, "该打卡消息已处理，本次未重复记账。")
        log.info("[CHECKIN_HANDLER_RETURN] reason=telegram_source_race_deduplicated")
        return
    log_checkin_recognition(
        stage="saved",
        tg_id=int(message.from_user.id),
        extraction=ai_out.extraction,
        employee_id=employee_id,
        clock_time_utc=ai_out.clock_time_utc,
        matter=matter,
    )
    log.info(
        "[CHECKIN_HANDLER_RETURN] tg_ref=%s reason=success_silent clock_time_utc=%s",
        redacted_ref(message.from_user.id),
        ai_out.clock_time_utc,
    )
    if is_test_group_chat(chat_id=chat_id, chat_title=chat_title):
        success_text = checkin_service.format_test_group_success_message(
            english_name=english_name or "",
            clock_time_utc=ai_out.clock_time_utc,
            matter=matter,
            timezone_name="Asia/Shanghai",
        )
    else:
        success_text = f"{matter}成功"
    try:
        await message.reply(text=success_text)
    except Exception:
        await message.answer(text=success_text)
    schedule_test_group_sheets_sync_after_checkin(
        bot=bot,
        chat_id=int(message.chat.id),
    )
    schedule_bbq_sheets_sync_after_checkin(
        bot=bot,
        chat_id=int(message.chat.id),
    )


CHECKIN_FILTER = F.chat.type.in_({"group", "supergroup"}) & (F.photo | F.document)


@router.message(CHECKIN_FILTER)
async def checkin_message_handler(message: Message, bot: Bot) -> None:
    tid = message.from_user.id if message.from_user else None
    log.info(
        "[CHECKIN_HANDLER_ENTER] tg_ref=%s chat_type=%s chat_ref=%s has_photo=%s has_document=%s",
        redacted_ref(tid),
        message.chat.type,
        redacted_ref(message.chat.id),
        message.photo is not None,
        message.document is not None,
    )
    await _handle_checkin_message(message, bot)


@router.edited_message(CHECKIN_FILTER)
async def checkin_edited_message_handler(message: Message, bot: Bot) -> None:
    tid = message.from_user.id if message.from_user else None
    log.info(
        "[CHECKIN_EDIT_HANDLER_ENTER] tg_ref=%s chat_type=%s chat_ref=%s",
        redacted_ref(tid),
        message.chat.type,
        redacted_ref(message.chat.id),
    )
    await _handle_checkin_message(message, bot)
