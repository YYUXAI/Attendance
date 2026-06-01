from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, time
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import BufferedInputFile

from services import group_attendance_summary_service

log = logging.getLogger(__name__)


def _hour_min() -> tuple[int, int]:
    raw = (os.getenv("GROUP_DAILY_SUMMARY_TIME") or "23:00").strip()
    try:
        hh, mm = raw.split(":", 1)
        h = max(0, min(int(hh), 23))
        m = max(0, min(int(mm), 59))
        return h, m
    except Exception:
        return 23, 0


def _tz() -> str:
    return (os.getenv("GROUP_DAILY_SUMMARY_TZ") or "Asia/Shanghai").strip() or "Asia/Shanghai"


def _seconds_to_next() -> float:
    h, m = _hour_min()
    tz = ZoneInfo(_tz())
    now = datetime.now(tz)
    tgt = datetime.combine(now.date(), time(h, m), tzinfo=tz)
    if now >= tgt:
        from datetime import timedelta

        tgt += timedelta(days=1)
    return max(1.0, (tgt - now).total_seconds())


async def run_group_daily_summary_worker(*, bot: Bot) -> None:
    group_attendance_summary_service.ensure_tables()
    log.info("group_summary: worker started at %s %s", _tz(), _hour_min())
    while True:
        delay = _seconds_to_next()
        await asyncio.sleep(delay)
        try:
            tz = ZoneInfo(_tz())
            d = datetime.now(tz).date()
            for gid in group_attendance_summary_service.list_attendance_group_ids():
                gname = await group_attendance_summary_service.resolve_group_display_name(
                    bot=bot, chat_id=int(gid)
                )
                rows = group_attendance_summary_service.build_rows_for_group(
                    chat_id=int(gid),
                    target_date=d,
                    group_name=gname,
                )
                if not rows:
                    continue
                text = group_attendance_summary_service.summarize_text(rows=rows, target_date=d)
                csv_body = group_attendance_summary_service.encode_csv(rows=rows)
                await bot.send_message(chat_id=int(gid), text=text)
                await bot.send_document(
                    chat_id=int(gid),
                    document=BufferedInputFile(file=csv_body, filename=f"group_{gid}_{d.isoformat()}.csv"),
                    caption=f"本群当日打卡明细 {d.isoformat()}",
                )
                log.info("group_summary: sent gid=%s rows=%s", gid, len(rows))
        except Exception:
            log.exception("group_summary cycle failed")
