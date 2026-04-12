from __future__ import annotations

import asyncio
import logging

from services.temporary_leave_effective_poll_service import run_poll_cycle

log = logging.getLogger(__name__)


async def run_temporary_leave_effective_poll(*, interval_sec: int = 10) -> None:
    while True:
        try:
            run_poll_cycle(limit=100)
        except Exception as e:
            log.exception(
                "tleave_effective_poll_error phase=cycle exc_type=%s exc=%r",
                type(e).__name__,
                e,
            )
        await asyncio.sleep(interval_sec)
