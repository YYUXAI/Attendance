from __future__ import annotations

import asyncio
import os

from infra.bot import build_app
from infra.logger import configure_logging
from tasks.approval_poll import run_approval_dispatch_poll
from tasks.audit_worker import run_audit_worker
from tasks.notification_worker import run_notification_worker
from tasks.qc_private_notify_poll import run_qc_private_notify_poll
from tasks.qc_round_closeout_poll import run_qc_round_closeout_poll
from tasks.qc_round_scheduler_poll import run_qc_round_scheduler_poll
from tasks.qc_shift_summary_poll import run_qc_shift_summary_poll
from tasks.qc_timeout_worker import run_qc_timeout_worker
from tasks.temporary_leave_effective_poll import run_temporary_leave_effective_poll


async def main() -> None:
    configure_logging()
    bot, dp = build_app()
    await asyncio.gather(
        dp.start_polling(bot),
        run_approval_dispatch_poll(bot=bot),
        run_notification_worker(bot=bot),
        run_audit_worker(),
        run_temporary_leave_effective_poll(),
        run_qc_round_scheduler_poll(bot=bot),
        run_qc_round_closeout_poll(bot=bot),
        run_qc_shift_summary_poll(bot=bot),
        run_qc_private_notify_poll(bot=bot),
        run_qc_timeout_worker(),
    )


if __name__ == "__main__":
    os.environ.setdefault("TZ", "UTC")
    asyncio.run(main())
