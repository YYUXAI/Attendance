from __future__ import annotations

import asyncio
import logging

from aiogram import Bot

from repositories import shifts_repo
from services import qc_round_open_service

log = logging.getLogger(__name__)


async def run_qc_round_scheduler_poll(*, bot: Bot, interval_sec: int = 10) -> None:
    _ = bot  # 预留：后续若 scheduler 需要 bot 能力时不改签名
    while True:
        try:
            shifts = shifts_repo.list_all_shifts()
            for s in shifts:
                try:
                    qc_round_open_service.try_open_next_round_for_shift(shift_id=int(s.id))
                except Exception:
                    log.exception("qc_round_scheduler shift_id=%s failed", s.id)
        except Exception:
            log.exception("qc_round_scheduler cycle failed")
        await asyncio.sleep(interval_sec)
