from __future__ import annotations

import asyncio
import logging

from infra.google_sheets_config import load_google_sheets_config
from services.google_sheets_shift_sync_service import sync_shifts_from_google_sheets

log = logging.getLogger(__name__)


async def run_google_sheets_sync_worker() -> None:
    cfg = load_google_sheets_config()
    if not cfg.enabled:
        log.info("google_sheets_worker: disabled")
        return

    log.info(
        "google_sheets_worker: started interval=%ss year_month=%s",
        cfg.sync_interval_seconds,
        cfg.year_month,
    )

    while True:
        try:
            result = await asyncio.to_thread(sync_shifts_from_google_sheets, cfg=cfg)
            if result.ok:
                log.info("google_sheets_worker: %s", result.message)
            else:
                log.warning("google_sheets_worker: %s", result.message)
        except Exception:
            log.exception("google_sheets_worker: sync error")
        await asyncio.sleep(cfg.sync_interval_seconds)
