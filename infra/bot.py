from __future__ import annotations

import os

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from handlers.attendance_actions import router as attendance_actions_router
from handlers.admin_export_test import router as admin_export_test_router
from handlers.admin_test import router as admin_test_router
from handlers.checkin import router as checkin_router
from handlers.menu import router as menu_router
from handlers.profile import router as profile_router
from handlers.register import router as register_router
# --- 已下线：报备休息 / 私聊离岗审批 / 审批 / QC（勿取消注释）---
# from handlers.rest import router as rest_router
# from handlers.approval import router as approval_router
# from handlers.temporary_leave import router as temporary_leave_router
# from handlers.qc_callback import router as qc_callback_router
# from handlers.qc_message import router as qc_message_router
# from handlers.qc_closeout_group_callback import router as qc_closeout_group_callback_router
from infra.bot_commands import register_bot_commands


def build_app() -> tuple[Bot, Dispatcher]:
    load_dotenv(override=True, encoding="utf-8")
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN")

    bot = Bot(token=token)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(admin_test_router)
    dp.include_router(admin_export_test_router)
    dp.include_router(attendance_actions_router)
    dp.include_router(menu_router)
    dp.include_router(profile_router)
    dp.include_router(register_router)
    dp.include_router(checkin_router)
    # --- 已下线 Handler（报备休息 / 私聊离岗审批 / 审批 / QC）---
    # dp.include_router(rest_router)
    # dp.include_router(approval_router)
    # dp.include_router(temporary_leave_router)
    # dp.include_router(qc_callback_router)
    # dp.include_router(qc_message_router)
    # dp.include_router(qc_closeout_group_callback_router)

    @dp.startup()
    async def _on_startup() -> None:
        await register_bot_commands(bot=bot)

    return bot, dp
