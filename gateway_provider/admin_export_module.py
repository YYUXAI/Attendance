from __future__ import annotations

import base64
import codecs
import csv
import io
from datetime import date
from typing import Any

from psycopg2.extensions import cursor as Cursor

from gateway_provider.contracts import (
    AcquireSessionDirective,
    AnswerCallbackAction,
    BytesMediaSource,
    GatewayEventRequest,
    GatewayEventResponse,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReleaseSessionDirective,
    SendDocumentAction,
    SendMessageAction,
    TelegramCallbackUpdate,
    TelegramMessage,
    TelegramMessageUpdate,
    UnchangedSessionDirective,
)
from gateway_provider.export_module import is_admin
from services.csv_security import safe_csv_cell


MSG_NON_PRIVATE = "该导出功能仅限在私聊中使用，请到私聊窗口重试。"
MSG_NO_PERMISSION = "你没有权限使用该指令"
MSG_PROMPT_SHIFT_ID = "请输入您要下载的班次ID"
MSG_PROMPT_START_DATE = "请按照 年$月$日 发送您要下载数据的起点时间，例如：\n2026$4$12"
MSG_PROMPT_END_DATE = "请按照 年$月$日 发送您要下载数据的终点时间，例如：\n2026$4$16"
MSG_INVALID_SHIFT_FORMAT = "班次ID格式不正确，请输入纯数字整数。"
MSG_SHIFT_NOT_FOUND = "该班次不存在，请重新输入。"
MSG_INVALID_DATE_FORMAT = "日期格式不正确，请按 年$月$日 发送，例如：2026$4$12"
MSG_END_BEFORE_START = "终点日期不能早于起点日期，请重新输入终点日期。"
MSG_DATE_RANGE_TOO_LARGE = "导出日期范围不能超过 366 天，请重新输入终点日期。"
MSG_EXPORT_TOO_LARGE = "导出数据量过大，请缩小日期范围后重新发送 /test_1。"
MSG_EXPORT_FAILED = "导出失败，请重新发送 /test_1 后再试。"

MAX_EXPORT_DATE_DAYS = 366
MAX_EXPORT_ROWS_PER_FILE = 50_000
MAX_EXPORT_TOTAL_ROWS = 100_000
MAX_EXPORT_BASE64_BYTES_PER_FILE = 16 * 1024 * 1024
MAX_EXPORT_TOTAL_BASE64_BYTES = 32 * 1024 * 1024
EXPORT_FETCH_BATCH_SIZE = 1_000


class AdminExportLimitError(ValueError):
    pass


def is_admin_export_test_message(message: TelegramMessage) -> bool:
    return _is_command(message.text) or _is_command(message.caption)


def is_admin_export_callback(callback_data: str) -> bool:
    return callback_data in {
        "att:admin_export:confirm",
        "att:admin_export:cancel",
    }


def process_admin_export_entry(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramMessageUpdate,
) -> GatewayEventResponse:
    message = update.message
    sender = message.sender
    if message.chat.type != "private":
        return _message_response(request, message, MSG_NON_PRIVATE, acquire=False)
    if sender is None:
        return _message_response(request, message, MSG_EXPORT_FAILED, acquire=False)
    allowed, error_text = _admin_check(cursor, tg_id=sender.id)
    if not allowed:
        return _message_response(
            request,
            message,
            error_text or MSG_NO_PERMISSION,
            acquire=False,
        )
    cursor.execute(
        """
        INSERT INTO attendance_admin_export_sessions (
            tg_id, private_chat_id, stage, shift_id, start_date, end_date,
            updated_at, expires_at
        )
        VALUES (%s, %s, 'waiting_shift_id', NULL, NULL, NULL,
                clock_timestamp(), clock_timestamp() + INTERVAL '15 minutes')
        ON CONFLICT (tg_id) DO UPDATE
        SET private_chat_id = EXCLUDED.private_chat_id,
            stage = 'waiting_shift_id',
            shift_id = NULL,
            start_date = NULL,
            end_date = NULL,
            updated_at = clock_timestamp(),
            expires_at = clock_timestamp() + INTERVAL '15 minutes'
        """,
        (sender.id, message.chat.id),
    )
    return _message_response(request, message, MSG_PROMPT_SHIFT_ID, acquire=True)


def has_active_admin_export_session(
    cursor: Cursor,
    *,
    tg_id: int,
    private_chat_id: int,
) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM attendance_admin_export_sessions
        WHERE tg_id = %s AND private_chat_id = %s
          AND expires_at >= clock_timestamp()
        """,
        (tg_id, private_chat_id),
    )
    return cursor.fetchone() is not None


def process_admin_export_text(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramMessageUpdate,
) -> GatewayEventResponse:
    message = update.message
    sender = message.sender
    if message.chat.type != "private" or sender is None or message.text is None:
        return _message_response(request, message, MSG_EXPORT_FAILED, acquire=False)
    allowed, error_text = _admin_check(cursor, tg_id=sender.id)
    if not allowed:
        _clear(cursor, tg_id=sender.id)
        return _message_response(
            request,
            message,
            error_text or MSG_NO_PERMISSION,
            acquire=False,
        )
    session = _session(cursor, tg_id=sender.id, private_chat_id=message.chat.id)
    if session is None:
        return _message_response(request, message, MSG_EXPORT_FAILED, acquire=False)
    stage, shift_id, start_date, _end_date = session
    raw = message.text.strip()
    if stage == "waiting_shift_id":
        if not raw.isdigit():
            return _message_response(request, message, MSG_INVALID_SHIFT_FORMAT, acquire=True)
        parsed_shift_id = int(raw)
        cursor.execute("SELECT 1 FROM shifts WHERE id = %s", (parsed_shift_id,))
        if cursor.fetchone() is None:
            return _message_response(request, message, MSG_SHIFT_NOT_FOUND, acquire=True)
        _advance(
            cursor,
            tg_id=sender.id,
            stage="waiting_start_date",
            shift_id=parsed_shift_id,
        )
        return _message_response(request, message, MSG_PROMPT_START_DATE, acquire=True)
    if stage == "waiting_start_date":
        parsed = _parse_date(raw)
        if parsed is None:
            return _message_response(request, message, MSG_INVALID_DATE_FORMAT, acquire=True)
        _advance(
            cursor,
            tg_id=sender.id,
            stage="waiting_end_date",
            start_date=parsed,
        )
        return _message_response(request, message, MSG_PROMPT_END_DATE, acquire=True)
    if stage == "waiting_end_date":
        parsed = _parse_date(raw)
        if parsed is None:
            return _message_response(request, message, MSG_INVALID_DATE_FORMAT, acquire=True)
        if start_date is None or parsed < start_date:
            return _message_response(request, message, MSG_END_BEFORE_START, acquire=True)
        if _inclusive_date_days(start_date, parsed) > MAX_EXPORT_DATE_DAYS:
            return _message_response(
                request,
                message,
                MSG_DATE_RANGE_TOO_LARGE,
                acquire=True,
            )
        if shift_id is None:
            _clear(cursor, tg_id=sender.id)
            return _message_response(request, message, MSG_EXPORT_FAILED, acquire=False)
        _advance(
            cursor,
            tg_id=sender.id,
            stage="waiting_confirm",
            end_date=parsed,
        )
        return _message_response(
            request,
            message,
            (
                "请确认您的下载范围：\n\n"
                f"班次：{shift_id}\n"
                f"日期：{start_date.isoformat()} 至 {parsed.isoformat()}"
            ),
            acquire=True,
            reply_markup=InlineKeyboardMarkup(
                inlineKeyboard=[[
                    InlineKeyboardButton(
                        text="确认",
                        callbackData="att:admin_export:confirm",
                    ),
                    InlineKeyboardButton(
                        text="取消",
                        callbackData="att:admin_export:cancel",
                    ),
                ]]
            ),
        )
    return _message_response(request, message, MSG_EXPORT_FAILED, acquire=True)


def process_admin_export_callback(
    request: GatewayEventRequest,
    cursor: Cursor,
    update: TelegramCallbackUpdate,
) -> GatewayEventResponse:
    callback = update.callback_query
    message = callback.message
    if message.chat.type != "private":
        return _callback_message_response(request, update, MSG_NON_PRIVATE)
    if callback.data == "att:admin_export:cancel":
        _clear(cursor, tg_id=callback.sender.id)
        return _callback_message_response(request, update, "已取消")
    allowed, error_text = _admin_check(cursor, tg_id=callback.sender.id)
    if not allowed:
        _clear(cursor, tg_id=callback.sender.id)
        return _callback_message_response(
            request,
            update,
            error_text or MSG_NO_PERMISSION,
        )
    session = _session(
        cursor,
        tg_id=callback.sender.id,
        private_chat_id=message.chat.id,
    )
    if session is None:
        return _callback_message_response(request, update, MSG_EXPORT_FAILED)
    stage, shift_id, start_date, end_date = session
    if (
        stage != "waiting_confirm"
        or shift_id is None
        or start_date is None
        or end_date is None
    ):
        _clear(cursor, tg_id=callback.sender.id)
        return _callback_message_response(request, update, MSG_EXPORT_FAILED)
    try:
        files = prepare_three_csv_exports(
            cursor,
            shift_id=shift_id,
            start_date=start_date,
            end_date=end_date,
        )
    except AdminExportLimitError:
        _clear(cursor, tg_id=callback.sender.id)
        return _callback_message_response(request, update, MSG_EXPORT_TOO_LARGE)
    except Exception:
        _clear(cursor, tg_id=callback.sender.id)
        return _callback_message_response(request, update, MSG_EXPORT_FAILED)
    _clear(cursor, tg_id=callback.sender.id)
    actions: list[Any] = [
        AnswerCallbackAction(
            actionId=f"{request.eventId}.callback",
            type="ANSWER_CALLBACK",
            callbackQueryId=callback.id,
        )
    ]
    for index, (file_name, body) in enumerate(files, start=1):
        actions.append(
            SendDocumentAction(
                actionId=f"{request.eventId}.document-{index}",
                type="SEND_DOCUMENT",
                chatId=message.chat.id,
                replyToMessageId=message.message_id,
                document=BytesMediaSource(
                    source="BYTES",
                    contentBase64=base64.b64encode(body).decode("ascii"),
                    fileName=file_name,
                    mimeType="text/csv; charset=utf-8",
                ),
            )
        )
    return GatewayEventResponse(
        protocolVersion="1.0",
        eventId=request.eventId,
        result="PROCESSED",
        session=ReleaseSessionDirective(directive="RELEASE"),
        actions=actions,
    )


def prepare_three_csv_exports(
    cursor: Cursor,
    *,
    shift_id: int,
    start_date: date,
    end_date: date,
) -> list[tuple[str, bytes]]:
    if end_date < start_date:
        raise AdminExportLimitError(MSG_END_BEFORE_START)
    if _inclusive_date_days(start_date, end_date) > MAX_EXPORT_DATE_DAYS:
        raise AdminExportLimitError("导出日期范围不能超过 366 天")

    specs = (
        (
            "clock_records",
            (
                "id", "employee_id", "shift_id", "clock_time", "clock_action",
                "tg_id", "chat_id", "file_id",
            ),
            """
            SELECT id, employee_id, shift_id, clock_time, clock_action,
                   tg_id, chat_id, file_id
            FROM public.clock_records
            WHERE shift_id = %s
              AND (clock_time AT TIME ZONE 'Asia/Shanghai')::date >= %s
              AND (clock_time AT TIME ZONE 'Asia/Shanghai')::date <= %s
            """,
        ),
        (
            "temporary_leave_records",
            (
                "id", "employee_id", "shift_id", "english_name", "tg_id",
                "chat_id", "leave_at", "back_at", "duration_minutes", "reason",
                "remark_required", "status",
            ),
            """
            SELECT leave.id, leave.employee_id, registration.shift_id,
                   leave.english_name, leave.tg_id, leave.chat_id,
                   leave.leave_at, leave.back_at, leave.duration_minutes,
                   leave.reason, leave.remark_required, leave.status
            FROM public.temporary_leave_records AS leave
            JOIN public.registrations AS registration
              ON registration.employee_id = leave.employee_id
            WHERE registration.shift_id = %s
              AND (leave.leave_at AT TIME ZONE 'Asia/Shanghai')::date >= %s
              AND (leave.leave_at AT TIME ZONE 'Asia/Shanghai')::date <= %s
            """,
        ),
        (
            "effective_leave_days",
            ("id", "employee_id", "shift_id", "leave_date"),
            """
            SELECT leave.id, leave.employee_id, registration.shift_id,
                   leave.leave_date
            FROM public.effective_leave_days AS leave
            JOIN public.registrations AS registration
              ON registration.employee_id = leave.employee_id
            WHERE registration.shift_id = %s
              AND leave.leave_date >= %s
              AND leave.leave_date <= %s
            """,
        ),
    )
    preflight: list[tuple[int, int]] = []
    total_rows = 0
    total_projected_base64_bytes = 0
    for _table, columns, query in specs:
        cursor.execute(
            f"""
            SELECT COUNT(*)::bigint,
                   COALESCE(
                       SUM(octet_length(row_to_json(export_rows)::text)),
                       0
                   )::bigint
            FROM ({query}) AS export_rows
            """,
            (shift_id, start_date, end_date),
        )
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("admin export preflight returned no result")
        row_count = int(row[0])
        json_octets = int(row[1])
        projected_csv_bytes = (
            len(codecs.BOM_UTF8)
            + len(",".join(columns).encode("utf-8"))
            + 1
            + json_octets
            + row_count
        )
        projected_base64_bytes = _base64_encoded_size(projected_csv_bytes)
        total_rows += row_count
        total_projected_base64_bytes += projected_base64_bytes
        if (
            row_count > MAX_EXPORT_ROWS_PER_FILE
            or projected_base64_bytes > MAX_EXPORT_BASE64_BYTES_PER_FILE
            or total_rows > MAX_EXPORT_TOTAL_ROWS
            or total_projected_base64_bytes > MAX_EXPORT_TOTAL_BASE64_BYTES
        ):
            raise AdminExportLimitError("导出数据量过大")
        preflight.append((row_count, projected_base64_bytes))

    part = f"{start_date.isoformat()}_to_{end_date.isoformat()}"
    files: list[tuple[str, bytes]] = []
    total_actual_base64_bytes = 0
    for (table, columns, query), (expected_rows, _projected_size) in zip(
        specs,
        preflight,
        strict=True,
    ):
        cursor.execute(
            f"{query}\nORDER BY id",
            (shift_id, start_date, end_date),
        )
        body, actual_rows = _encode_csv_cursor(columns, cursor)
        if actual_rows != expected_rows:
            raise RuntimeError("admin export changed between preflight and read")
        total_actual_base64_bytes += _base64_encoded_size(len(body))
        if total_actual_base64_bytes > MAX_EXPORT_TOTAL_BASE64_BYTES:
            raise AdminExportLimitError("导出数据量过大")
        files.append((f"{table}_shift_{shift_id}_{part}.csv", body))
    return files


def _inclusive_date_days(start_date: date, end_date: date) -> int:
    return (end_date - start_date).days + 1


def _base64_encoded_size(raw_size: int) -> int:
    return 4 * ((raw_size + 2) // 3)


class _BoundedCsvBuffer:
    def __init__(self) -> None:
        self._body = bytearray(codecs.BOM_UTF8)

    def write(self, value: str) -> int:
        encoded = value.encode("utf-8")
        projected_size = len(self._body) + len(encoded)
        if _base64_encoded_size(projected_size) > MAX_EXPORT_BASE64_BYTES_PER_FILE:
            raise AdminExportLimitError("导出数据量过大")
        self._body.extend(encoded)
        return len(value)

    def bytes(self) -> bytes:
        return bytes(self._body)


def _encode_csv_cursor(
    headers: tuple[str, ...],
    cursor: Cursor,
) -> tuple[bytes, int]:
    output = _BoundedCsvBuffer()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(headers)
    row_count = 0
    while True:
        rows = cursor.fetchmany(EXPORT_FETCH_BATCH_SIZE)
        if not rows:
            break
        for row in rows:
            writer.writerow([safe_csv_cell(value) for value in row])
            row_count += 1
    return output.bytes(), row_count


def _session(
    cursor: Cursor,
    *,
    tg_id: int,
    private_chat_id: int,
) -> tuple[str, int | None, date | None, date | None] | None:
    cursor.execute(
        """
        SELECT stage, shift_id, start_date, end_date
        FROM attendance_admin_export_sessions
        WHERE tg_id = %s AND private_chat_id = %s
          AND expires_at >= clock_timestamp()
        FOR UPDATE
        """,
        (tg_id, private_chat_id),
    )
    row = cursor.fetchone()
    return row if row is None else (str(row[0]), row[1], row[2], row[3])


def _advance(
    cursor: Cursor,
    *,
    tg_id: int,
    stage: str,
    shift_id: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> None:
    assignments = ["stage = %s", "updated_at = clock_timestamp()", "expires_at = clock_timestamp() + INTERVAL '15 minutes'"]
    values: list[object] = [stage]
    for column, value in (
        ("shift_id", shift_id),
        ("start_date", start_date),
        ("end_date", end_date),
    ):
        if value is not None:
            assignments.append(f"{column} = %s")
            values.append(value)
    values.append(tg_id)
    cursor.execute(
        f"UPDATE attendance_admin_export_sessions SET {', '.join(assignments)} WHERE tg_id = %s",
        tuple(values),
    )


def _clear(cursor: Cursor, *, tg_id: int) -> None:
    cursor.execute("DELETE FROM attendance_admin_export_sessions WHERE tg_id = %s", (tg_id,))


def _message_response(
    request: GatewayEventRequest,
    message: TelegramMessage,
    text: str,
    *,
    acquire: bool,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> GatewayEventResponse:
    session = (
        AcquireSessionDirective(directive="ACQUIRE", ttlSeconds=900)
        if acquire
        else ReleaseSessionDirective(directive="RELEASE")
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
                replyMarkup=reply_markup,
            )
        ],
    )


def _callback_message_response(
    request: GatewayEventRequest,
    update: TelegramCallbackUpdate,
    text: str,
) -> GatewayEventResponse:
    callback = update.callback_query
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
                chatId=callback.message.chat.id,
                replyToMessageId=callback.message.message_id,
                text=text,
            ),
        ],
    )


def _admin_check(cursor: Cursor, *, tg_id: int) -> tuple[bool, str | None]:
    try:
        allowed = is_admin(cursor, tg_id=tg_id)
    except Exception:
        return False, MSG_EXPORT_FAILED
    return (True, None) if allowed else (False, MSG_NO_PERMISSION)


def _parse_date(text: str) -> date | None:
    parts = [part.strip() for part in text.split("$")]
    if len(parts) != 3 or any(not part.isdigit() for part in parts):
        return None
    try:
        return date(*(int(part) for part in parts))
    except ValueError:
        return None


def _is_command(value: str | None) -> bool:
    text = (value or "").strip()
    return text == "/test_1" or (
        text.startswith("/test_1@")
        and " " not in text
        and len(text) > len("/test_1@")
    )


def _encode_csv(headers: tuple[str, ...], rows: list[tuple[Any, ...]]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([safe_csv_cell(value) for value in row])
    return codecs.BOM_UTF8 + output.getvalue().encode("utf-8")
