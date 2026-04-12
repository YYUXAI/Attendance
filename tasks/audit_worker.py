from __future__ import annotations

import asyncio
import logging

from services import audit_service
from repositories import shifts_repo

log = logging.getLogger(__name__)


async def run_audit_worker(*, interval_sec: int = 300) -> None:
    """
    审计 worker：
    - 每 5 分钟轮询一次
    - 初始化建任务（每阶段一次，不重复整批插入）
    - 执行未终态任务（PENDING/FAILED）
    - 触发审计通知缺失检查与补建（3003/3006 必须落地；3004 条件实现；3005 保留）
    """
    while True:
        try:
            shifts = shifts_repo.list_all_shifts()
            for s in shifts:
                # 初始化任务：到达窗口 start 后会生效；未到则返回 0
                audit_service.init_checkin_tasks_for_shift(shift_id=s.id)
                audit_service.init_checkout_tasks_for_shift(shift_id=s.id)
                # 通知补建：只补缺失，不处理发送失败重试
                audit_service.check_and_backfill_notifications_for_shift(shift_id=s.id)

            # 执行任务（批量）
            audit_service.run_batch(limit=200)
        except Exception:
            log.exception("audit_worker cycle failed")
        await asyncio.sleep(interval_sec)

