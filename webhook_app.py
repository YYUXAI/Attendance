from __future__ import annotations

import asyncio
import hmac
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from aiogram.types import Update
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

# EasyOCR/PyTorch 与 NumPy(MKL) 同进程时须先于二者 import
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("TZ", "UTC")

load_dotenv(
    override=(os.getenv("ATTENDANCE_DOTENV_OVERRIDE") or "1").strip() != "0",
    encoding="utf-8",
)

from infra.bot_owner import load_attendance_bot_owner  # noqa: E402
from infra.db import get_cursor  # noqa: E402
from repositories import telegram_update_inbox_repo, unified_runtime_state_schema  # noqa: E402
from runtime import prepare_runtime  # noqa: E402
from services import register_service  # noqa: E402

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


def _assert_webhook_workers_disabled() -> None:
    configured = (os.getenv("ATTENDANCE_WEBHOOK_RUN_WORKERS") or "").strip().lower()
    if configured in {"1", "true", "yes", "on"}:
        raise RuntimeError("Attendance unified webhook must not start legacy workers")


def _assert_unified_webhook_has_no_legacy_sheets_side_effects() -> None:
    legacy_sheet_flags = (
        "GOOGLE_SHEETS_ENABLED",
        "TEST_GROUP_GOOGLE_SHEETS_ENABLED",
        "BBQ_GOOGLE_SHEETS_ENABLED",
    )
    enabled = [
        key for key in legacy_sheet_flags
        if (os.getenv(key) or "").strip().lower() in {"1", "true", "yes", "on"}
    ]
    if enabled:
        raise RuntimeError("Attendance unified webhook must not enable legacy Sheets side effects")


@asynccontextmanager
async def lifespan(app: FastAPI):
    bot_owner = load_attendance_bot_owner(require_unified=True)
    _assert_webhook_workers_disabled()
    _assert_unified_webhook_has_no_legacy_sheets_side_effects()
    unified_runtime_state_schema.ensure_tables()
    runtime = prepare_runtime(include_polling=False, include_workers=False)
    await runtime.dp.emit_startup()
    worker_tasks: List[asyncio.Task[Any]] = [
        asyncio.create_task(coro, name=f"worker-{i}")
        for i, coro in enumerate(runtime.workers)
    ]
    app.state.bot = runtime.bot
    app.state.dp = runtime.dp
    app.state.worker_tasks = worker_tasks
    app.state.bot_owner = bot_owner
    logger.info(
        "Attendance webhook 已启动 workers=%s workers_enabled=%s port=%s",
        len(worker_tasks),
        False,
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
    return {"status": "ok", "service": "attendance-unified-webhook", "mode": "webhook"}


@app.get("/health")
@app.get("/healthz")
async def health():
    database_healthy = False
    try:
        with get_cursor() as cur:
            cur.execute("SELECT 1")
            database_healthy = cur.fetchone() == (1,)
    except Exception:  # noqa: BLE001
        logger.exception("Attendance webhook database health check failed")
    worker_tasks = list(getattr(app.state, "worker_tasks", []))
    failed_workers = sum(
        1
        for task in worker_tasks
        if task.done() and not task.cancelled() and task.exception() is not None
    )
    workers_enabled = False
    workers_healthy = len(worker_tasks) == 0 and failed_workers == 0
    healthy = database_healthy and workers_healthy
    payload = {
        "status": "healthy" if healthy else "unhealthy",
        "service": "attendance-unified-webhook",
        "mode": "webhook",
        "components": {
            "http": True,
            "database": database_healthy,
            "polling": False,
            "workers": {
                "enabled": workers_enabled,
                "running": len(worker_tasks),
                "failed": failed_workers,
                "healthy": workers_healthy,
            },
        },
    }
    return JSONResponse(payload, status_code=200 if healthy else 503)


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
    update_id = data.get("update_id")
    if isinstance(update_id, bool) or not isinstance(update_id, int):
        return Response(status_code=400)
    bot_owner = app.state.bot_owner
    claim = telegram_update_inbox_repo.claim_update(
        bot_owner=bot_owner,
        update_id=update_id,
        now=datetime.now(timezone.utc),
        lease_ttl=timedelta(minutes=10),
    )
    if claim.state == "busy":
        return Response(status_code=409)
    if claim.state == "completed":
        registration_session = _registration_session_state(data, bot_owner=bot_owner)
        return {
            "ok": True,
            "duplicate": True,
            **(
                {"registration_session": registration_session}
                if registration_session is not None
                else {}
            ),
        }
    if claim.claim_token is None:
        raise RuntimeError("attendance_update_claim_token_missing")
    try:
        await dp.feed_update(bot, update)
    except Exception as exc:
        telegram_update_inbox_repo.fail_update(
            bot_owner=bot_owner,
            update_id=update_id,
            claim_token=claim.claim_token,
            error_code=type(exc).__name__,
            now=datetime.now(timezone.utc),
        )
        raise
    completed = telegram_update_inbox_repo.complete_update(
        bot_owner=bot_owner,
        update_id=update_id,
        claim_token=claim.claim_token,
        now=datetime.now(timezone.utc),
    )
    if not completed:
        raise RuntimeError("attendance_update_completion_lost")
    registration_session = _registration_session_state(data, bot_owner=bot_owner)
    return {
        "ok": True,
        **(
            {"registration_session": registration_session}
            if registration_session is not None
            else {}
        ),
    }


@app.post("/internal/private-registration-session/status")
async def private_registration_session_status(request: Request):
    """由统一壳查询 Attendance 持久注册会话；不复制会话状态到壳。"""
    actor = await _authorized_private_registration_actor(request)
    if isinstance(actor, Response):
        return actor
    tg_id, private_chat_id = actor
    active = register_service.is_waiting_register_input(
        bot_owner=app.state.bot_owner,
        tg_id=tg_id,
        private_chat_id=private_chat_id,
    )
    return {"status": "active" if active else "ended"}


@app.post("/internal/private-registration-session/clear")
async def clear_private_registration_session(request: Request):
    """由统一壳在自己的 /start 首页前终止 Attendance 注册会话。"""
    actor = await _authorized_private_registration_actor(request)
    if isinstance(actor, Response):
        return actor
    tg_id, _private_chat_id = actor
    register_service.clear_waiting_register_input(
        bot_owner=app.state.bot_owner,
        tg_id=tg_id,
    )
    return {"status": "ended"}


async def _authorized_private_registration_actor(
    request: Request,
) -> tuple[int, int] | Response:
    header_value = (
        request.headers.get("x-telegram-bot-api-secret-token")
        or request.headers.get("x-omniai-unified-bot-secret-token")
    )
    if not _webhook_secret_token_matches(header_value):
        return Response(status_code=401)
    if getattr(app.state, "bot_owner", None) != "ux_assistant":
        return Response(status_code=409)
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        return Response(status_code=400)
    if not isinstance(payload, dict):
        return Response(status_code=400)
    tg_id = _positive_integer(payload.get("telegram_user_id"))
    private_chat_id = _positive_integer(payload.get("private_chat_id"))
    if tg_id is None or private_chat_id is None:
        return Response(status_code=400)
    return tg_id, private_chat_id


def _positive_integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value) if isinstance(value, (int, str)) else 0
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _registration_session_state(
    data: dict[str, Any],
    *,
    bot_owner: str,
) -> str | None:
    message = data.get("message")
    actor = message.get("from") if isinstance(message, dict) else None
    chat = message.get("chat") if isinstance(message, dict) else None
    if not isinstance(chat, dict) or chat.get("type") != "private":
        callback = data.get("callback_query")
        actor = callback.get("from") if isinstance(callback, dict) else None
        callback_message = callback.get("message") if isinstance(callback, dict) else None
        chat = callback_message.get("chat") if isinstance(callback_message, dict) else None
    if not isinstance(chat, dict) or chat.get("type") != "private" or not isinstance(actor, dict):
        return None
    tg_id = actor.get("id")
    private_chat_id = chat.get("id")
    if not isinstance(tg_id, int) or not isinstance(private_chat_id, int):
        return None
    return (
        "active"
        if register_service.is_waiting_register_input(
            bot_owner=bot_owner,
            tg_id=tg_id,
            private_chat_id=private_chat_id,
        )
        else "ended"
    )
