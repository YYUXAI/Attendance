from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extensions import cursor as Cursor
from psycopg2.extras import Json

from gateway_provider.contracts import (
    AcquireSessionDirective,
    AnswerCallbackAction,
    AnswerInlineQueryAction,
    AttendanceRegistrationCompletion,
    GatewayEventRequest,
    GatewayEventResponse,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemoveMarkup,
    ReleaseSessionDirective,
    SendMessageAction,
    TelegramCallbackUpdate,
    TelegramEditedMessageUpdate,
    TelegramInlineQueryUpdate,
    TelegramMessageUpdate,
    UnchangedSessionDirective,
    event_request_canonical_value,
    event_response_value,
)
from gateway_provider.checkin_module import is_group_checkin, process_group_checkin
from gateway_provider.admin_module import (
    is_admin_test_message,
    process_admin_test_message,
)
from infra.leave_return_keyboard_only_config import (
    is_leave_return_keyboard_only_chat,
    is_username_identity_chat,
    leave_overtime_minutes_for_chat,
    normalize_tg_username,
)
from gateway_provider.admin_export_module import (
    has_active_admin_export_session,
    is_admin_export_callback,
    is_admin_export_test_message,
    process_admin_export_callback,
    process_admin_export_entry,
    process_admin_export_text,
)
from gateway_provider.gateway_file_client import GatewayFileReader
from gateway_provider.export_module import (
    ensure_admin_identity,
    is_admin,
    is_export_callback,
    is_leave_export_scope,
    process_export_callback,
    process_export_message,
    resolve_admin_export_chat_id,
)
from gateway_provider.profile_module import profile_text_for_tg_id
from infra.checkin_remote_diff_config import requires_remote_diff_checkin
from infra.attendance_group_policy import load_group_policies
from infra.db import database_url_scope
from domain.action_drafts import (
    build_back_draft,
    build_checkin_draft,
    build_leave_draft,
    report_reason,
)
from repositories import (
    attendance_runtime_config_repo,
    registrations_repo,
    temporary_leave_records_repo,
)
from services import register_service
from services.leave_flow_guard import (
    format_leave_duration_minutes,
    requires_leave_back_copy_fallback,
    requires_leave_mutual_exclusion,
)
from services.register_service import RegisterPreview


_GROUP_INLINE_HINT = "请点击下方按钮操作"
_GROUP_INLINE_HINT_REMOTE = (
    "请点击 ↗ 填入模板；发截图时请「回复本条消息」发送（群隐私模式下否则 Bot 收不到）。"
    "若无法 ↗，请点「复制」后粘贴并回复本条发送。"
)


class GatewayEventIdConflictError(RuntimeError):
    def __init__(self, event_id: str) -> None:
        super().__init__("Gateway event ID conflicts with a different request")
        self.event_id = event_id


class GatewayRouteOwnershipMismatchError(RuntimeError):
    pass


class GatewayEventBusyError(RuntimeError):
    def __init__(self, event_id: str) -> None:
        super().__init__("Gateway event is busy")
        self.event_id = event_id


class AttendanceGatewayEventModule:
    def __init__(
        self,
        database_url: str,
        file_reader: GatewayFileReader,
        *,
        shift_web_app_public_url: str,
    ) -> None:
        self._database_url = database_url
        self._file_reader = file_reader
        self._shift_web_app_public_url = shift_web_app_public_url

    def process_event(self, request: GatewayEventRequest) -> GatewayEventResponse:
        request_hash = _request_hash(request)
        with database_url_scope(self._database_url):
            with psycopg2.connect(self._database_url) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_try_advisory_xact_lock(hashtextextended(%s, 0))",
                        (request.eventId,),
                    )
                    locked = cursor.fetchone()
                    if locked != (True,):
                        raise GatewayEventBusyError(request.eventId)
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
                        shift_web_app_public_url=self._shift_web_app_public_url,
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
    *,
    shift_web_app_public_url: str,
) -> GatewayEventResponse:
    if request.routeReason == "GROUP_OWNER" and (
        request.groupRouteRef is None
        or request.groupClassification != "ATTENDANCE"
    ):
        raise GatewayRouteOwnershipMismatchError()
    update = request.telegramUpdate
    if request.routeReason == "GROUP_OWNER":
        chat = _group_event_chat(update)
        if chat is None or request.groupRouteRef is None:
            raise GatewayRouteOwnershipMismatchError()
        fingerprint = (os.environ.get("ATTENDANCE_GROUPS_FINGERPRINT") or "").strip()
        if len(fingerprint) != 64:
            raise RuntimeError("ATTENDANCE_GROUPS_FINGERPRINT is required")
        attendance_runtime_config_repo.bind_observed_group_cur(
            cursor,
            chat_id=chat.id,
            route_ref=request.groupRouteRef,
            title=chat.title,
            policies=load_group_policies(os.environ),
            config_fingerprint=fingerprint,
        )
    if isinstance(update, TelegramInlineQueryUpdate):
        if request.routeReason != "INLINE_QUERY":
            raise GatewayRouteOwnershipMismatchError()
        return _answer_inline_query(request, update)
    if isinstance(update, TelegramCallbackUpdate):
        callback_data = update.callback_query.data
        if is_admin_export_callback(callback_data):
            return process_admin_export_callback(request, cursor, update)
        if is_export_callback(callback_data):
            return process_export_callback(request, cursor, update)
        if callback_data == "att:menu":
            ensure_admin_identity(
                cursor,
                tg_id=update.callback_query.sender.id,
                tg_username=update.callback_query.sender.username,
            )
            return _private_menu_response(
                request,
                cursor,
                chat_id=update.callback_query.message.chat.id,
                reply_to_message_id=update.callback_query.message.message_id,
                actor_id=update.callback_query.sender.id,
                callback_id=update.callback_query.id,
                shift_web_app_url=_shift_web_app_url(
                    request,
                    shift_web_app_public_url,
                ),
            )
        if callback_data == "att:shift":
            return _show_shift_callback(
                request,
                cursor,
                update,
                shift_web_app_url=_shift_web_app_url(
                    request,
                    shift_web_app_public_url,
                ),
            )
        if callback_data == "att:register":
            return _begin_registration(request, cursor, update)
        if callback_data == "att:profile":
            return _show_profile(request, cursor, update)
        if callback_data in {"att:signin", "att:signout"}:
            return _show_group_action(request, cursor, update)
        if callback_data in {"att:leave", "att:back"}:
            return _show_leave_back_action(request, cursor, update)
        if callback_data == "att:switch_group":
            return _switch_attendance_group(request, cursor, update)
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

    if isinstance(update, TelegramEditedMessageUpdate):
        if request.routeReason == "GROUP_OWNER":
            if is_group_checkin(update):
                return process_group_checkin(request, cursor, update, file_reader)
            if update.edited_message.chat.type in {"group", "supergroup"}:
                return _ignored_event_response(request)
        raise GatewayRouteOwnershipMismatchError()
    if not isinstance(update, TelegramMessageUpdate):
        raise GatewayRouteOwnershipMismatchError()
    message = update.message
    if is_admin_test_message(message):
        return process_admin_test_message(request, cursor, update)
    if is_admin_export_test_message(message):
        return process_admin_export_entry(request, cursor, update)
    if request.routeReason == "CONVERSATION_SESSION":
        if (
            message.sender is not None
            and message.chat.type == "private"
            and has_active_admin_export_session(
                cursor,
                tg_id=message.sender.id,
                private_chat_id=message.chat.id,
            )
        ):
            return process_admin_export_text(request, cursor, update)
        return _process_registration_text(
            request,
            cursor,
            update,
            shift_web_app_public_url=shift_web_app_public_url,
        )
    if (
        request.routeReason == "GROUP_OWNER"
        and message.chat.type in {"group", "supergroup"}
    ):
        if is_group_checkin(update):
            return process_group_checkin(request, cursor, update, file_reader)
        if _command_name(message.text) == "/start":
            return _group_menu_response(request, update)
        message_text = (message.text or "").strip()
        if message_text == "导出":
            return process_export_message(request, cursor, update)
        group_action = {
            "/signin": ("signin", "签到"),
            "/signout": ("signout", "签退"),
            "/leave": ("leave", "离岗"),
            "/back": ("back", "返岗"),
        }.get(_command_name(message.text) or "") or {
            "签到": ("signin", "签到"),
            "签退": ("signout", "签退"),
            "离岗": ("leave", "离岗"),
            "返岗": ("back", "返岗"),
        }.get(message_text)
        if group_action is not None and group_action[0] in {"signin", "signout"}:
            if is_leave_return_keyboard_only_chat(
                chat_id=message.chat.id,
                chat_title=message.chat.title,
            ):
                return _group_menu_response(request, update)
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
        return _ignored_event_response(request)
    if request.routeReason != "COMMAND" or message.chat.type != "private":
        raise GatewayRouteOwnershipMismatchError()

    if _is_registration_begin_text(message.text):
        return _begin_registration_message(request, cursor, update)

    normalized_private = (message.text or "").strip()
    if normalized_private in {"我的考勤", "个人", "我的信息"}:
        return _show_profile_message(request, cursor, update)
    if normalized_private == "导出":
        return process_export_message(request, cursor, update)
    if normalized_private in {"班表", "班次"}:
        return _show_shift_message(
            request,
            cursor,
            update,
            shift_web_app_url=_shift_web_app_url(
                request,
                shift_web_app_public_url,
            ),
        )

    if (
        _command_name(message.text) != "/attendance"
        and normalized_private not in {"⌨️ 考勤菜单", "考勤菜单"}
    ):
        raise GatewayRouteOwnershipMismatchError()

    if message.sender is not None:
        ensure_admin_identity(
            cursor,
            tg_id=message.sender.id,
            tg_username=message.sender.username,
        )
    return _private_menu_response(
        request,
        cursor,
        chat_id=message.chat.id,
        reply_to_message_id=message.message_id,
        actor_id=message.sender.id if message.sender is not None else message.chat.id,
        shift_web_app_url=_shift_web_app_url(
            request,
            shift_web_app_public_url,
        ),
    )


def _private_menu_response(
    request: GatewayEventRequest,
    cursor: Cursor,
    *,
    chat_id: int,
    reply_to_message_id: int,
    actor_id: int,
    shift_web_app_url: str | None,
    callback_id: str | None = None,
) -> GatewayEventResponse:
    register_service.clear_waiting_register_input(cursor, tg_id=actor_id)
    # 预登记仅有 @用户名时，私聊首次点菜单补绑 tg_id（管理员导出依赖）
    # username 由调用方在有 sender 时先 bind；此处仅按 tg_id 判管理员
    menu_rows = [
        [InlineKeyboardButton(text="我的考勤", callbackData="att:profile")],
    ]
    # 非管理员只展示「我的考勤」；导出 / 班表仅管理员可见
    if is_admin(cursor, tg_id=actor_id):
        export_chat_id = resolve_admin_export_chat_id(cursor, tg_id=actor_id)
        leave_export_only = is_leave_export_scope(chat_id=export_chat_id)
        menu_rows.append(
            [InlineKeyboardButton(text="导出", callbackData="att:export")]
        )
        if not leave_export_only:
            shift_button = (
                InlineKeyboardButton(text="班表", webAppUrl=shift_web_app_url)
                if shift_web_app_url is not None
                else InlineKeyboardButton(text="班表", callbackData="att:shift")
            )
            menu_rows.append([shift_button])
    callback_actions = [] if callback_id is None else [
        AnswerCallbackAction(
            actionId=f"{request.eventId}.callback",
            type="ANSWER_CALLBACK",
            callbackQueryId=callback_id,
        )
    ]
    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=ReleaseSessionDirective(directive="RELEASE"),
        actions=[
            *callback_actions,
            SendMessageAction(
                actionId=f"{request.eventId}.menu",
                type="SEND_MESSAGE",
                chatId=chat_id,
                replyToMessageId=reply_to_message_id,
                text="请选择功能：",
                replyMarkup=InlineKeyboardMarkup(inlineKeyboard=menu_rows),
            ),
        ],
    )


def _ignored_event_response(request: GatewayEventRequest) -> GatewayEventResponse:
    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=UnchangedSessionDirective(directive="UNCHANGED"),
        actions=[],
    )


def _shift_web_app_url(
    request: GatewayEventRequest,
    public_base_url: str,
) -> str | None:
    if not public_base_url:
        return None
    year_month = _received_at_utc(request.receivedAt).astimezone(
        ZoneInfo("Asia/Shanghai")
    ).strftime("%Y-%m")
    return (
        f"{public_base_url}/shift-app/index.html"
        f"?year_month={year_month}"
    )


def _group_reply_keyboard(
    *,
    chat_id: int | None,
    chat_title: str | None,
) -> ReplyKeyboardMarkup:
    if is_leave_return_keyboard_only_chat(
        chat_id=chat_id,
        chat_title=chat_title,
    ):
        rows = [
            [
                ReplyKeyboardButton(text="离岗"),
                ReplyKeyboardButton(text="返岗"),
            ],
        ]
    else:
        rows = [
            [
                ReplyKeyboardButton(text="签到"),
                ReplyKeyboardButton(text="签退"),
            ],
            [
                ReplyKeyboardButton(text="离岗"),
                ReplyKeyboardButton(text="返岗"),
            ],
        ]
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resizeKeyboard=True,
        isPersistent=True,
        inputFieldPlaceholder="选下方按钮或输入消息",
    )


def _group_menu_response(
    request: GatewayEventRequest,
    update: TelegramMessageUpdate,
) -> GatewayEventResponse:
    message = update.message
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
                text="功能菜单（底部按钮或 /start）",
                replyMarkup=_group_reply_keyboard(
                    chat_id=message.chat.id,
                    chat_title=message.chat.title,
                ),
            )
        ],
    )


def _process_registration_text(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramMessageUpdate,
    *,
    shift_web_app_public_url: str,
) -> GatewayEventResponse:
    message = update.message
    sender = message.sender
    if message.chat.type != "private" or sender is None or message.text is None:
        raise GatewayRouteOwnershipMismatchError()
    normalized_text = message.text.strip()
    if normalized_text in {"我的考勤", "个人", "我的信息", "导出", "班表", "班次"}:
        register_service.clear_waiting_register_input(cursor, tg_id=sender.id)
        if normalized_text in {"我的考勤", "个人", "我的信息"}:
            return _show_profile_message(request, cursor, update)
        if normalized_text == "导出":
            return process_export_message(request, cursor, update)
        return _show_shift_message(
            request,
            cursor,
            update,
            shift_web_app_url=_shift_web_app_url(
                request,
                shift_web_app_public_url,
            ),
        )
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
        return _callback_message_response(
            request,
            callback_id=callback.id,
            chat_id=message.chat.id,
            reply_to_message_id=message.message_id,
            text="请先私聊机器人，再点击【注册】完成注册。",
        )
    session, text = _begin_registration_result(
        cursor,
        tg_id=callback.sender.id,
        private_chat_id=message.chat.id,
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


def _begin_registration_message(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramMessageUpdate,
) -> GatewayEventResponse:
    message = update.message
    sender = message.sender
    if message.chat.type != "private" or sender is None:
        raise GatewayRouteOwnershipMismatchError()
    session, text = _begin_registration_result(
        cursor,
        tg_id=sender.id,
        private_chat_id=message.chat.id,
    )
    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=session,
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


def _begin_registration_result(
    cursor: Cursor,
    *,
    tg_id: int,
    private_chat_id: int,
) -> tuple[AcquireSessionDirective | ReleaseSessionDirective, str]:
    if registrations_repo.get_by_tg_id_cur(cursor, tg_id=tg_id) is not None:
        register_service.clear_waiting_register_input(cursor, tg_id=tg_id)
        session = ReleaseSessionDirective(directive="RELEASE")
        text = "您已经注册过了"
    else:
        register_service.mark_waiting_register_input(
            cursor,
            tg_id=tg_id,
            private_chat_id=private_chat_id,
        )
        session = AcquireSessionDirective(directive="ACQUIRE", ttlSeconds=900)
        text = (
            "请私聊发送一行（不要复制「请输入」「示例」等提示）：\n"
            "英文名$工号\n"
            "例如：GRANDFOR$74808"
        )
    return session, text


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

    preview = register_service.get_preview(
        cursor,
        token=token,
        tg_id=callback.sender.id,
        private_chat_id=message.chat.id,
    ) if operation == "confirm" else None
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

    reply_action_id = f"{request.eventId}.reply"
    actions: list = [
        AnswerCallbackAction(
            actionId=f"{request.eventId}.callback",
            type="ANSWER_CALLBACK",
            callbackQueryId=callback.id,
        ),
        SendMessageAction(
            actionId=reply_action_id,
            type="SEND_MESSAGE",
            chatId=message.chat.id,
            replyToMessageId=message.message_id,
            text=result.message,
        ),
    ]
    # 注册成功后再挂底部考勤菜单（未绑定的 /start 不会提前挂）
    if operation == "confirm" and result.ok:
        actions.append(
            SendMessageAction(
                actionId=f"{request.eventId}.attendance-reply-keyboard",
                type="SEND_MESSAGE",
                chatId=message.chat.id,
                text="⌨️ 考勤菜单已就绪",
                replyMarkup=ReplyKeyboardMarkup(
                    keyboard=[[ReplyKeyboardButton(text="⌨️ 考勤菜单")]],
                    resizeKeyboard=True,
                    isPersistent=True,
                    inputFieldPlaceholder="点下方考勤菜单，或直接输入消息",
                ),
            )
        )
    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=ReleaseSessionDirective(directive="RELEASE"),
        actions=actions,
        attendanceRegistration=(
            AttendanceRegistrationCompletion(
                status="BOUND",
                businessUsername=preview.english_name,
                employeeId=preview.employee_id,
                replyActionId=reply_action_id,
            )
            if operation == "confirm" and result.ok and preview is not None
            else None
        ),
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
    text = profile_text_for_tg_id(
        cursor,
        tg_id=callback.sender.id,
        now_utc=_received_at_utc(request.receivedAt),
    )
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


def _show_profile_message(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramMessageUpdate,
) -> GatewayEventResponse:
    message = update.message
    sender = message.sender
    if message.chat.type != "private" or sender is None:
        raise GatewayRouteOwnershipMismatchError()
    return _single_message_response(
        request,
        message.chat.id,
        message.message_id,
        profile_text_for_tg_id(
            cursor,
            tg_id=sender.id,
            now_utc=_received_at_utc(request.receivedAt),
        ),
        ReleaseSessionDirective(directive="RELEASE"),
    )


def _show_shift_message(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramMessageUpdate,
    *,
    shift_web_app_url: str | None,
) -> GatewayEventResponse:
    message = update.message
    sender = message.sender
    if message.chat.type != "private" or sender is None:
        raise GatewayRouteOwnershipMismatchError()
    text, reply_markup = _shift_content(
        cursor,
        tg_id=sender.id,
        shift_web_app_url=shift_web_app_url,
    )
    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=ReleaseSessionDirective(directive="RELEASE"),
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


def _show_shift_callback(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramCallbackUpdate,
    *,
    shift_web_app_url: str | None,
) -> GatewayEventResponse:
    callback = update.callback_query
    message = callback.message
    if message.chat.type != "private":
        raise GatewayRouteOwnershipMismatchError()
    text, reply_markup = _shift_content(
        cursor,
        tg_id=callback.sender.id,
        shift_web_app_url=shift_web_app_url,
    )
    return _callback_message_response(
        request,
        callback_id=callback.id,
        chat_id=message.chat.id,
        reply_to_message_id=message.message_id,
        text=text,
        reply_markup=reply_markup,
    )


def _shift_content(
    cursor: Cursor,
    *,
    tg_id: int,
    shift_web_app_url: str | None,
) -> tuple[str, InlineKeyboardMarkup | None]:
    if not is_admin(cursor, tg_id=tg_id):
        return "无权限操作", None
    if shift_web_app_url is None:
        return (
            "班表 Web 未配置：请检查 active Attendance publicBaseUrl\n"
            "（须为 Telegram 可访问的 HTTPS 地址）",
            None,
        )
    return (
        "请点下方「打开班表配置」进入编辑页：",
        InlineKeyboardMarkup(
            inlineKeyboard=[[
                InlineKeyboardButton(
                    text="打开班表配置",
                    webAppUrl=shift_web_app_url,
                )
            ]]
        ),
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
        chat_id=message.chat.id,
        chat_title=message.chat.title,
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
        chat_id=message.chat.id,
        chat_title=message.chat.title,
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
        tg_username=callback.sender.username,
        chat_id=message.chat.id,
        chat_title=message.chat.title,
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
        tg_username=sender.username,
        chat_id=message.chat.id,
        chat_title=message.chat.title,
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


def _switch_attendance_group(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramCallbackUpdate,
) -> GatewayEventResponse:
    callback = update.callback_query
    message = callback.message
    if message.chat.type not in {"group", "supergroup"}:
        raise GatewayRouteOwnershipMismatchError()
    registration = registrations_repo.get_by_tg_id_cur(
        cursor,
        tg_id=callback.sender.id,
    )
    if registration is None:
        text = "您尚未注册。"
    else:
        updated = registrations_repo.update_registered_chat_by_tg_id_cur(
            cursor,
            tg_id=callback.sender.id,
            registered_chat_id=message.chat.id,
        )
        if updated != 1:
            raise RuntimeError("Attendance registration group update lost its owner row")
        text = "已记录本群为考勤群，请重新发送打卡截图。"
    return _callback_message_response(
        request,
        callback_id=callback.id,
        chat_id=message.chat.id,
        reply_to_message_id=message.message_id,
        text=text,
    )


def _registration_for_group_action(
    cursor: Cursor,
    *,
    tg_id: int,
    tg_username: str | None,
    chat_id: int,
    chat_title: str | None,
):
    if is_username_identity_chat(chat_id=chat_id, chat_title=chat_title):
        username = normalize_tg_username(tg_username)
        if not username:
            return None, "missing_username"
        registration = registrations_repo.get_by_tg_username_cur(
            cursor,
            tg_username=username,
        )
        if registration is None:
            return None, "unknown_username"
        return registration, None
    registration = registrations_repo.get_by_tg_id_cur(cursor, tg_id=tg_id)
    if registration is None:
        return None, "unregistered"
    return registration, None


def _username_identity_unmatched_text(reason: str) -> str:
    if reason == "missing_username":
        return "本群按 Telegram 用户名识别，请先设置用户名后再点离岗/返岗。"
    if reason == "unknown_username":
        return "本群名单未包含你的 Telegram 用户名，请联系管理员。"
    return "请先私聊机器人完成注册（英文名$工号）。"


def _leave_back_content(
    cursor: Cursor,
    *,
    tg_id: int,
    tg_username: str | None = None,
    chat_id: int,
    chat_title: str | None,
    operation: str,
    now_utc: datetime,
) -> tuple[str, InlineKeyboardMarkup | None]:
    registration, miss = _registration_for_group_action(
        cursor,
        tg_id=tg_id,
        tg_username=tg_username,
        chat_id=chat_id,
        chat_title=chat_title,
    )
    if registration is None:
        label = "离岗" if operation == "leave" else "返岗"
        return (
            _username_identity_unmatched_text(miss or "unregistered"),
            InlineKeyboardMarkup(
                inlineKeyboard=[[
                    InlineKeyboardButton(
                        text=label,
                        callbackData=f"att:{operation}",
                    )
                ]]
            ),
        )
    cursor.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
        (f"leave:{registration.employee_id}:{chat_id}",),
    )
    open_record = temporary_leave_records_repo.get_latest_open_cur(
        cursor,
        employee_id=registration.employee_id,
        chat_id=chat_id,
    )
    mutual_exclusion = requires_leave_mutual_exclusion(
        chat_id=chat_id, chat_title=chat_title
    )
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
            overtime = minutes >= leave_overtime_minutes_for_chat(
                chat_id=chat_id,
                chat_title=chat_title,
            )
        draft = build_back_draft(
            english_name=name,
            employee_id=registration.employee_id,
            leave_duration=duration,
            leave_overtime=overtime,
            now_local=now_local,
        )
    copy_fallback = requires_leave_back_copy_fallback(
        chat_id=chat_id, chat_title=chat_title
    )
    buttons = [
        InlineKeyboardButton(
            text=label,
            switchInlineQueryCurrentChat=draft,
        )
    ]
    if copy_fallback:
        buttons.append(InlineKeyboardButton(text="复制", copyText=draft))
    return (
        _GROUP_INLINE_HINT_REMOTE if copy_fallback else _GROUP_INLINE_HINT,
        InlineKeyboardMarkup(inlineKeyboard=[buttons]),
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
    chat_id: int,
    chat_title: str | None,
    label: str,
) -> tuple[str, InlineKeyboardMarkup | None]:
    registration = registrations_repo.get_by_tg_id_cur(cursor, tg_id=tg_id)
    if registration is None:
        callback_data = "att:signin" if label == "签到" else "att:signout"
        return (
            "请先私聊机器人完成注册（英文名$工号）。",
            InlineKeyboardMarkup(
                inlineKeyboard=[[
                    InlineKeyboardButton(
                        text=label,
                        callbackData=callback_data,
                    )
                ]]
            ),
        )
    draft = build_checkin_draft(
        english_name=registration.english_name or "",
        employee_id=registration.employee_id,
        action=label,
    )
    copy_fallback = requires_remote_diff_checkin(
        chat_id=chat_id,
        chat_title=chat_title,
    )
    buttons = [
        InlineKeyboardButton(
            text=label,
            switchInlineQueryCurrentChat=draft,
        )
    ]
    if copy_fallback:
        buttons.append(InlineKeyboardButton(text="复制", copyText=draft))
    return (
        _GROUP_INLINE_HINT_REMOTE if copy_fallback else _GROUP_INLINE_HINT,
        InlineKeyboardMarkup(inlineKeyboard=[buttons]),
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
    registration, miss = _registration_for_group_action(
        cursor,
        tg_id=sender.id,
        tg_username=sender.username,
        chat_id=message.chat.id,
        chat_title=message.chat.title,
    )
    if registration is None:
        if miss in {"missing_username", "unknown_username"}:
            return _group_report_message(
                request,
                chat_id=message.chat.id,
                reply_to_message_id=message.message_id,
                text=_username_identity_unmatched_text(miss),
            )
        return _group_report_without_actions(request)

    registrations_repo.bind_tg_id_if_username_matches_cur(
        cursor,
        tg_id=sender.id,
        tg_username=sender.username,
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
    mutual_exclusion = requires_leave_mutual_exclusion(
        chat_id=message.chat.id,
        chat_title=message.chat.title,
    )
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


def _group_event_chat(update: object):
    if isinstance(update, TelegramMessageUpdate):
        return update.message.chat
    if isinstance(update, TelegramEditedMessageUpdate):
        return update.edited_message.chat
    if isinstance(update, TelegramCallbackUpdate):
        return update.callback_query.message.chat
    return None


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
    tokens = text.strip().split(maxsplit=1)
    if not tokens:
        return None
    first_token = tokens[0]
    return first_token.split("@", maxsplit=1)[0].lower()


def _is_registration_begin_text(text: str | None) -> bool:
    normalized = (text or "").strip()
    return normalized in {"注册", "绑定考勤资料"} or (
        _command_name(normalized) in {"/start", "/attendance_register"}
    )
