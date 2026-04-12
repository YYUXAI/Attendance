from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from services import qc_round_closeout_service

log = logging.getLogger(__name__)


async def run_qc_round_closeout_poll(*, bot: Bot, interval_sec: int = 8) -> None:
    while True:
        try:
            await qc_round_closeout_service.run_round_closeout_cycle(bot=bot, limit=20)
        except Exception:
            log.exception("qc_round_closeout_poll cycle failed")
        await asyncio.sleep(interval_sec)
