from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from psycopg2.extensions import cursor as Cursor

from domain.clock_matter import (
    parse_matter_from_text,
    validate_caption_for_remote_diff,
    validate_caption_identity_for_sender,
)
from domain.shared.result import ServiceResult
from gateway_provider.contracts import (
    GatewayEventRequest,
    GatewayEventResponse,
    SendMessageAction,
    TelegramEditedMessageUpdate,
    TelegramMessage,
    TelegramMessageUpdate,
    UnchangedSessionDirective,
)
from gateway_provider.gateway_file_client import (
    GatewayFileReader,
    GatewayFileTooLargeError,
)
from infra.checkin_ai_config import load_checkin_ai_config
from infra.checkin_employee_id_only_config import requires_employee_id_only_checkin
from infra.checkin_remote_diff_config import requires_remote_diff_checkin
from infra.test_group_google_config import is_test_group_chat
from repositories import clock_records_repo, registrations_repo
from services import checkin_ai_orchestrator, checkin_service
from services.checkin_user_message import user_message_for_checkin_error


def process_group_checkin(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramMessageUpdate | TelegramEditedMessageUpdate,
    file_reader: GatewayFileReader,
) -> GatewayEventResponse:
    message = _checkin_message(update)
    sender = message.sender
    if sender is None:
        return _reply(request, update, "打卡失败：无法识别发送者。")
    matter = parse_matter_from_text(message.caption)
    if matter not in {"签到", "签退"}:
        return _reply(
            request,
            update,
            (
                "打卡未处理：请用「↗ 签到/签退」模板发送，"
                "或确保图片说明里包含「签到」或「签退」。"
            ),
        )
    if len(request.telegramFiles) != 1:
        return _reply(request, update, "打卡失败：附件引用无效，请重新发送截图。")
    attachment = request.telegramFiles[0]
    expected_kind = "DOCUMENT" if message.document is not None else "PHOTO"
    if attachment.kind != expected_kind:
        return _reply(request, update, "打卡失败：附件类型不匹配，请重新发送截图。")

    registration = registrations_repo.get_by_tg_id_cur(cursor, tg_id=sender.id)
    if registration is None:
        return _reply(request, update, "打卡失败，您尚未注册")
    sent_at_utc = datetime.fromtimestamp(message.date, tz=timezone.utc)
    year_month = sent_at_utc.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")
    roster_source = checkin_service.formal_group_roster_source_for_chat(
        chat_id=message.chat.id,
    )
    roster_allowed = _employee_in_roster(
        cursor,
        year_month=year_month,
        roster_source=roster_source,
        employee_id=registration.employee_id,
    )
    ai_dry_run = checkin_service.should_run_ai_without_persist(
        chat_id=message.chat.id,
        employee_id=registration.employee_id,
        roster_allowed=roster_allowed,
        chat_title=message.chat.title,
    )
    if not roster_allowed and not ai_dry_run:
        return _reply(request, update, "打卡失败：您不在本群当前班表，未记账。")

    caption_error = _caption_error(
        caption=message.caption,
        english_name=registration.english_name or "",
        employee_id=registration.employee_id,
        chat_id=message.chat.id,
        chat_title=message.chat.title,
    )
    if caption_error is not None:
        return _reply(request, update, user_message_for_checkin_error(caption_error))
    if clock_records_repo.has_telegram_source_cur(
        cursor,
        source_chat_id=message.chat.id,
        source_message_id=message.message_id,
    ):
        return _reply(request, update, "该打卡消息已处理，本次未重复记账。")

    try:
        image_bytes = file_reader.read(
            file_ref=attachment.fileRef,
            declared_size_bytes=attachment.sizeBytes,
        )
    except GatewayFileTooLargeError:
        return _reply(request, update, "打卡失败：截图超过 20 MiB。")
    resolved = _resolve_checkin(
        image_bytes=image_bytes,
        tg_id=sender.id,
        message_sent_utc=sent_at_utc,
        caption=message.caption,
        chat_id=message.chat.id,
        chat_title=message.chat.title,
        registration=registration,
    )
    if isinstance(resolved, ServiceResult):
        return _reply(request, update, resolved.message)
    if ai_dry_run:
        return _reply(
            request,
            update,
            checkin_service.format_ai_dry_run_success_message(
                english_name=registration.english_name or "",
                employee_id=registration.employee_id,
                clock_time_utc=resolved.clock_time_utc,
                matter=matter,
                used_ai_time=resolved.used_ai_time,
                verified_image_user=resolved.verified_image_user,
                image_display_name=(
                    resolved.extraction.display_name
                    if resolved.extraction is not None
                    else None
                ),
                timezone_name="Asia/Shanghai",
            ),
        )

    inserted = clock_records_repo.insert_gateway_clock_record_cur(
        cursor,
        source_chat_id=message.chat.id,
        source_message_id=message.message_id,
        file_ref=attachment.fileRef,
        tg_id=sender.id,
        employee_id=registration.employee_id,
        shift_id=None,
        clock_time_utc=resolved.clock_time_utc,
        clock_action=matter,
    )
    if not inserted:
        return _reply(request, update, "该打卡消息已处理，本次未重复记账。")
    if is_test_group_chat(chat_id=message.chat.id, chat_title=message.chat.title):
        text = checkin_service.format_test_group_success_message(
            english_name=registration.english_name or "",
            clock_time_utc=resolved.clock_time_utc,
            matter=matter,
            timezone_name="Asia/Shanghai",
        )
    else:
        text = f"{matter}成功"
    return _reply(request, update, text)


def is_group_checkin(
    update: TelegramMessageUpdate | TelegramEditedMessageUpdate,
) -> bool:
    message = _checkin_message(update)
    return (
        message.chat.type in {"group", "supergroup"}
        and (message.photo is not None or message.document is not None)
    )


def _employee_in_roster(
    cursor: Cursor,
    *,
    year_month: str,
    roster_source: str | None,
    employee_id: str,
) -> bool:
    if roster_source is None:
        return False
    cursor.execute(
        """
        SELECT 1
        FROM public.employee_shift_roster
        WHERE year_month = %s
          AND source = %s
          AND employee_id = %s
        """,
        (year_month, roster_source, employee_id),
    )
    return cursor.fetchone() is not None


def _caption_error(
    *,
    caption: str | None,
    english_name: str,
    employee_id: str,
    chat_id: int,
    chat_title: str | None,
) -> str | None:
    if requires_remote_diff_checkin(chat_id=chat_id, chat_title=chat_title) or (
        requires_employee_id_only_checkin(chat_id=chat_id, chat_title=chat_title)
    ):
        return validate_caption_for_remote_diff(
            caption=caption,
            employee_id=employee_id,
        )
    return validate_caption_identity_for_sender(
        caption=caption,
        english_name=english_name,
        employee_id=employee_id,
    )


def _resolve_checkin(
    *,
    image_bytes: bytes,
    tg_id: int,
    message_sent_utc: datetime,
    caption: str | None,
    chat_id: int,
    chat_title: str | None,
    registration: registrations_repo.RegistrationRow,
) -> ServiceResult | checkin_ai_orchestrator.CheckinAiResolveResult:
    config = load_checkin_ai_config()
    if not config.enabled:
        return checkin_ai_orchestrator.CheckinAiResolveResult(
            clock_time_utc=message_sent_utc,
            used_ai_time=False,
            verified_image_user=False,
            extraction=None,
        )
    return asyncio.run(
        checkin_ai_orchestrator.resolve_clock_time_with_ai_from_bytes(
            image_bytes=image_bytes,
            tg_id=tg_id,
            shift_timezone="Asia/Shanghai",
            config=config,
            message_sent_utc=message_sent_utc,
            caption=caption,
            chat_id=chat_id,
            chat_title=chat_title,
            registration=registration,
        )
    )


def _reply(
    request: GatewayEventRequest,
    update: TelegramMessageUpdate | TelegramEditedMessageUpdate,
    text: str,
) -> GatewayEventResponse:
    message = _checkin_message(update)
    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=UnchangedSessionDirective(directive="UNCHANGED"),
        actions=[
            SendMessageAction(
                actionId=f"{request.eventId}.reply",
                type="SEND_MESSAGE",
                chatId=message.chat.id,
                replyToMessageId=message.message_id,
                text=text,
            )
        ],
    )


def _checkin_message(
    update: TelegramMessageUpdate | TelegramEditedMessageUpdate,
) -> TelegramMessage:
    if isinstance(update, TelegramMessageUpdate):
        return update.message
    return update.edited_message
