from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extensions import cursor as Cursor
from psycopg2.extras import Json

from gateway_provider.contracts import (
    AcquireSessionDirective,
    AnswerCallbackAction,
    AnswerInlineQueryAction,
    GatewayEventRequest,
    GatewayEventResponse,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReleaseSessionDirective,
    SendMessageAction,
    TelegramCallbackUpdate,
    TelegramInlineQueryUpdate,
    TelegramMessageUpdate,
    UnchangedSessionDirective,
    event_request_canonical_value,
    event_response_value,
)
from gateway_provider.checkin_module import is_group_checkin, process_group_checkin
from gateway_provider.gateway_file_client import GatewayFileReader
from gateway_provider.profile_module import profile_text_for_tg_id
from domain.action_drafts import (
    build_back_draft,
    build_checkin_draft,
    build_leave_draft,
    report_reason,
)
from repositories import registrations_repo, temporary_leave_records_repo
from services import register_service
from services.leave_flow_guard import (
    LEAVE_BACK_OVERTIME_MINUTES,
    format_leave_duration_minutes,
    requires_leave_mutual_exclusion,
)
from services.register_service import RegisterPreview


class GatewayEventIdConflictError(RuntimeError):
    def __init__(self, event_id: str) -> None:
        super().__init__("Gateway event ID conflicts with a different request")
        self.event_id = event_id


class GatewayRouteOwnershipMismatchError(RuntimeError):
    pass


class AttendanceGatewayEventModule:
    def __init__(self, database_url: str, file_reader: GatewayFileReader) -> None:
        self._database_url = database_url
        self._file_reader = file_reader

    def process_event(self, request: GatewayEventRequest) -> GatewayEventResponse:
        request_hash = _request_hash(request)
        with psycopg2.connect(self._database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (request.eventId,),
                )
                cursor.execute(
                    """
                    SELECT request_hash, response_json
                    FROM gateway_processed_events
                    WHERE event_id = %s
                    """,
                    (request.eventId,),
                )
                existing = cursor.fetchone()
                if existing is not None:
                    stored_hash, stored_response = existing
                    if stored_hash != request_hash:
                        raise GatewayEventIdConflictError(request.eventId)
                    return GatewayEventResponse.model_validate(
                        {**stored_response, "result": "DUPLICATE"},
                        strict=True,
                    )

                response = _process_attendance_event(
                    request,
                    cursor,
                    self._file_reader,
                )
                response_value = event_response_value(response)
                cursor.execute(
                    """
                    INSERT INTO gateway_processed_events (
                        event_id,
                        request_hash,
                        response_json,
                        processed_at
                    )
                    VALUES (%s, %s, %s, clock_timestamp())
                    """,
                    (request.eventId, request_hash, Json(response_value)),
                )
                return response


def _request_hash(request: GatewayEventRequest) -> str:
    canonical = json.dumps(
        event_request_canonical_value(request),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _process_attendance_event(
    request: GatewayEventRequest,
    cursor: Cursor,
    file_reader: GatewayFileReader,
) -> GatewayEventResponse:
    update = request.telegramUpdate
    if isinstance(update, TelegramInlineQueryUpdate):
        if request.routeReason != "INLINE_QUERY":
            raise GatewayRouteOwnershipMismatchError()
        return _answer_inline_query(request, update)
    if isinstance(update, TelegramCallbackUpdate):
        callback_data = update.callback_query.data
        if callback_data == "att:register":
            return _begin_registration(request, cursor, update)
        if callback_data == "att:profile":
            return _show_profile(request, cursor, update)
        if callback_data in {"att:signin", "att:signout"}:
            return _show_group_action(request, cursor, update)
        if callback_data in {"att:leave", "att:back"}:
            return _show_leave_back_action(request, cursor, update)
        for operation in ("confirm", "cancel"):
            prefix = f"att:register:{operation}:"
            if callback_data.startswith(prefix):
                token = callback_data.removeprefix(prefix)
                if not token:
                    raise GatewayRouteOwnershipMismatchError()
                return _finish_registration(
                    request,
                    cursor,
                    update,
                    operation=operation,
                    token=token,
                )
        raise GatewayRouteOwnershipMismatchError()

    if not isinstance(update, TelegramMessageUpdate):
        raise GatewayRouteOwnershipMismatchError()
    message = update.message
    if request.routeReason == "CONVERSATION_SESSION":
        return _process_registration_text(request, cursor, update)
    if (
        request.routeReason == "GROUP_OWNER"
        and message.chat.type in {"group", "supergroup"}
    ):
        if is_group_checkin(update):
            return process_group_checkin(request, cursor, update, file_reader)
        group_action = {
            "/att_signin": ("signin", "签到"),
            "/att_signout": ("signout", "签退"),
            "/att_leave": ("leave", "离岗"),
            "/att_back": ("back", "返岗"),
        }.get(_command_name(message.text) or "")
        if group_action is not None and group_action[0] in {"signin", "signout"}:
            return _show_group_message_action(
                request,
                cursor,
                update,
                label=group_action[1],
            )
        if group_action is not None:
            return _show_leave_back_message_action(
                request,
                cursor,
                update,
                operation=group_action[0],
            )
        if message.text is not None and "#离岗报备" in message.text:
            return _process_group_leave_report(
                request,
                cursor,
                update,
                operation="leave",
            )
        if message.text is not None and "#返岗报备" in message.text:
            return _process_group_leave_report(
                request,
                cursor,
                update,
                operation="back",
            )
        raise GatewayRouteOwnershipMismatchError()
    if (
        request.routeReason != "COMMAND"
        or message.chat.type != "private"
        or _command_name(message.text) != "/attendance"
    ):
        raise GatewayRouteOwnershipMismatchError()

    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=UnchangedSessionDirective(directive="UNCHANGED"),
        actions=[
            SendMessageAction(
                actionId=f"{request.eventId}.menu",
                type="SEND_MESSAGE",
                chatId=message.chat.id,
                replyToMessageId=message.message_id,
                text="考勤功能",
                replyMarkup=InlineKeyboardMarkup(
                    inlineKeyboard=[
                        [
                            InlineKeyboardButton(
                                text="注册",
                                callbackData="att:register",
                            ),
                            InlineKeyboardButton(
                                text="个人",
                                callbackData="att:profile",
                            ),
                        ]
                    ]
                ),
            )
        ],
    )


def _process_registration_text(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramMessageUpdate,
) -> GatewayEventResponse:
    message = update.message
    sender = message.sender
    if message.chat.type != "private" or sender is None or message.text is None:
        raise GatewayRouteOwnershipMismatchError()
    if not register_service.is_waiting_register_input(
        cursor,
        tg_id=sender.id,
        private_chat_id=message.chat.id,
    ):
        return _single_message_response(
            request,
            message.chat.id,
            message.message_id,
            "注册会话已超时，请重新点击【注册】。",
            ReleaseSessionDirective(directive="RELEASE"),
        )

    preview = register_service.preview_register(
        cursor,
        tg_id=sender.id,
        private_chat_id=message.chat.id,
        text=message.text,
    )
    if not isinstance(preview, RegisterPreview):
        return _single_message_response(
            request,
            message.chat.id,
            message.message_id,
            preview.message,
            AcquireSessionDirective(directive="ACQUIRE", ttlSeconds=900),
        )
    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=AcquireSessionDirective(directive="ACQUIRE", ttlSeconds=900),
        actions=[
            SendMessageAction(
                actionId=f"{request.eventId}.reply",
                type="SEND_MESSAGE",
                chatId=message.chat.id,
                replyToMessageId=message.message_id,
                text=(
                    "请确认：\n\n"
                    f"英文名：{preview.english_name}\n"
                    f"工号：{preview.employee_id}\n"
                ),
                replyMarkup=InlineKeyboardMarkup(
                    inlineKeyboard=[
                        [
                            InlineKeyboardButton(
                                text="确认",
                                callbackData=(
                                    f"att:register:confirm:{preview.token}"
                                ),
                            ),
                            InlineKeyboardButton(
                                text="取消",
                                callbackData=(
                                    f"att:register:cancel:{preview.token}"
                                ),
                            ),
                        ]
                    ]
                ),
            )
        ],
    )


def _single_message_response(
    request: GatewayEventRequest,
    chat_id: int,
    reply_to_message_id: int,
    text: str,
    session: AcquireSessionDirective | ReleaseSessionDirective,
) -> GatewayEventResponse:
    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=session,
        actions=[
            SendMessageAction(
                actionId=f"{request.eventId}.reply",
                type="SEND_MESSAGE",
                chatId=chat_id,
                replyToMessageId=reply_to_message_id,
                text=text,
            )
        ],
    )


def _begin_registration(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramCallbackUpdate,
) -> GatewayEventResponse:
    callback = update.callback_query
    message = callback.message
    if message.chat.type != "private":
        raise GatewayRouteOwnershipMismatchError()
    tg_id = callback.sender.id
    if registrations_repo.get_by_tg_id_cur(cursor, tg_id=tg_id) is not None:
        register_service.clear_waiting_register_input(cursor, tg_id=tg_id)
        session = ReleaseSessionDirective(directive="RELEASE")
        text = "您已经注册过了"
    else:
        register_service.mark_waiting_register_input(
            cursor,
            tg_id=tg_id,
            private_chat_id=message.chat.id,
        )
        session = AcquireSessionDirective(directive="ACQUIRE", ttlSeconds=900)
        text = (
            "请私聊发送一行（不要复制「请输入」「示例」等提示）：\n"
            "英文名$工号\n"
            "例如：GRANDFOR$74808"
        )
    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=session,
        actions=[
            AnswerCallbackAction(
                actionId=f"{request.eventId}.callback",
                type="ANSWER_CALLBACK",
                callbackQueryId=callback.id,
            ),
            SendMessageAction(
                actionId=f"{request.eventId}.reply",
                type="SEND_MESSAGE",
                chatId=message.chat.id,
                replyToMessageId=message.message_id,
                text=text,
            ),
        ],
    )


def _finish_registration(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramCallbackUpdate,
    *,
    operation: str,
    token: str,
) -> GatewayEventResponse:
    callback = update.callback_query
    message = callback.message
    if message.chat.type != "private":
        raise GatewayRouteOwnershipMismatchError()

    if operation == "confirm":
        result = register_service.confirm_register(
            cursor,
            token=token,
            tg_id=callback.sender.id,
            registered_chat_id=message.chat.id,
            tg_username=callback.sender.username,
        )
    elif operation == "cancel":
        result = register_service.cancel_preview(
            cursor,
            token=token,
            tg_id=callback.sender.id,
            private_chat_id=message.chat.id,
        )
    else:
        raise GatewayRouteOwnershipMismatchError()

    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=ReleaseSessionDirective(directive="RELEASE"),
        actions=[
            AnswerCallbackAction(
                actionId=f"{request.eventId}.callback",
                type="ANSWER_CALLBACK",
                callbackQueryId=callback.id,
            ),
            SendMessageAction(
                actionId=f"{request.eventId}.reply",
                type="SEND_MESSAGE",
                chatId=message.chat.id,
                replyToMessageId=message.message_id,
                text=result.message,
            ),
        ],
    )


def _show_profile(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramCallbackUpdate,
) -> GatewayEventResponse:
    callback = update.callback_query
    message = callback.message
    if message.chat.type != "private":
        raise GatewayRouteOwnershipMismatchError()
    register_service.clear_waiting_register_input(
        cursor,
        tg_id=callback.sender.id,
    )
    text = profile_text_for_tg_id(cursor, tg_id=callback.sender.id)
    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=ReleaseSessionDirective(directive="RELEASE"),
        actions=[
            AnswerCallbackAction(
                actionId=f"{request.eventId}.callback",
                type="ANSWER_CALLBACK",
                callbackQueryId=callback.id,
            ),
            SendMessageAction(
                actionId=f"{request.eventId}.reply",
                type="SEND_MESSAGE",
                chatId=message.chat.id,
                replyToMessageId=message.message_id,
                text=text,
            ),
        ],
    )


def _show_group_action(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramCallbackUpdate,
) -> GatewayEventResponse:
    callback = update.callback_query
    message = callback.message
    if message.chat.type not in {"group", "supergroup"}:
        raise GatewayRouteOwnershipMismatchError()
    label = {
        "att:signin": "签到",
        "att:signout": "签退",
    }.get(callback.data)
    if label is None:
        raise GatewayRouteOwnershipMismatchError()
    text, reply_markup = _group_action_content(
        cursor,
        tg_id=callback.sender.id,
        label=label,
    )
    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=UnchangedSessionDirective(directive="UNCHANGED"),
        actions=[
            AnswerCallbackAction(
                actionId=f"{request.eventId}.callback",
                type="ANSWER_CALLBACK",
                callbackQueryId=callback.id,
            ),
            SendMessageAction(
                actionId=f"{request.eventId}.reply",
                type="SEND_MESSAGE",
                chatId=message.chat.id,
                replyToMessageId=message.message_id,
                text=text,
                replyMarkup=reply_markup,
            ),
        ],
    )


def _show_group_message_action(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramMessageUpdate,
    *,
    label: str,
) -> GatewayEventResponse:
    message = update.message
    sender = message.sender
    if sender is None:
        raise GatewayRouteOwnershipMismatchError()
    text, reply_markup = _group_action_content(
        cursor,
        tg_id=sender.id,
        label=label,
    )
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
                replyMarkup=reply_markup,
            )
        ],
    )


def _show_leave_back_action(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramCallbackUpdate,
) -> GatewayEventResponse:
    callback = update.callback_query
    message = callback.message
    if message.chat.type not in {"group", "supergroup"}:
        raise GatewayRouteOwnershipMismatchError()
    operation = callback.data.removeprefix("att:")
    if operation not in {"leave", "back"}:
        raise GatewayRouteOwnershipMismatchError()
    text, reply_markup = _leave_back_content(
        cursor,
        tg_id=callback.sender.id,
        chat_id=message.chat.id,
        operation=operation,
        now_utc=_received_at_utc(request.receivedAt),
    )
    return _callback_message_response(
        request,
        callback_id=callback.id,
        chat_id=message.chat.id,
        reply_to_message_id=message.message_id,
        text=text,
        reply_markup=reply_markup,
    )


def _show_leave_back_message_action(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramMessageUpdate,
    *,
    operation: str,
) -> GatewayEventResponse:
    message = update.message
    sender = message.sender
    if sender is None:
        raise GatewayRouteOwnershipMismatchError()
    text, reply_markup = _leave_back_content(
        cursor,
        tg_id=sender.id,
        chat_id=message.chat.id,
        operation=operation,
        now_utc=_received_at_utc(request.receivedAt),
    )
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
                replyMarkup=reply_markup,
            )
        ],
    )


def _leave_back_content(
    cursor: Cursor,
    *,
    tg_id: int,
    chat_id: int,
    operation: str,
    now_utc: datetime,
) -> tuple[str, InlineKeyboardMarkup | None]:
    registration = registrations_repo.get_by_tg_id_cur(cursor, tg_id=tg_id)
    if registration is None:
        return "请先私聊机器人完成注册（英文名$工号）。", None
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"leave:{registration.employee_id}:{chat_id}",),
    )
    open_record = temporary_leave_records_repo.get_latest_open_cur(
        cursor,
        employee_id=registration.employee_id,
        chat_id=chat_id,
    )
    mutual_exclusion = requires_leave_mutual_exclusion(chat_id=chat_id)
    if operation == "leave" and mutual_exclusion and open_record is not None:
        return "您已离岗", None
    if operation == "back" and mutual_exclusion and open_record is None:
        return "您还未点击离岗", None
    now_local = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
    name = registration.english_name or ""
    if operation == "leave":
        label = "离岗"
        draft = build_leave_draft(
            english_name=name,
            employee_id=registration.employee_id,
            now_local=now_local,
        )
    else:
        label = "返岗"
        duration = None
        overtime = False
        if open_record is not None and isinstance(open_record.leave_at, datetime):
            minutes = max(
                0,
                int((now_utc - _as_utc(open_record.leave_at)).total_seconds() // 60),
            )
            duration = format_leave_duration_minutes(minutes)
            overtime = minutes >= LEAVE_BACK_OVERTIME_MINUTES
        draft = build_back_draft(
            english_name=name,
            employee_id=registration.employee_id,
            leave_duration=duration,
            leave_overtime=overtime,
            now_local=now_local,
        )
    return (
        f"请点击下方按钮填入{label}模板。",
        InlineKeyboardMarkup(
            inlineKeyboard=[
                [
                    InlineKeyboardButton(
                        text=label,
                        switchInlineQueryCurrentChat=draft,
                    )
                ]
            ]
        ),
    )


def _callback_message_response(
    request: GatewayEventRequest,
    *,
    callback_id: str,
    chat_id: int,
    reply_to_message_id: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> GatewayEventResponse:
    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=UnchangedSessionDirective(directive="UNCHANGED"),
        actions=[
            AnswerCallbackAction(
                actionId=f"{request.eventId}.callback",
                type="ANSWER_CALLBACK",
                callbackQueryId=callback_id,
            ),
            SendMessageAction(
                actionId=f"{request.eventId}.reply",
                type="SEND_MESSAGE",
                chatId=chat_id,
                replyToMessageId=reply_to_message_id,
                text=text,
                replyMarkup=reply_markup,
            ),
        ],
    )


def _group_action_content(
    cursor: Cursor,
    *,
    tg_id: int,
    label: str,
) -> tuple[str, InlineKeyboardMarkup | None]:
    registration = registrations_repo.get_by_tg_id_cur(cursor, tg_id=tg_id)
    if registration is None:
        return "请先私聊机器人完成注册（英文名$工号）。", None
    draft = build_checkin_draft(
        english_name=registration.english_name or "",
        employee_id=registration.employee_id,
        action=label,
    )
    return (
        f"请点击下方按钮填入{label}模板。",
        InlineKeyboardMarkup(
            inlineKeyboard=[
                [
                    InlineKeyboardButton(
                        text=label,
                        switchInlineQueryCurrentChat=draft,
                    )
                ]
            ]
        ),
    )


def _answer_inline_query(
    request: GatewayEventRequest,
    update: TelegramInlineQueryUpdate,
) -> GatewayEventResponse:
    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=UnchangedSessionDirective(directive="UNCHANGED"),
        actions=[
            AnswerInlineQueryAction(
                actionId=f"{request.eventId}.answer",
                type="ANSWER_INLINE_QUERY",
                inlineQueryId=update.inline_query.id,
                results=[],
                cacheTimeSeconds=0,
                isPersonal=True,
            )
        ],
    )


def _process_group_leave_report(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramMessageUpdate,
    *,
    operation: str,
) -> GatewayEventResponse:
    message = update.message
    sender = message.sender
    if sender is None:
        raise GatewayRouteOwnershipMismatchError()
    registration = registrations_repo.get_by_tg_id_cur(cursor, tg_id=sender.id)
    if registration is None:
        return _group_report_message(
            request,
            chat_id=message.chat.id,
            reply_to_message_id=message.message_id,
            text="请先私聊机器人完成注册（英文名$工号）。",
        )

    employee_id = registration.employee_id
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"leave:{employee_id}:{message.chat.id}",),
    )
    occurred_at = _received_at_utc(request.receivedAt)
    open_record = temporary_leave_records_repo.get_latest_open_cur(
        cursor,
        employee_id=employee_id,
        chat_id=message.chat.id,
        for_update=True,
    )
    mutual_exclusion = requires_leave_mutual_exclusion(chat_id=message.chat.id)
    if operation == "leave":
        if mutual_exclusion and open_record is not None:
            return _group_report_message(
                request,
                chat_id=message.chat.id,
                reply_to_message_id=message.message_id,
                text="您已离岗",
            )
        temporary_leave_records_repo.insert_leave_cur(
            cursor,
            employee_id=employee_id,
            english_name=(registration.english_name or "").strip() or "未命名",
            tg_id=sender.id,
            chat_id=message.chat.id,
            leave_at_utc=occurred_at,
            reason=report_reason(message.text),
        )
        return _group_report_without_actions(request)
    if operation != "back":
        raise GatewayRouteOwnershipMismatchError()
    if open_record is None:
        return _group_report_message(
            request,
            chat_id=message.chat.id,
            reply_to_message_id=message.message_id,
            text="您还未点击离岗",
        )
    leave_at = open_record.leave_at
    if not isinstance(leave_at, datetime):
        raise RuntimeError("temporary leave record has invalid leave_at")
    leave_at_utc = _as_utc(leave_at)
    duration_minutes = max(
        0,
        int((occurred_at - leave_at_utc).total_seconds() // 60),
    )
    if not temporary_leave_records_repo.close_leave_cur(
        cursor,
        record_id=open_record.id,
        back_at_utc=occurred_at,
        duration_minutes=duration_minutes,
        remark_required=duration_minutes > 30,
    ):
        raise RuntimeError("temporary leave record close lost ownership")
    return _group_report_without_actions(request)


def _group_report_without_actions(
    request: GatewayEventRequest,
) -> GatewayEventResponse:
    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=UnchangedSessionDirective(directive="UNCHANGED"),
        actions=[],
    )


def _group_report_message(
    request: GatewayEventRequest,
    *,
    chat_id: int,
    reply_to_message_id: int,
    text: str,
) -> GatewayEventResponse:
    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=UnchangedSessionDirective(directive="UNCHANGED"),
        actions=[
            SendMessageAction(
                actionId=f"{request.eventId}.reply",
                type="SEND_MESSAGE",
                chatId=chat_id,
                replyToMessageId=reply_to_message_id,
                text=text,
            )
        ],
    )


def _received_at_utc(value: str) -> datetime:
    return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _command_name(text: str | None) -> str | None:
    if text is None:
        return None
    first_token = text.strip().split(maxsplit=1)[0]
    return first_token.split("@", maxsplit=1)[0].lower()
