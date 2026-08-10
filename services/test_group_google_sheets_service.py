"""测试群：从 Google 班表同步班次；打卡后回写 Google 表（每日单元格：上班卡/下班卡）。"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date

from infra.test_group_google_config import (
    ConfiguredTestGroupGoogleConfig,
    is_test_group_chat,
    load_test_group_google_config,
    primary_test_group_chat_id,
)
from repositories import (
    employee_shift_calendar_repo,
    employee_shift_config_repo,
    employee_shift_roster_repo,
)
from services.attendance_export_service import (
    build_attendance_export_grid,
    build_pivot_and_overview,
    collect_rows_for_roster_at_chat,
    today_in_tz,
)
from services.google_sheets_client import ensure_sheet_tab, fetch_sheet_values, replace_sheet_values
from services.google_sheets_punch_export import (
    overview_for_punch_status,
    pivot_with_punch_status,
)
from services.google_sheets_shift_sync_service import (
    _upsert_employees,
    parse_shift_matrix,
)

log = logging.getLogger(__name__)

_ROSTER_SOURCE = "test_group"

@dataclass(frozen=True)
class ConfiguredTestGroupSheetsSyncResult:
    ok: bool
    message: str
    row_count: int = 0
    sheet_title: str = ""


def _month_range(*, today: date) -> tuple[date, date, str]:
    start = date(today.year, today.month, 1)
    return start, today, "本月"


async def build_test_group_month_export_grid(
    *,
    timezone: str,
    cfg: ConfiguredTestGroupGoogleConfig | None = None,
) -> tuple[list[list[object]], date, date]:
    """按 Google 班表 roster 全员统计；打卡仅取自测试群（上班卡/下班卡，月休保留）。"""
    cfg = cfg or load_test_group_google_config()
    attendance_chat_id = primary_test_group_chat_id()
    today = today_in_tz(tz_name=timezone)
    start, end, range_label = _month_range(today=today)
    year_month = start.strftime("%Y-%m")

    shift_sync = sync_test_group_shifts_from_google(cfg=cfg, year_month=year_month)
    if not shift_sync.ok:
        log.warning(
            "test_group_sheets: 班表同步失败，使用本地 roster：%s",
            shift_sync.message,
        )

    roster_ids = employee_shift_roster_repo.roster_set(
        year_month=year_month,
        source=_ROSTER_SOURCE,
    )
    rows = await collect_rows_for_roster_at_chat(
        chat_id=attendance_chat_id,
        start=start,
        end=end,
        roster_ids=roster_ids,
    )
    pivot, _overview, dates = build_pivot_and_overview(rows=rows, start=start, end=end)
    pivot = pivot_with_punch_status(
        pivot=pivot,
        dates=dates,
        chat_id=attendance_chat_id,
        tz_name=timezone,
    )
    overview = overview_for_punch_status(pivot=pivot, dates=dates)
    grid = build_attendance_export_grid(
        pivot=pivot,
        dates=dates,
        overview=overview,
        range_label=range_label,
        include_chart_section=False,
    )
    return grid, start, end

def sync_test_group_shifts_from_google(
    *,
    cfg: ConfiguredTestGroupGoogleConfig | None = None,
    year_month: str | None = None,
) -> ConfiguredTestGroupSheetsSyncResult:
    """从班表来源 Google 表读入班次 → 系统数据库。"""
    cfg = cfg or load_test_group_google_config()
    if not cfg.enabled:
        return ConfiguredTestGroupSheetsSyncResult(False, "TEST_GROUP_GOOGLE_SHEETS_ENABLED=false")
    if not cfg.shift_spreadsheet_id:
        return ConfiguredTestGroupSheetsSyncResult(False, "缺少 TEST_GROUP_SHIFT_SPREADSHEET_ID")
    ym = (year_month or "").strip()
    if not ym:
        from infra.google_sheets_config import load_google_sheets_config

        ym = load_google_sheets_config().year_month
    if not ym:
        return ConfiguredTestGroupSheetsSyncResult(False, "缺少 year_month")

    try:
        sheet_title, rows = fetch_sheet_values(
            spreadsheet_id=cfg.shift_spreadsheet_id,
            credentials_json=cfg.credentials_json,
            sheet_gid=cfg.shift_sheet_gid,
        )
        _, employees = parse_shift_matrix(rows, year_month=ym)
    except Exception as exc:
        log.exception("test_group_sheets: shift fetch failed")
        return ConfiguredTestGroupSheetsSyncResult(False, str(exc))

    if not employees:
        return ConfiguredTestGroupSheetsSyncResult(False, "测试群班表未解析到员工")

    emp_ids = [e.employee_id for e in employees]
    employee_shift_config_repo.ensure_table()
    employee_shift_calendar_repo.ensure_table()
    employee_shift_roster_repo.ensure_table()
    employee_shift_roster_repo.set_roster(
        year_month=ym,
        source=_ROSTER_SOURCE,
        employee_ids=emp_ids,
    )
    # 已在统筹主表 / MGZ 班表 roster 的员工，班次与月休以 ▲ 标注的正式表为准，测试群表仅作考勤 roster。
    authoritative_ids = (
        employee_shift_roster_repo.roster_set(year_month=ym, source="main")
        | employee_shift_roster_repo.roster_set(year_month=ym, source="alt")
    )
    to_upsert = [e for e in employees if e.employee_id not in authoritative_ids]
    skipped = sorted(e.employee_id for e in employees if e.employee_id in authoritative_ids)
    if skipped:
        log.info(
            "test_group_sheets: skip shift upsert for %s (main/alt roster authoritative)",
            ",".join(skipped),
        )
    count, cells = _upsert_employees(to_upsert, year_month=ym)
    msg = f"测试群班表同步：{count} 人、{cells} 格（{sheet_title}）"
    log.info("test_group_sheets: %s", msg)
    return ConfiguredTestGroupSheetsSyncResult(True, msg, row_count=count, sheet_title=sheet_title)


async def sync_test_group_month_to_google_sheets(
    *,
    chat_id: int,
    cfg: ConfiguredTestGroupGoogleConfig | None = None,
) -> ConfiguredTestGroupSheetsSyncResult:
    """测试群当月考勤 → Google 表（格式同私聊导出 XLSX）。"""
    cfg = cfg or load_test_group_google_config()
    if not cfg.enabled:
        return ConfiguredTestGroupSheetsSyncResult(False, "TEST_GROUP_GOOGLE_SHEETS_ENABLED=false")
    if not cfg.attendance_spreadsheet_id:
        return ConfiguredTestGroupSheetsSyncResult(False, "缺少 TEST_GROUP_ATTENDANCE_SPREADSHEET_ID")
    if not is_test_group_chat(chat_id=int(chat_id)):
        return ConfiguredTestGroupSheetsSyncResult(False, f"chat_id={chat_id} 非测试群，跳过")

    grid, start, end = await build_test_group_month_export_grid(
        timezone=cfg.timezone,
        cfg=cfg,
    )
    try:
        tab_title = (cfg.attendance_sheet_title or "测试群").strip()
        await asyncio.to_thread(
            ensure_sheet_tab,
            spreadsheet_id=cfg.attendance_spreadsheet_id,
            credentials_json=cfg.credentials_json,
            sheet_title=tab_title,
        )
        sheet_title, row_count = await asyncio.to_thread(
            replace_sheet_values,
            spreadsheet_id=cfg.attendance_spreadsheet_id,
            credentials_json=cfg.credentials_json,
            values=grid,
            sheet_title=tab_title,
        )
    except Exception as exc:
        log.exception(
            "test_group_sheets: export sync failed chat_id=%s spreadsheet=%s",
            chat_id,
            cfg.attendance_spreadsheet_id,
        )
        return ConfiguredTestGroupSheetsSyncResult(False, f"Google 表写入失败: {exc}")

    msg = f"已同步测试群 {start}~{end} 共 {row_count} 行到 {sheet_title!r}（上班卡/下班卡）"
    log.info("test_group_sheets: %s chat_id=%s", msg, chat_id)
    return ConfiguredTestGroupSheetsSyncResult(True, msg, row_count=row_count, sheet_title=sheet_title)
