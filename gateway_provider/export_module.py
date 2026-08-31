from __future__ import annotations

import asyncio
import base64
import io
import logging
import zipfile
from datetime import datetime
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from psycopg2.extensions import cursor as Cursor

from gateway_provider.contracts import (
    AnswerCallbackAction,
    BytesMediaSource,
    DeleteMessageAction,
    GatewayEventRequest,
    GatewayEventResponse,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    SendDocumentAction,
    SendMessageAction,
    TelegramCallbackUpdate,
    TelegramMessageUpdate,
    ReleaseSessionDirective,
    UnchangedSessionDirective,
)
from infra.admin_export_scope_config import admin_export_chat_id_for_employee
from infra.leave_return_keyboard_only_config import (
    is_leave_return_keyboard_only_chat,
    is_qdyyz_chat,
    leave_overtime_minutes_for_chat,
)
from repositories import registrations_repo, worker_schedule_repo
from services import attendance_export_service, leave_export_service


log = logging.getLogger(__name__)

ExportMode = str  # "attendance" | "leave"

_RANGE_KINDS: dict[str, attendance_export_service.ExportRangeKind] = {
    "today": "today",
    "yesterday": "yesterday",
    "week": "week",
    "last_week": "last_week",
    "month": "month",
    "last_month": "last_month",
}
_LEGACY_EXPORT_KINDS: dict[str, attendance_export_service.ExportRangeKind] = {
    f"att:export:{suffix}": kind for suffix, kind in _RANGE_KINDS.items()
}
_MODE_ENTRY_CALLBACKS = {
    "att:export:attendance": "attendance",
    "att:export:leave": "leave",
}
_XLSX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

MSG_NO_EXPORT_SCOPE = "未配置导出范围，请联系管理员。"


def admin_employee_id(cursor: Cursor, *, tg_id: int) -> str | None:
    cursor.execute(
        "SELECT employee_id FROM public.registrations WHERE tg_id = %s",
        (int(tg_id),),
    )
    row = cursor.fetchone()
    if not row or row[0] is None:
        return None
    return str(row[0]).strip() or None


def resolve_admin_export_chat_id(cursor: Cursor, *, tg_id: int) -> int | None:
    employee_id = admin_employee_id(cursor, tg_id=tg_id)
    if employee_id is None:
        return None
    return admin_export_chat_id_for_employee(employee_id=employee_id)


def is_leave_export_scope(*, chat_id: int | None) -> bool:
    return is_leave_return_keyboard_only_chat(chat_id=chat_id, chat_title=None)


def is_dual_admin_export_scope(*, chat_id: int | None) -> bool:
    """QDYYZ：管理员菜单同时提供考勤导出与报备导出。"""
    return is_qdyyz_chat(chat_id=chat_id, chat_title=None)


def ensure_admin_identity(
    cursor: Cursor,
    *,
    tg_id: int,
    tg_username: str | None,
) -> None:
    registrations_repo.bind_tg_id_if_username_matches_cur(
        cursor,
        tg_id=tg_id,
        tg_username=tg_username,
    )


def process_export_callback(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramCallbackUpdate,
    *,
    defer_long_operation: bool = True,
) -> GatewayEventResponse:
    callback = update.callback_query
    message = callback.message
    if message.chat.type != "private" or callback.sender.id != message.chat.id:
        return _callback_reply(request, update, text="导出仅支持私聊中使用。")
    ensure_admin_identity(
        cursor,
        tg_id=callback.sender.id,
        tg_username=callback.sender.username,
    )
    if not is_admin(cursor, tg_id=callback.sender.id):
        return _callback_reply(request, update, text="无权限操作")
    export_chat_id = resolve_admin_export_chat_id(cursor, tg_id=callback.sender.id)
    if export_chat_id is None:
        return _callback_reply(request, update, text=MSG_NO_EXPORT_SCOPE)
    dual_mode = is_dual_admin_export_scope(chat_id=export_chat_id)
    default_leave_mode = is_leave_export_scope(chat_id=export_chat_id) and not dual_mode
    entry_mode = _MODE_ENTRY_CALLBACKS.get(callback.data)
    if callback.data == "att:export" or entry_mode is not None:
        mode: ExportMode = entry_mode or (
            "leave" if default_leave_mode else "attendance"
        )
        return _callback_reply(
            request,
            update,
            text="请选择导出范围：",
            reply_markup=_range_keyboard(mode=mode),
        )
    parsed = _parse_export_range_callback(
        callback.data,
        default_leave_mode=default_leave_mode,
    )
    if parsed is None:
        return _callback_reply(request, update, text="导出范围无效，请重新选择。")
    export_mode, kind = parsed
    leave_mode = export_mode == "leave"

    received_at = datetime.fromisoformat(request.receivedAt.replace("Z", "+00:00"))
    today = received_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
    start, end, range_label = attendance_export_service.resolve_export_date_range(
        kind=kind,
        today=today,
    )
    progress_noun = "报备导出" if leave_mode else "考勤导出"
    progress_action_id = f"{request.eventId}.progress"
    initial_actions = [
        AnswerCallbackAction(
            actionId=f"{request.eventId}.callback",
            type="ANSWER_CALLBACK",
            callbackQueryId=callback.id,
        ),
        SendMessageAction(
            actionId=progress_action_id,
            type="SEND_MESSAGE",
            chatId=message.chat.id,
            replyToMessageId=message.message_id,
            text=(
                f"正在生成{range_label}{progress_noun}（{start.isoformat()}～"
                f"{end.isoformat()}），请稍候…"
            ),
        ),
    ]
    delete_progress = DeleteMessageAction(
        actionId=f"{request.eventId}.progress-delete",
        type="DELETE_MESSAGE",
        chatId=message.chat.id,
        messageIdSourceActionId=progress_action_id,
    )
    if defer_long_operation:
        worker_schedule_repo.enqueue_run_cur(
            cursor,
            run_key=f"deferred-export:{request.eventId}",
            job_kind="ADMIN_EXPORT_PROCESS",
            payload={
                "event": request.model_dump(
                    mode="json",
                    by_alias=True,
                    exclude_none=True,
                ),
                "progressActionId": progress_action_id,
            },
            now=received_at,
        )
        return GatewayEventResponse(
            protocolVersion="1.0",
            eventId=request.eventId,
            result="PROCESSED",
            session=UnchangedSessionDirective(directive="UNCHANGED"),
            actions=initial_actions,
        )
    try:
        if leave_mode:
            leave_rows = leave_export_service.collect_leave_rows_for_chat(
                chat_id=export_chat_id,
                start=start,
                end=end,
            )
            body = leave_export_service.encode_leave_export_xlsx(
                rows=leave_rows,
                overtime_minutes=leave_overtime_minutes_for_chat(chat_id=export_chat_id),
            )
            body = _deterministic_xlsx(body, generated_at=received_at)
            caption = f"{range_label}报备导出（{len(leave_rows)} 条）"
            file_name = leave_export_service.leave_export_filename(start=start, end=end)
        else:
            rows = asyncio.run(
                attendance_export_service.collect_rows_for_single_group(
                    chat_id=export_chat_id,
                    start=start,
                    end=end,
                )
            )
            pivot, overview, dates = attendance_export_service.build_pivot_and_overview(
                rows=rows,
                start=start,
                end=end,
            )
            body = attendance_export_service.encode_attendance_export_xlsx(
                pivot=pivot,
                dates=dates,
                overview=overview,
                range_label=range_label,
            )
            body = _deterministic_xlsx(body, generated_at=received_at)
            caption = f"{range_label}考勤导出（{overview.expected_count} 人）"
            file_name = attendance_export_service.export_filename(
                start=start,
                end=end,
            )
    except Exception:
        log.exception("Attendance export generation failed")
        return GatewayEventResponse(
            protocolVersion="1.0",
            eventId=request.eventId,
            result="PROCESSED",
            session=UnchangedSessionDirective(directive="UNCHANGED"),
            actions=[
                *initial_actions,
                SendMessageAction(
                    actionId=f"{request.eventId}.failure",
                    type="SEND_MESSAGE",
                    chatId=message.chat.id,
                    replyToMessageId=message.message_id,
                    text="导出失败，请稍后重试或联系管理员查看服务日志。",
                ),
                delete_progress,
            ],
        )
    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=UnchangedSessionDirective(directive="UNCHANGED"),
        actions=[
            *initial_actions,
            SendDocumentAction(
                actionId=f"{request.eventId}.document",
                type="SEND_DOCUMENT",
                chatId=message.chat.id,
                replyToMessageId=message.message_id,
                caption=caption,
                document=BytesMediaSource(
                    source="BYTES",
                    contentBase64=base64.b64encode(body).decode("ascii"),
                    fileName=file_name,
                    mimeType=_XLSX_MIME_TYPE,
                ),
            ),
            delete_progress,
        ],
    )


def process_export_message(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramMessageUpdate,
    *,
    export_mode: ExportMode | None = None,
) -> GatewayEventResponse:
    message = update.message
    sender = message.sender
    if message.chat.type != "private" or sender is None:
        text = "导出仅支持私聊中使用。"
        reply_markup = None
    else:
        ensure_admin_identity(
            cursor,
            tg_id=sender.id,
            tg_username=sender.username,
        )
        if not is_admin(cursor, tg_id=sender.id):
            text = "无权限操作"
            reply_markup = None
        else:
            export_chat_id = resolve_admin_export_chat_id(cursor, tg_id=sender.id)
            if export_chat_id is None:
                text = MSG_NO_EXPORT_SCOPE
                reply_markup = None
            elif is_dual_admin_export_scope(chat_id=export_chat_id) and export_mode is None:
                text = "请选择导出类型："
                reply_markup = InlineKeyboardMarkup(
                    inlineKeyboard=[
                        [
                            InlineKeyboardButton(
                                text="考勤导出",
                                callbackData="att:export:attendance",
                            ),
                            InlineKeyboardButton(
                                text="报备导出",
                                callbackData="att:export:leave",
                            ),
                        ]
                    ]
                )
            else:
                dual = is_dual_admin_export_scope(chat_id=export_chat_id)
                mode: ExportMode = export_mode or (
                    "leave"
                    if is_leave_export_scope(chat_id=export_chat_id) and not dual
                    else "attendance"
                )
                text = "请选择导出范围："
                reply_markup = _range_keyboard(mode=mode)
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


def is_export_callback(data: str) -> bool:
    if data == "att:export" or data in _MODE_ENTRY_CALLBACKS:
        return True
    if data in _LEGACY_EXPORT_KINDS:
        return True
    return any(
        data.startswith(f"att:export:{mode}:") for mode in ("attendance", "leave")
    )


def is_admin(cursor: Cursor, *, tg_id: int) -> bool:
    cursor.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM public.registrations r
            INNER JOIN public.admin_list a
                ON a.admin_employee_id = r.employee_id
            WHERE r.tg_id = %s
        )
        """,
        (int(tg_id),),
    )
    row = cursor.fetchone()
    return bool(row and row[0])


def _range_keyboard(*, mode: ExportMode = "attendance") -> InlineKeyboardMarkup:
    def _cb(kind: str) -> str:
        return f"att:export:{mode}:{kind}"

    return InlineKeyboardMarkup(
        inlineKeyboard=[
            [
                InlineKeyboardButton(text="今日", callbackData=_cb("today")),
                InlineKeyboardButton(text="本周", callbackData=_cb("week")),
                InlineKeyboardButton(text="本月", callbackData=_cb("month")),
            ],
            [
                InlineKeyboardButton(text="昨天", callbackData=_cb("yesterday")),
                InlineKeyboardButton(text="上周", callbackData=_cb("last_week")),
                InlineKeyboardButton(text="上月", callbackData=_cb("last_month")),
            ],
        ]
    )


def _parse_export_range_callback(
    data: str,
    *,
    default_leave_mode: bool,
) -> tuple[ExportMode, attendance_export_service.ExportRangeKind] | None:
    for mode in ("attendance", "leave"):
        prefix = f"att:export:{mode}:"
        if data.startswith(prefix):
            kind = _RANGE_KINDS.get(data[len(prefix) :])
            if kind is None:
                return None
            return mode, kind
    kind = _LEGACY_EXPORT_KINDS.get(data)
    if kind is None:
        return None
    return ("leave" if default_leave_mode else "attendance"), kind


def _callback_reply(
    request: GatewayEventRequest,
    update: TelegramCallbackUpdate,
    *,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> GatewayEventResponse:
    callback = update.callback_query
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
                chatId=callback.message.chat.id,
                replyToMessageId=callback.message.message_id,
                text=text,
                replyMarkup=reply_markup,
            ),
        ],
    )


def _deterministic_xlsx(payload: bytes, *, generated_at: datetime) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(payload), "r")
    output = io.BytesIO()
    generated_text = generated_at.isoformat().replace("+00:00", "Z")
    with source, zipfile.ZipFile(
        output,
        "w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as target:
        for name in sorted(source.namelist()):
            body = source.read(name)
            if name == "docProps/core.xml":
                body = _normalized_core_properties(body, generated_text)
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            target.writestr(info, body)
    return output.getvalue()


def _normalized_core_properties(payload: bytes, generated_text: str) -> bytes:
    root = ElementTree.fromstring(payload)
    for element in root.iter():
        if element.tag.endswith("}created") or element.tag.endswith("}modified"):
            element.text = generated_text
    return ElementTree.tostring(root, encoding="utf-8", xml_declaration=True)
