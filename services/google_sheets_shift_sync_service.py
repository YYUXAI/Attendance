from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, time

from domain.world_cup_shift_codes import (
    ShiftCodeRange,
    default_shift_catalog,
    lookup_shift,
    merge_legend_from_sheet_rows,
)
from infra.google_sheets_config import GoogleSheetsConfig, load_google_sheets_config
from repositories import employee_shift_calendar_repo, employee_shift_config_repo
from services.google_sheets_client import fetch_sheet_values

log = logging.getLogger(__name__)

_EMP_ID_RE = re.compile(r"^\d{4,8}$")
_REST_MARKERS = ("▲", "△", "休", "月休")
_GROUP_ROW_HINTS = ("组", "Group", "GROUP", "部门", "UX设计")
_SHIFT_CODE_RE = re.compile(r"^W[A-Z]$")


@dataclass(frozen=True)
class ParsedEmployee:
    employee_id: str
    english_name: str
    chinese_name: str
    primary_code: str
    checkin: time
    checkout: time
    shift_time_range: str
    monthly_rest_days: str
    daily: dict[int, str]


@dataclass(frozen=True)
class SyncResult:
    ok: bool
    message: str
    year_month: str
    employee_count: int
    calendar_cells: int
    sheet_title: str = ""


def _norm_cell(v: object) -> str:
    return str(v or "").strip()


def _is_rest_cell(cell: str) -> bool:
    c = _norm_cell(cell)
    if not c:
        return False
    if c in _REST_MARKERS:
        return True
    return any(m in c for m in _REST_MARKERS)


def _extract_shift_code(cell: str) -> str:
    c = _norm_cell(cell).upper()
    if not c or _is_rest_cell(c):
        return ""
    if _SHIFT_CODE_RE.fullmatch(c):
        return c
    m = re.search(r"\bW[A-Z]\b", c)
    return m.group(0) if m else ""


def _find_header_row(rows: list[list[str]]) -> int | None:
    for idx, row in enumerate(rows):
        joined = " ".join(_norm_cell(c) for c in row)
        if "工号" in joined and ("名字" in joined or "姓名" in joined or "英文名" in joined):
            return idx
    return None


def _find_col(row: list[str], *keywords: str) -> int | None:
    for i, cell in enumerate(row):
        text = _norm_cell(cell)
        if any(k in text for k in keywords):
            return i
    return None


def _parse_day_columns(date_row: list[str]) -> dict[int, int]:
    out: dict[int, int] = {}
    for col, cell in enumerate(date_row):
        text = _norm_cell(cell)
        if not text.isdigit():
            continue
        day = int(text)
        if 1 <= day <= 31:
            out[day] = col
    return out


def _is_group_row(row: list[str], *, emp_col: int | None) -> bool:
    cells = [_norm_cell(c) for c in row if _norm_cell(c)]
    if not cells:
        return True
    joined = " ".join(cells)
    emp_val = ""
    if emp_col is not None and emp_col < len(row):
        emp_val = _norm_cell(row[emp_col])
    if any(h in joined for h in _GROUP_ROW_HINTS) and not emp_val:
        return True
    if len(cells) == 1 and not _EMP_ID_RE.fullmatch(cells[0]):
        return True
    return False


def _pick_primary_code(daily: dict[int, str]) -> str:
    codes = [_extract_shift_code(v) for v in daily.values()]
    codes = [c for c in codes if c]
    if not codes:
        return ""
    return Counter(codes).most_common(1)[0][0]


def parse_shift_matrix(
    rows: list[list[str]],
    *,
    year_month: str,
) -> tuple[dict[str, ShiftCodeRange], list[ParsedEmployee]]:
    catalog = merge_legend_from_sheet_rows(rows, base=default_shift_catalog())
    header_idx = _find_header_row(rows)
    if header_idx is None:
        raise ValueError("未找到含「工号」的表头行")
    header = rows[header_idx]
    date_idx = header_idx + 1
    if date_idx >= len(rows):
        raise ValueError("表头下一行缺少日期行")
    day_cols = _parse_day_columns(rows[date_idx])
    if not day_cols:
        raise ValueError("未解析到 1–31 日列")

    emp_col = _find_col(header, "工号")
    name_col = _find_col(header, "名字", "姓名", "英文名")
    cn_col = _find_col(header, "中文", "昵称")

    employees: list[ParsedEmployee] = []
    for row in rows[date_idx + 1 :]:
        if _is_group_row(row, emp_col=emp_col):
            continue
        if emp_col is None or emp_col >= len(row):
            continue
        emp_id = _norm_cell(row[emp_col])
        if not _EMP_ID_RE.fullmatch(emp_id):
            continue

        english = _norm_cell(row[name_col]) if name_col is not None and name_col < len(row) else ""
        chinese = _norm_cell(row[cn_col]) if cn_col is not None and cn_col < len(row) else ""

        daily: dict[int, str] = {}
        rest_days: list[int] = []
        for day, col in day_cols.items():
            cell = _norm_cell(row[col]) if col < len(row) else ""
            daily[day] = cell
            if _is_rest_cell(cell):
                rest_days.append(day)

        primary = _pick_primary_code(daily)
        shift = lookup_shift(primary, catalog)
        if not shift:
            log.warning("google_sheets: skip %s — no shift code in row", emp_id)
            continue

        employees.append(
            ParsedEmployee(
                employee_id=emp_id,
                english_name=english,
                chinese_name=chinese,
                primary_code=primary,
                checkin=shift.checkin,
                checkout=shift.checkout,
                shift_time_range=shift.time_range_display,
                monthly_rest_days=",".join(str(d) for d in sorted(rest_days)),
                daily=daily,
            )
        )

    if not employees:
        raise ValueError(f"未解析到有效员工行（year_month={year_month}）")
    return catalog, employees


def _cell_kind(cell: str, code: str) -> str:
    c = _norm_cell(cell)
    if _is_rest_cell(c):
        return "rest"
    if "出差" in c:
        return "trip"
    if "※" in c or "签证" in c:
        return "visa"
    if code:
        return "shift"
    return "empty"


def _work_date(year_month: str, day: int) -> date:
    y, m = year_month.split("-", 1)
    return date(int(y), int(m), day)


def _calendar_rows(emp: ParsedEmployee, *, year_month: str) -> list[tuple[str, date, str, str, str]]:
    out: list[tuple[str, date, str, str, str]] = []
    for day, cell in emp.daily.items():
        code = _extract_shift_code(cell)
        kind = _cell_kind(cell, code)
        out.append((emp.employee_id, _work_date(year_month, day), cell, code, kind))
    return out


def sync_shifts_from_google_sheets(
    *,
    cfg: GoogleSheetsConfig | None = None,
    year_month: str | None = None,
) -> SyncResult:
    cfg = cfg or load_google_sheets_config()
    ym = (year_month or cfg.year_month or "").strip()
    if not cfg.enabled:
        return SyncResult(False, "GOOGLE_SHEETS_ENABLED=false", ym, 0, 0)
    if not cfg.spreadsheet_id:
        return SyncResult(False, "缺少 GOOGLE_SHEETS_SPREADSHEET_ID", ym, 0, 0)
    if not ym or not re.fullmatch(r"\d{4}-\d{2}", ym):
        return SyncResult(False, "缺少或无效 GOOGLE_SHEETS_YEAR_MONTH", ym, 0, 0)

    try:
        sheet_title, rows = fetch_sheet_values(
            spreadsheet_id=cfg.spreadsheet_id,
            credentials_json=cfg.credentials_json,
            sheet_gid=cfg.sheet_gid,
        )
        _, employees = parse_shift_matrix(rows, year_month=ym)
    except Exception as e:
        log.exception("google_sheets sync failed")
        return SyncResult(False, str(e), ym, 0, 0)

    employee_shift_config_repo.ensure_table()
    employee_shift_calendar_repo.ensure_table()
    emp_ids: list[str] = []
    calendar_count = 0
    for emp in employees:
        english = emp.english_name or emp.chinese_name or emp.employee_id
        employee_shift_config_repo.upsert_config(
            year_month=ym,
            employee_id=emp.employee_id,
            english_name=english,
            shift_time_range=emp.shift_time_range,
            shift_checkin_time=emp.checkin,
            shift_checkout_time=emp.checkout,
            monthly_rest_days=emp.monthly_rest_days,
        )
        emp_ids.append(emp.employee_id)
        calendar_count += employee_shift_calendar_repo.upsert_many(
            year_month=ym,
            rows=_calendar_rows(emp, year_month=ym),
        )

    employee_shift_config_repo.delete_not_in(year_month=ym, employee_ids=emp_ids)
    employee_shift_calendar_repo.delete_not_in(year_month=ym, employee_ids=emp_ids)

    msg = f"同步成功：{len(employees)} 人、{calendar_count} 格"
    log.info("google_sheets: %s (%s)", msg, sheet_title)
    return SyncResult(
        ok=True,
        message=msg,
        year_month=ym,
        employee_count=len(employees),
        calendar_cells=calendar_count,
        sheet_title=sheet_title,
    )
