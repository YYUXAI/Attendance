from __future__ import annotations

import asyncio
import logging

from services import qc_timeout_service

log = logging.getLogger(__name__)


async def run_qc_timeout_worker(*, interval_sec: int = 10) -> None:
    while True:
        try:
            qc_timeout_service.run_timeout_cycle(limit=100)
        except Exception as e:
            log.exception(
                "qc_timeout_poll_error phase=cycle exc_type=%s exc=%r",
                type(e).__name__,
                e,
            )
        await asyncio.sleep(interval_sec)
