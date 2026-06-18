from __future__ import annotations

import os

# EasyOCR/PyTorch 与 NumPy(MKL) 同进程时须先于二者 import（见 Intel OpenMP #15）
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import asyncio

from dotenv import load_dotenv

load_dotenv(override=True, encoding="utf-8")

from infra.bot import build_app
from infra.logger import configure_logging
from infra.daily_report_config import load_daily_report_api_config, load_daily_report_config
from infra.google_sheets_config import load_google_sheets_config
from infra.shift_web_config import load_shift_web_config
from infra.daily_report_http import run_daily_report_http_server
from repositories import employee_shift_config_repo, temporary_leave_records_repo
from repositories.clock_records_repo import ensure_clock_action_column
from tasks.audit_worker import run_audit_worker
from tasks.daily_attendance_report_worker import run_daily_attendance_report_worker
from tasks.google_sheets_sync_worker import run_google_sheets_sync_worker
from tasks.group_daily_summary_worker import run_group_daily_summary_worker
from tasks.notification_worker import run_notification_worker
# --- 已下线 Worker（报备休息 / 私聊离岗审批 / 审批 / QC）— 勿取消注释 ---
# from tasks.approval_poll import run_approval_dispatch_poll
# from tasks.temporary_leave_effective_poll import run_temporary_leave_effective_poll
# from tasks.qc_timeout_worker import run_qc_timeout_worker
# from tasks.qc_round_scheduler_poll import run_qc_round_scheduler_poll
# from tasks.qc_private_notify_poll import run_qc_private_notify_poll
# from tasks.qc_round_closeout_poll import run_qc_round_closeout_poll
# from tasks.qc_shift_summary_poll import run_qc_shift_summary_poll


async def main() -> None:
    configure_logging()
    employee_shift_config_repo.ensure_table()
    temporary_leave_records_repo.ensure_table()
    ensure_clock_action_column()
    bot, dp = build_app()
    tasks = [
        dp.start_polling(bot),
        run_notification_worker(bot=bot),
        run_audit_worker(),
        run_group_daily_summary_worker(bot=bot),
    ]
    # --- 已下线 Worker 任务（报备休息 / 私聊离岗审批 / 审批 / QC）---
    # tasks.append(run_approval_dispatch_poll(bot=bot))
    # tasks.append(run_temporary_leave_effective_poll())
    # tasks.append(run_qc_timeout_worker())
    # tasks.append(run_qc_round_scheduler_poll(bot=bot))
    # tasks.append(run_qc_private_notify_poll(bot=bot))
    # tasks.append(run_qc_round_closeout_poll(bot=bot))
    # tasks.append(run_qc_shift_summary_poll(bot=bot))
    if load_daily_report_config().enabled:
        tasks.append(run_daily_attendance_report_worker(bot=bot))
    if load_google_sheets_config().enabled:
        tasks.append(run_google_sheets_sync_worker())
    api_cfg = load_daily_report_api_config()
    shift_cfg = load_shift_web_config()
    if api_cfg.enabled or shift_cfg.enabled:
        tasks.append(run_daily_report_http_server(bot=bot))
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    os.environ.setdefault("TZ", "UTC")
    asyncio.run(main())
