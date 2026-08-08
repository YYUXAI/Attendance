from __future__ import annotations

import asyncio
import base64
import io
import zipfile
from datetime import datetime
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

from psycopg2.extensions import cursor as Cursor

from gateway_provider.contracts import (
    AnswerCallbackAction,
    BytesMediaSource,
    GatewayEventRequest,
    GatewayEventResponse,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    SendDocumentAction,
    SendMessageAction,
    TelegramCallbackUpdate,
    UnchangedSessionDirective,
)
from services import attendance_export_service


_EXPORT_KINDS: dict[str, attendance_export_service.ExportRangeKind] = {
    "att:export:today": "today",
    "att:export:yesterday": "yesterday",
    "att:export:week": "week",
    "att:export:last_week": "last_week",
    "att:export:month": "month",
    "att:export:last_month": "last_month",
}
_XLSX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)


def process_export_callback(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramCallbackUpdate,
) -> GatewayEventResponse:
    callback = update.callback_query
    message = callback.message
    if message.chat.type != "private" or callback.sender.id != message.chat.id:
        return _callback_reply(request, update, text="导出仅支持私聊中使用。")
    if not is_admin(cursor, tg_id=callback.sender.id):
        return _callback_reply(request, update, text="无权限操作")
    if callback.data == "att:export":
        return _callback_reply(
            request,
            update,
            text="请选择导出范围：",
            reply_markup=_range_keyboard(),
        )
    kind = _EXPORT_KINDS.get(callback.data)
    if kind is None:
        return _callback_reply(request, update, text="导出范围无效，请重新选择。")

    received_at = datetime.fromisoformat(request.receivedAt.replace("Z", "+00:00"))
    today = received_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
    start, end, range_label = attendance_export_service.resolve_export_date_range(
        kind=kind,
        today=today,
    )
    rows = asyncio.run(
        attendance_export_service.collect_rows_for_range(
            start=start,
            end=end,
            bot=None,
            export_tg_id=callback.sender.id,
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
            SendDocumentAction(
                actionId=f"{request.eventId}.document",
                type="SEND_DOCUMENT",
                chatId=message.chat.id,
                replyToMessageId=message.message_id,
                caption=f"{range_label}考勤导出（{overview.expected_count} 人）",
                document=BytesMediaSource(
                    source="BYTES",
                    contentBase64=base64.b64encode(body).decode("ascii"),
                    fileName=attendance_export_service.export_filename(
                        start=start,
                        end=end,
                    ),
                    mimeType=_XLSX_MIME_TYPE,
                ),
            ),
        ],
    )


def is_export_callback(data: str) -> bool:
    return data == "att:export" or data in _EXPORT_KINDS


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


def _range_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inlineKeyboard=[
            [
                InlineKeyboardButton(text="今日", callbackData="att:export:today"),
                InlineKeyboardButton(text="本周", callbackData="att:export:week"),
                InlineKeyboardButton(text="本月", callbackData="att:export:month"),
            ],
            [
                InlineKeyboardButton(
                    text="昨天",
                    callbackData="att:export:yesterday",
                ),
                InlineKeyboardButton(
                    text="上周",
                    callbackData="att:export:last_week",
                ),
                InlineKeyboardButton(
                    text="上月",
                    callbackData="att:export:last_month",
                ),
            ],
        ]
    )


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
