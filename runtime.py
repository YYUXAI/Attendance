from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, List

from aiogram import Bot, Dispatcher

from infra.bot import build_app
from infra.daily_report_config import load_daily_report_api_config, load_daily_report_config
from infra.daily_report_http import run_daily_report_http_server
from infra.google_sheets_config import load_google_sheets_config
from infra.logger import configure_logging
from infra.shift_web_config import load_shift_web_config
from repositories import employee_shift_config_repo, temporary_leave_records_repo
from repositories.clock_records_repo import ensure_clock_action_column
from tasks.audit_worker import run_audit_worker
from tasks.daily_attendance_report_worker import run_daily_attendance_report_worker
from tasks.google_sheets_sync_worker import run_google_sheets_sync_worker
from tasks.group_daily_summary_worker import run_group_daily_summary_worker
from tasks.notification_worker import run_notification_worker

WorkerCoro = Callable[[], Awaitable[Any]]


@dataclass
class AttendanceRuntime:
    bot: Bot
    dp: Dispatcher
    workers: List[Awaitable[Any]]


def prepare_runtime(
    *,
    include_polling: bool = False,
    include_workers: bool = True,
) -> AttendanceRuntime:
    """初始化 Bot / Dispatcher / 后台 Worker（不含启动）。"""
    configure_logging()
    employee_shift_config_repo.ensure_table()
    temporary_leave_records_repo.ensure_table()
    ensure_clock_action_column()

    bot, dp = build_app()
    workers: List[Awaitable[Any]] = []
    if include_workers:
        workers.extend([
            run_notification_worker(bot=bot),
            run_audit_worker(),
            run_group_daily_summary_worker(bot=bot),
        ])
        if load_daily_report_config().enabled:
            workers.append(run_daily_attendance_report_worker(bot=bot))
        if load_google_sheets_config().enabled:
            workers.append(run_google_sheets_sync_worker())

        api_cfg = load_daily_report_api_config()
        shift_cfg = load_shift_web_config()
        if api_cfg.enabled or shift_cfg.enabled:
            workers.append(run_daily_report_http_server(bot=bot))

    if include_polling:
        workers.insert(0, dp.start_polling(bot))

    return AttendanceRuntime(bot=bot, dp=dp, workers=workers)


def run_mode() -> str:
    """polling（本地）或 webhook（接入 Gateway）。"""
    mode = (os.getenv("ATTENDANCE_RUN_MODE") or "polling").strip().lower()
    if mode not in {"polling", "webhook"}:
        raise RuntimeError(f"Invalid ATTENDANCE_RUN_MODE={mode!r}, expect polling|webhook")
    return mode
