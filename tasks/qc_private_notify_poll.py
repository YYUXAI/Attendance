from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from services import qc_private_notify_service

log = logging.getLogger(__name__)


async def run_qc_private_notify_poll(*, bot: Bot, interval_sec: int = 5) -> None:
    while True:
        try:
            await qc_private_notify_service.run_first_private_notify_cycle(bot=bot, limit=50)
        except Exception:
            log.exception("qc_private_notify_poll cycle failed")
        await asyncio.sleep(interval_sec)
