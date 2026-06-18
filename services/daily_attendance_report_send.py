from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import BufferedInputFile

from infra.daily_report_config import DailyReportConfig, load_daily_report_config
from repositories import event_logs_repo
from services import daily_attendance_report_service as report_svc

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DailyReportSendOutcome:
    ok: bool
    message: str
    report_date: str
    row_count: int
    filename: str
    notify_tg_id: Optional[int]
    skipped_duplicate: bool = False


def parse_report_date_arg(value: str | None, *, tz_name: str) -> date:
    if value is None or not str(value).strip():
        return datetime.now(ZoneInfo(tz_name)).date()
    raw = str(value).strip()
    try:
        return date.fromisoformat(raw)
    except ValueError as e:
        raise ValueError(f"invalid date {raw!r}, use YYYY-MM-DD") from e


async def send_daily_attendance_report(
    *,
    bot: Bot,
    report_date: date | None = None,
    notify_tg_id: int | None = None,
    force: bool = False,
    record_sent: bool = False,
    cfg: DailyReportConfig | None = None,
) -> DailyReportSendOutcome:
    """
    从 clock_records 生成群打卡汇总 CSV，私聊发送（与每天 23:00 定时为同一文件）。

    - force=False：当日已发送过则跳过（23:00 定时用）
    - force=True：随时可再发（HTTP 手动触发默认）
    - record_sent=True：记入 event_logs，避免 23:00 再发一遍
    """
    cfg = cfg or load_daily_report_config()
    tz_name = cfg.timezone_name
    report_date = report_date or datetime.now(ZoneInfo(tz_name)).date()
    day_key = report_svc.report_day_key(report_calendar_date=report_date)

    if not force and event_logs_repo.daily_report_already_sent(report_day_key=day_key):
        log.info("daily_report: already sent for %s, skip", report_date.isoformat())
        return DailyReportSendOutcome(
            ok=True,
            message="当日群打卡 CSV 已发送过，已跳过",
            report_date=report_date.isoformat(),
            row_count=0,
            filename="",
            notify_tg_id=notify_tg_id,
            skipped_duplicate=True,
        )

    target_tg_id = notify_tg_id
    if target_tg_id is None:
        target_tg_id = report_svc.resolve_notify_tg_id(cfg)
    if target_tg_id is None:
        return DailyReportSendOutcome(
            ok=False,
            message="无法解析接收人 tg_id，请配置 NOTIFY_TG_ID 或注册用户名",
            report_date=report_date.isoformat(),
            row_count=0,
            filename="",
            notify_tg_id=None,
        )

    body, filename, rows = report_svc.build_report_for_calendar_date(
        report_calendar_date=report_date,
        tz_name=tz_name,
    )
    caption = (
        f"群打卡汇总 {report_date.isoformat()}\n"
        f"共 {len(rows)} 人有打卡记录\n"
        f"时区：{tz_name}"
    )
    doc = BufferedInputFile(file=body, filename=filename)
    await bot.send_document(chat_id=int(target_tg_id), document=doc, caption=caption)

    if record_sent:
        event_logs_repo.mark_daily_report_sent(
            report_day_key=day_key,
            created_at_utc=datetime.now(timezone.utc),
        )

    log.info(
        "daily_report: sent %s rows to tg_id=%s file=%s force=%s record_sent=%s",
        len(rows),
        target_tg_id,
        filename,
        force,
        record_sent,
    )
    return DailyReportSendOutcome(
        ok=True,
        message="已发送",
        report_date=report_date.isoformat(),
        row_count=len(rows),
        filename=filename,
        notify_tg_id=int(target_tg_id),
        skipped_duplicate=False,
    )


def outcome_to_json(outcome: DailyReportSendOutcome) -> dict[str, Any]:
    return {
        "ok": outcome.ok,
        "message": outcome.message,
        "report_date": outcome.report_date,
        "row_count": outcome.row_count,
        "filename": outcome.filename,
        "notify_tg_id": outcome.notify_tg_id,
        "skipped_duplicate": outcome.skipped_duplicate,
    }
