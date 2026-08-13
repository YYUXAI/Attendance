"""BBQ 群当月考勤同步到 Google 表（格式同私聊导出 XLSX，异常标黄）。"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date

from infra.bbq_google_sheets_config import (
    BbqGoogleSheetsConfig,
    load_bbq_google_sheets_config,
)
from services.attendance_export_service import (
    abnormal_status_cells_in_export_grid,
    build_attendance_export_grid,
    build_pivot_and_overview,
    collect_rows_for_single_group,
    today_in_tz,
)
from services.google_sheets_client import write_attendance_export_to_sheet

log = logging.getLogger(__name__)



@dataclass(frozen=True)
class BbqSheetsSyncResult:
    ok: bool
    message: str
    row_count: int = 0
    sheet_title: str = ""


def _month_range(*, today: date) -> tuple[date, date, str]:
    start = date(today.year, today.month, 1)
    return start, today, "本月"


async def build_bbq_month_export_grid(
    *,
    chat_id: int,
    chat_title: str | None = None,
    timezone: str,
) -> tuple[list[list[object]], list[tuple[int, int]], date, date]:
    """整月 BBQ 群打卡，导出格式同 XLSX（含状态分布 + 异常标黄坐标）。"""
    today = today_in_tz(tz_name=timezone)
    start, end, range_label = _month_range(today=today)
    rows = await collect_rows_for_single_group(
        chat_id=int(chat_id),
        start=start,
        end=end,
    )
    pivot, overview, dates = build_pivot_and_overview(rows=rows, start=start, end=end)
    grid = build_attendance_export_grid(
        pivot=pivot,
        dates=dates,
        overview=overview,
        range_label=range_label,
        include_chart_section=True,
    )
    yellow_cells = abnormal_status_cells_in_export_grid(
        grid=grid,
        pivot=pivot,
        dates=dates,
    )
    return grid, yellow_cells, start, end


async def sync_bbq_group_month_to_google_sheets(
    *,
    chat_id: int,
    chat_title: str | None = None,
    cfg: BbqGoogleSheetsConfig | None = None,
) -> BbqSheetsSyncResult:
    cfg = cfg or load_bbq_google_sheets_config()
    if not cfg.enabled:
        return BbqSheetsSyncResult(False, "BBQ_GOOGLE_SHEETS_ENABLED=false")
    if not cfg.spreadsheet_id:
        return BbqSheetsSyncResult(False, "缺少 BBQ_GOOGLE_SHEETS_SPREADSHEET_ID")
    if not cfg.sheet_title:
        return BbqSheetsSyncResult(False, "缺少 BBQ_GOOGLE_SHEETS_SHEET_TITLE")
    from infra.bbq_google_sheets_config import is_bbq_attendance_summary_chat

    if not is_bbq_attendance_summary_chat(chat_id=chat_id, chat_title=chat_title):
        return BbqSheetsSyncResult(False, f"chat_id={chat_id} 非 BBQ 群，跳过")

    grid, yellow_cells, start, end = await build_bbq_month_export_grid(
        chat_id=int(chat_id),
        timezone=cfg.timezone,
    )
    try:
        sheet_title, row_count, _cols = await asyncio.to_thread(
            write_attendance_export_to_sheet,
            spreadsheet_id=cfg.spreadsheet_id,
            credentials_json=cfg.credentials_json,
            sheet_title=cfg.sheet_title,
            values=grid,
            yellow_cells=yellow_cells,
        )
    except Exception as error:
        log.error(
            "bbq_sheets: sync failed",
            extra={"error_type": type(error).__name__},
        )
        return BbqSheetsSyncResult(False, "Google 表写入失败")

    msg = (
        f"已同步 BBQ 群 {start}~{end} 共 {row_count} 行 "
        f"（异常标黄 {len(yellow_cells)} 格）"
    )
    log.info("bbq_sheets: %s chat_id=%s", msg, chat_id)
    return BbqSheetsSyncResult(True, msg, row_count=row_count)
