from __future__ import annotations

import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, List, Optional

from aiogram.types import Update
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response

# EasyOCR/PyTorch 与 NumPy(MKL) 同进程时须先于二者 import
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("TZ", "UTC")

load_dotenv(override=True, encoding="utf-8")

from runtime import prepare_runtime  # noqa: E402

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("aiogram.event").setLevel(logging.WARNING)
logger = logging.getLogger("attendance-webhook")


def _webhook_secret_token() -> Optional[str]:
    token = (
        os.getenv("WEBHOOK_SECRET_TOKEN")
        or os.getenv("UNIFIED_BOT_DOWNSTREAM_SECRET_TOKEN")
        or ""
    ).strip()
    return token or None


def _webhook_secret_token_matches(header_value: Optional[str]) -> bool:
    expected = _webhook_secret_token()
    if expected is None:
        return False
    return header_value is not None and hmac.compare_digest(header_value, expected)


def _webhook_workers_enabled() -> bool:
    configured = os.getenv("ATTENDANCE_WEBHOOK_RUN_WORKERS")
    if configured is None:
        return False
    return configured.strip().lower() in {"1", "true", "yes", "on"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    workers_enabled = _webhook_workers_enabled()
    runtime = prepare_runtime(include_polling=False, include_workers=workers_enabled)
    await runtime.dp.emit_startup()
    worker_tasks: List[asyncio.Task[Any]] = [
        asyncio.create_task(coro, name=f"worker-{i}")
        for i, coro in enumerate(runtime.workers)
    ]
    app.state.bot = runtime.bot
    app.state.dp = runtime.dp
    app.state.worker_tasks = worker_tasks
    logger.info(
        "Attendance webhook 已启动 workers=%s workers_enabled=%s port=%s",
        len(worker_tasks),
        workers_enabled,
        os.getenv("WEBHOOK_PORT", "8001"),
    )
    try:
        yield
    finally:
        for task in worker_tasks:
            task.cancel()
        if worker_tasks:
            await asyncio.gather(*worker_tasks, return_exceptions=True)
        try:
            await runtime.dp.emit_shutdown()
        except Exception:  # noqa: BLE001
            logger.exception("emit_shutdown failed")
        await runtime.bot.session.close()
        logger.info("Attendance webhook 已关闭")


app = FastAPI(title="Attendance Bot Webhook", version="1.0.0", lifespan=lifespan)


@app.get("/")
async def root():
    return {"status": "ok", "service": "attendance-python", "mode": "webhook"}


@app.get("/health")
async def health():
    return {"status": "healthy", "service": "attendance-python"}


@app.post("/webhook")
async def telegram_webhook(request: Request):
    """接收 Gateway 转发的 Telegram Update。"""
    header_value = (
        request.headers.get("x-telegram-bot-api-secret-token")
        or request.headers.get("x-omniai-unified-bot-secret-token")
    )
    if not _webhook_secret_token_matches(header_value):
        return Response(status_code=401)

    try:
        data = await request.json()
    except Exception:  # noqa: BLE001
        logger.warning("invalid webhook JSON payload")
        return Response(status_code=400)

    bot = app.state.bot
    dp = app.state.dp
    try:
        update = Update.model_validate(data, context={"bot": bot})
    except Exception:  # noqa: BLE001
        logger.warning("invalid update payload")
        return Response(status_code=400)
    await dp.feed_update(bot, update)
    return Response(content='{"ok":true}', media_type="application/json")
