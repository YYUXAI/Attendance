from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from services import qc_shift_summary_service

log = logging.getLogger(__name__)


async def run_qc_shift_summary_poll(*, bot: Bot, interval_sec: int = 12) -> None:
    _ = bot
    while True:
        try:
            qc_shift_summary_service.run_shift_summary_cycle()
        except Exception:
            log.exception("qc_shift_summary_poll cycle failed")
        await asyncio.sleep(interval_sec)
