from __future__ import annotations

import codecs
import csv
import io
import logging
import re
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional, Tuple

from repositories import admin_list_repo
from repositories import audit_results_export_repo
from repositories import effective_leave_days_export_repo
from repositories import qc_results_export_repo
from repositories import shifts_repo

log = logging.getLogger(__name__)

MSG_NON_PRIVATE = "该导出功能仅限在私聊中使用，请到私聊窗口重试。"
MSG_NO_PERMISSION = "你没有权限使用该指令"
MSG_PROMPT_SHIFT_ID = "请输入您要下载的班次ID"
MSG_PROMPT_START_DATE = "请按照 年$月$日 发送您要下载数据的起点时间，例如：\n2026$4$12"
MSG_PROMPT_END_DATE = "请按照 年$月$日 发送您要下载数据的终点时间，例如：\n2026$4$16"
MSG_INVALID_SHIFT_FORMAT = "班次ID格式不正确，请输入纯数字整数。"
MSG_SHIFT_NOT_FOUND = "该班次不存在，请重新输入。"
MSG_INVALID_DATE_FORMAT = "日期格式不正确，请按 年$月$日 发送，例如：2026$4$12"
MSG_END_BEFORE_START = "终点日期不能早于起点日期，请重新输入终点日期。"
MSG_EXPORT_FAILED = "导出失败，请重新发送 /test_1 后再试。"
MSG_CANCELLED = "已取消"

_DIGITS_ONLY = re.compile(r"^\d+$")


def check_admin_for_export(*, tg_id: int) -> Tuple[bool, Optional[str]]:
    """
    管理员校验。失败时返回 (False, 需回复用户的固定文案)。
    """
    try:
        ok = admin_list_repo.is_admin_by_tg_id(tg_id=int(tg_id))
    except Exception:
        log.exception("admin_export_test: admin check failed tg_id=%s", tg_id)
        return False, MSG_EXPORT_FAILED
    if not ok:
        return False, MSG_NO_PERMISSION
    return True, None


def parse_shift_id_input(*, text: str) -> Tuple[Optional[int], Optional[str]]:
    raw = (text or "").strip()
    if not raw or not _DIGITS_ONLY.match(raw):
        return None, MSG_INVALID_SHIFT_FORMAT
    shift_id = int(raw)
    if shift_id < 0:
        return None, MSG_INVALID_SHIFT_FORMAT
    row = shifts_repo.get_by_id(shift_id)
    if row is None:
        return None, MSG_SHIFT_NOT_FOUND
    return shift_id, None


def parse_ymd_dollar(*, text: str) -> Tuple[Optional[date], Optional[str]]:
    raw = (text or "").strip()
    parts = raw.split("$")
    if len(parts) != 3:
        return None, MSG_INVALID_DATE_FORMAT
    y_s, m_s, d_s = (p.strip() for p in parts)
    if not y_s or not m_s or not d_s:
        return None, MSG_INVALID_DATE_FORMAT
    if not _DIGITS_ONLY.match(y_s) or not _DIGITS_ONLY.match(m_s) or not _DIGITS_ONLY.match(d_s):
        return None, MSG_INVALID_DATE_FORMAT
    try:
        y, m, d = int(y_s), int(m_s), int(d_s)
        dt = date(y, m, d)
    except ValueError:
        return None, MSG_INVALID_DATE_FORMAT
    return dt, None


def format_confirm_message(*, shift_id: int, start_date: date, end_date: date) -> str:
    s = start_date.isoformat()
    e = end_date.isoformat()
    return (
        "请确认您的下载范围：\n\n"
        f"班次：{int(shift_id)}\n"
        f"日期：{s} 至 {e}"
    )


def _csv_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _encode_csv_utf8_sig(*, headers: List[str], rows: List[Tuple]) -> bytes:
    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_csv_cell(v) for v in row])
    body = buf.getvalue().encode("utf-8")
    return codecs.BOM_UTF8 + body


def _range_filename_part(*, start_date: date, end_date: date) -> str:
    return f"{start_date.isoformat()}_to_{end_date.isoformat()}"


def prepare_three_csv_exports(
    *,
    shift_id: int,
    start_date: date,
    end_date: date,
) -> Tuple[Optional[List[Tuple[str, bytes]]], Optional[str]]:
    """
    生成 3 份 CSV（utf-8-sig）。成功返回 ([(filename, bytes), ...], None)；
    失败返回 (None, MSG_EXPORT_FAILED)。
    """
    part = _range_filename_part(start_date=start_date, end_date=end_date)
    sid = int(shift_id)
    try:
        qc_h, qc_r = qc_results_export_repo.fetch_rows_for_export(
            shift_id=sid, start_date=start_date, end_date=end_date
        )
        ar_h, ar_r = audit_results_export_repo.fetch_rows_for_export(
            shift_id=sid, start_date=start_date, end_date=end_date
        )
        el_h, el_r = effective_leave_days_export_repo.fetch_rows_for_export(
            shift_id=sid, start_date=start_date, end_date=end_date
        )
    except Exception:
        log.exception(
            "admin_export_test: DB export query failed shift_id=%s %s..%s",
            shift_id,
            start_date,
            end_date,
        )
        return None, MSG_EXPORT_FAILED

    out: List[Tuple[str, bytes]] = [
        (
            f"qc_results_shift_{sid}_{part}.csv",
            _encode_csv_utf8_sig(headers=qc_h, rows=qc_r),
        ),
        (
            f"audit_results_shift_{sid}_{part}.csv",
            _encode_csv_utf8_sig(headers=ar_h, rows=ar_r),
        ),
        (
            f"effective_leave_days_shift_{sid}_{part}.csv",
            _encode_csv_utf8_sig(headers=el_h, rows=el_r),
        ),
    ]
    return out, None
