from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date, time

from domain.employee_region import normalize_region_code, timezone_for_region
from domain.world_cup_shift_codes import (
    ShiftCodeRange,
    default_shift_catalog,
    lookup_shift,
    merge_legend_from_sheet_rows,
)
from infra.bbq_google_sheets_config import bbq_summary_excluded_employee_ids
from infra.google_sheets_alt_config import GoogleSheetsAltConfig, load_google_sheets_alt_config
from infra.google_sheets_config import GoogleSheetsConfig, load_google_sheets_config
from infra.test_group_google_config import load_test_group_google_config
from repositories import (
    employee_shift_calendar_repo,
    employee_shift_config_repo,
    employee_shift_roster_repo,
    registrations_repo,
)
from services.google_sheets_client import fetch_sheet_values

log = logging.getLogger(__name__)

_EMP_ID_RE = re.compile(r"^\d{3,8}$")
_REST_MARKERS = ("▲", "△", "休", "月休")
_GROUP_ROW_HINTS = ("组", "Group", "GROUP", "部门", "UX设计", "总计")
_SHIFT_CODE_RE = re.compile(r"^W[A-Z]$")
_SINGLE_SHIFT_CODE_RE = re.compile(r"^[A-Z]$")


_MAIN_EXPORT_SHEET_TEAM = "UX设计组"


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
    region_code: str = ""
    shift_timezone: str = ""
    sheet_team_group: str = ""


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
    if m:
        return m.group(0)
    if _SINGLE_SHIFT_CODE_RE.fullmatch(c):
        return c
    return ""


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
    if "总计" in joined:
        return True
    if any(h in joined for h in _GROUP_ROW_HINTS) and not emp_val:
        return True
    if len(cells) == 1 and not _EMP_ID_RE.fullmatch(cells[0]):
        return True
    return False


def _extract_team_group_name(row: list[str]) -> str:
    for cell in row:
        text = _norm_cell(cell)
        if not text or "总计" in text:
            continue
        if "组" in text:
            return text
    return ""


def main_export_roster_employee_ids(
    employees: list[ParsedEmployee],
    *,
    excluded_employee_ids: frozenset[str] = frozenset(),
) -> list[str]:
    """主表导出/开班 roster：默认仅 UX设计组（排除夏荷组等）。"""
    ux = [emp.employee_id for emp in employees if emp.sheet_team_group == _MAIN_EXPORT_SHEET_TEAM]
    ids = ux if ux else [emp.employee_id for emp in employees]
    return [eid for eid in ids if eid not in excluded_employee_ids]


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
    region_col = _find_col(header, "地区")

    employees: list[ParsedEmployee] = []
    current_team = ""
    for row in rows[date_idx + 1 :]:
        if _is_group_row(row, emp_col=emp_col):
            team = _extract_team_group_name(row)
            if team:
                current_team = team
            continue
        if emp_col is None or emp_col >= len(row):
            continue
        emp_id = _norm_cell(row[emp_col])
        if not _EMP_ID_RE.fullmatch(emp_id):
            continue

        english = _norm_cell(row[name_col]) if name_col is not None and name_col < len(row) else ""
        chinese = _norm_cell(row[cn_col]) if cn_col is not None and cn_col < len(row) else ""
        region_raw = _norm_cell(row[region_col]) if region_col is not None and region_col < len(row) else ""
        region_code = normalize_region_code(region_raw)
        shift_timezone = timezone_for_region(region_code) if region_code else ""

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
                region_code=region_code,
                shift_timezone=shift_timezone,
                sheet_team_group=current_team,
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


def _upsert_employees(
    employees: list[ParsedEmployee],
    *,
    year_month: str,
) -> tuple[int, int]:
    calendar_count = 0
    for emp in employees:
        english = emp.english_name or emp.chinese_name or emp.employee_id
        employee_shift_config_repo.upsert_config(
            year_month=year_month,
            employee_id=emp.employee_id,
            english_name=english,
            shift_time_range=emp.shift_time_range,
            shift_checkin_time=emp.checkin,
            shift_checkout_time=emp.checkout,
            monthly_rest_days=emp.monthly_rest_days,
            region_code=emp.region_code,
            shift_timezone=emp.shift_timezone,
        )
        calendar_count += employee_shift_calendar_repo.upsert_many(
            year_month=year_month,
            rows=_calendar_rows(emp, year_month=year_month),
        )
    return len(employees), calendar_count


def _mirror_employee_schedule(
    *,
    year_month: str,
    source_employee_id: str,
    target_employee_id: str,
    target_english_name: str | None = None,
) -> None:
    src_cfg = employee_shift_config_repo.get_by_employee_id(
        year_month=year_month,
        employee_id=str(source_employee_id),
    )
    if not src_cfg:
        log.warning(
            "google_sheets: mirror skip %s -> %s (source missing)",
            source_employee_id,
            target_employee_id,
        )
        return
    english = (target_english_name or src_cfg.english_name or target_employee_id).strip()
    employee_shift_config_repo.upsert_config(
        year_month=year_month,
        employee_id=str(target_employee_id),
        english_name=english,
        shift_time_range=src_cfg.shift_time_range,
        shift_checkin_time=src_cfg.shift_checkin_time,
        shift_checkout_time=src_cfg.shift_checkout_time,
        monthly_rest_days=src_cfg.monthly_rest_days,
        region_code=src_cfg.region_code,
        shift_timezone=src_cfg.shift_timezone,
    )
    cal_rows = employee_shift_calendar_repo.list_for_month(
        year_month=year_month,
        employee_ids=[str(source_employee_id)],
    )
    employee_shift_calendar_repo.upsert_many(
        year_month=year_month,
        rows=[
            (str(target_employee_id), r.work_date, r.cell_raw, r.shift_code, r.cell_kind)
            for r in cal_rows
        ],
    )
    log.info(
        "google_sheets: mirrored schedule %s -> %s (%s cells)",
        source_employee_id,
        target_employee_id,
        len(cal_rows),
    )


def shift_sheet_title_candidates(*, year_month: str, source: str) -> list[str]:
    """按 year_month 推断 Google 班表 tab 名称。"""
    y, m = year_month.split("-")
    month = int(m)
    if source == "main":
        return [f"排班 {year_month}"]
    if source == "alt":
        return [f"{y}年{month}月排班表", f"{y}年{m}月排班表"]
    return []


def fetch_shift_matrix_sheet(
    *,
    spreadsheet_id: str,
    credentials_json: str,
    year_month: str,
    source: str,
    fallback_gid: int | None = None,
) -> tuple[str, list[list[str]]]:
    """优先按月份 tab 名读取；找不到时回退到配置的 gid。"""
    candidates = shift_sheet_title_candidates(year_month=year_month, source=source)
    last_err: Exception | None = None
    for title in candidates:
        try:
            return fetch_sheet_values(
                spreadsheet_id=spreadsheet_id,
                credentials_json=credentials_json,
                sheet_title=title,
            )
        except Exception as exc:
            last_err = exc
    if fallback_gid is not None:
        return fetch_sheet_values(
            spreadsheet_id=spreadsheet_id,
            credentials_json=credentials_json,
            sheet_gid=fallback_gid,
        )
    hint = "、".join(candidates) or source
    raise ValueError(f"未找到 {year_month} 班表 tab（{hint}）") from last_err


def _sync_alt_sheet_employees(
    *,
    alt_cfg: GoogleSheetsAltConfig,
    year_month: str,
) -> tuple[int, int, str, list[str]]:
    if not alt_cfg.spreadsheet_id:
        return 0, 0, "", []
    sheet_title, rows = fetch_shift_matrix_sheet(
        spreadsheet_id=alt_cfg.spreadsheet_id,
        credentials_json=alt_cfg.credentials_json,
        year_month=year_month,
        source="alt",
        fallback_gid=alt_cfg.sheet_gid,
    )
    _, employees = parse_shift_matrix(rows, year_month=year_month)
    if not employees:
        raise ValueError("备用 Google 表未解析到有效员工")
    alt_ids = [emp.employee_id for emp in employees]
    count, cells = _upsert_employees(employees, year_month=year_month)
    alt_ids = list(alt_ids)
    for dst, src in alt_cfg.mirror_from_to.items():
        reg = registrations_repo.get_by_employee_id(str(dst))
        reg_name = (reg.english_name or "").strip() if reg else None
        _mirror_employee_schedule(
            year_month=year_month,
            source_employee_id=src,
            target_employee_id=dst,
            target_english_name=reg_name,
        )
    employee_shift_roster_repo.set_roster(
        year_month=year_month,
        source="alt",
        employee_ids=alt_ids,
    )
    return count, cells, sheet_title, alt_ids


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
        sheet_title, rows = fetch_shift_matrix_sheet(
            spreadsheet_id=cfg.spreadsheet_id,
            credentials_json=cfg.credentials_json,
            year_month=ym,
            source="main",
            fallback_gid=cfg.sheet_gid,
        )
        _, employees = parse_shift_matrix(rows, year_month=ym)
    except Exception as error:
        log.error("google_sheets sync failed", extra={"error_type": type(error).__name__})
        return SyncResult(False, "configured Sheet sync failed", ym, 0, 0)

    employee_shift_config_repo.ensure_table()
    employee_shift_calendar_repo.ensure_table()
    employee_shift_roster_repo.ensure_table()
    emp_ids = [emp.employee_id for emp in employees]
    export_roster_ids = main_export_roster_employee_ids(
        employees,
        excluded_employee_ids=bbq_summary_excluded_employee_ids(),
    )
    employee_shift_roster_repo.set_roster(
        year_month=ym,
        source="main",
        employee_ids=export_roster_ids,
    )
    calendar_count = _upsert_employees(employees, year_month=ym)[1]

    alt_cfg = load_google_sheets_alt_config()
    alt_roster_ids: list[str] = []
    alt_msg = ""
    if alt_cfg:
        try:
            alt_count, alt_cells, _alt_title, alt_roster_ids = _sync_alt_sheet_employees(
                alt_cfg=alt_cfg,
                year_month=ym,
            )
            if alt_count:
                alt_msg = f"；alt roster {alt_count} 人、{alt_cells} 格"
        except Exception as error:
            log.error("google_sheets alt sync failed", extra={"error_type": type(error).__name__})
            return SyncResult(False, "主表成功但 alt roster Sheet 失败", ym, len(employees), calendar_count)
    else:
        alt_roster_ids = employee_shift_roster_repo.list_roster(year_month=ym, source="alt")

    test_roster_ids: list[str] = []
    test_msg = ""
    test_cfg = load_test_group_google_config()
    if test_cfg.enabled and test_cfg.shift_spreadsheet_id:
        try:
            from services.test_group_google_sheets_service import sync_test_group_shifts_from_google

            test_result = sync_test_group_shifts_from_google(cfg=test_cfg, year_month=ym)
            if test_result.ok:
                test_roster_ids = employee_shift_roster_repo.list_roster(
                    year_month=ym, source="test_group"
                )
                test_msg = f"；{test_result.message}"
            else:
                log.warning("google_sheets: test group shift sync: %s", test_result.message)
        except Exception as error:
            log.error("google_sheets test group shift sync failed", extra={"error_type": type(error).__name__})
            return SyncResult(False, "主表成功但测试群班表失败", ym, len(employees), calendar_count)

    protected = set(alt_roster_ids) | set(test_roster_ids)
    if alt_cfg:
        protected |= set(alt_cfg.mirror_from_to.keys())
    keep_ids = list(set(emp_ids) | protected)
    employee_shift_config_repo.delete_not_in(year_month=ym, employee_ids=keep_ids)
    employee_shift_calendar_repo.delete_not_in(year_month=ym, employee_ids=keep_ids)

    msg = f"同步成功：{len(employees)} 人、{calendar_count} 格{alt_msg}{test_msg}"
    log.info("google_sheets: %s", msg)
    return SyncResult(
        ok=True,
        message=msg,
        year_month=ym,
        employee_count=len(employees),
        calendar_cells=calendar_count,
        sheet_title=sheet_title,
    )
