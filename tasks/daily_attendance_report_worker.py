from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot

from infra.daily_report_config import load_daily_report_config
from services.daily_attendance_report_send import send_daily_attendance_report

log = logging.getLogger(__name__)


def _seconds_until_next_run(*, tz_name: str, hour: int, minute: int) -> float:
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)
    target = datetime.combine(now_local.date(), time(hour, minute), tzinfo=tz)
    if now_local >= target:
        target += timedelta(days=1)
    return max(1.0, (target - now_local).total_seconds())


async def _send_scheduled_group_checkin_csv(*, bot: Bot) -> None:
    """23:00 定时：发送当日群打卡汇总 CSV（与 HTTP 手动触发为同一文件）。"""
    cfg = load_daily_report_config()
    if not cfg.enabled:
        return

    tz = ZoneInfo(cfg.timezone_name)
    report_date = datetime.now(tz).date()
    outcome = await send_daily_attendance_report(
        bot=bot,
        report_date=report_date,
        force=False,
        record_sent=True,
        cfg=cfg,
    )
    if outcome.skipped_duplicate:
        log.info("group_checkin_csv: already sent for %s, skip", report_date.isoformat())
        return
    if not outcome.ok:
        log.warning("group_checkin_csv: send failed %s", outcome.message)
        return
    log.info(
        "group_checkin_csv: scheduled sent %s rows file=%s tg_id=%s",
        outcome.row_count,
        outcome.filename,
        outcome.notify_tg_id,
    )


async def run_daily_attendance_report_worker(*, bot: Bot) -> None:
    """
    每日定时（默认北京时间 23:00）把群里 clock_records 汇总成 CSV，私聊发给配置账号。
    与 HTTP 接口 POST /api/v1/group-checkin-csv/send 发送的是同一份文件。
    """
    cfg = load_daily_report_config()
    if not cfg.enabled:
        log.info("daily_report: disabled (DAILY_ATTENDANCE_REPORT_ENABLED=false)")
        return

    log.info(
        "daily_report: worker started tz=%s at %02d:%02d notify=%s",
        cfg.timezone_name,
        cfg.report_hour,
        cfg.report_minute,
        cfg.notify_username,
    )

    # 启动后若已过当日 23:00（可配置）且尚未发送，补发一次（避免重启错过）
    tz = ZoneInfo(cfg.timezone_name)
    now_local = datetime.now(tz)
    target_today = datetime.combine(
        now_local.date(),
        time(cfg.report_hour, cfg.report_minute),
        tzinfo=tz,
    )
    if now_local >= target_today:
        try:
            await _send_scheduled_group_checkin_csv(bot=bot)
        except Exception:
            log.exception("daily_report: startup catch-up failed")

    while True:
        cfg = load_daily_report_config()
        if not cfg.enabled:
            await asyncio.sleep(3600)
            continue
        delay = _seconds_until_next_run(
            tz_name=cfg.timezone_name,
            hour=cfg.report_hour,
            minute=cfg.report_minute,
        )
        log.info("daily_report: next run in %.0f sec", delay)
        await asyncio.sleep(delay)
        try:
            await _send_scheduled_group_checkin_csv(bot=bot)
        except Exception:
            log.exception("daily_report: scheduled send failed")
