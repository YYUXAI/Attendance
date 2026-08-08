from __future__ import annotations

import hashlib
import json

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
from gateway_provider.profile_module import profile_text_for_tg_id
from domain.action_drafts import build_checkin_draft
from repositories import registrations_repo
from services import register_service
from services.register_service import RegisterPreview


class GatewayEventIdConflictError(RuntimeError):
    def __init__(self, event_id: str) -> None:
        super().__init__("Gateway event ID conflicts with a different request")
        self.event_id = event_id


class GatewayRouteOwnershipMismatchError(RuntimeError):
    pass


class AttendanceGatewayEventModule:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

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

                response = _process_attendance_event(request, cursor)
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
        group_action = {
            "/att_signin": "签到",
            "/att_signout": "签退",
        }.get(_command_name(message.text) or "")
        if group_action is not None:
            return _show_group_message_action(
                request,
                cursor,
                update,
                label=group_action,
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


def _command_name(text: str | None) -> str | None:
    if text is None:
        return None
    first_token = text.strip().split(maxsplit=1)[0]
    return first_token.split("@", maxsplit=1)[0].lower()
