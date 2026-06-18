from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from services import approval_service

log = logging.getLogger(__name__)


async def run_approval_dispatch_poll(*, bot: Bot, interval_sec: int = 60) -> None:
    while True:
        try:
            await approval_service.run_pending_dispatch_poll(bot=bot)
        except Exception:
            log.exception("approval_poll cycle failed")
        await asyncio.sleep(interval_sec)
