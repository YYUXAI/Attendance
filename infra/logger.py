from __future__ import annotations

import logging
import os


def configure_logging() -> None:
    """Uvicorn 会先配置 logging；必须 force=True，否则 INFO 打不出来。"""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
    logging.getLogger().setLevel(level)
