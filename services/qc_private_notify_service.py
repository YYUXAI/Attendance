from __future__ import annotations

import html
import logging
from datetime import datetime, timezone

from aiogram import Bot

from infra.db import transaction
from infra.qc_dm import send_qc_private_open
from keyboards.qc_inline import build_first_stage_keyboard
from repositories import qc_task_queue_repo, registrations_repo, shifts_repo

log = logging.getLogger(__name__)


def _first_touch_caption_html(*, english_name: str, employee_id: str) -> str:
    disp = (english_name or "").strip() or str(employee_id).strip()
    disp_e = html.escape(disp)
    return (
        f"{disp_e}，您好。\n"
        "请在15分钟内按图例所示手势在工作机的锁屏界面拍摄照片，画面必须能清楚的看到您的工号。"
        "如果您已经准备好请点击【确认】开启流程，点击【取消】将取消本次质检并被记录为质检失败。"
    )


async def run_first_private_notify_cycle(*, bot: Bot, limit: int = 50) -> None:
    rows = qc_task_queue_repo.list_pending_first_private_notify(limit=limit)
    if not rows:
        return
    for t in rows:
        reg = registrations_repo.get_by_employee_id(t.employee_id)
        if not reg or reg.tg_id is None or int(reg.tg_id) == 0:
            log.warning(
                "qc_private_notify skip reason=no_tg task_id=%s employee_id=%s",
                t.id,
                t.employee_id,
            )
            continue
        shift = shifts_repo.get_by_id(int(t.shift_id))
        example_fid: str | None = None
        if shift and shift.qc_example_file_id and str(shift.qc_example_file_id).strip():
            example_fid = str(shift.qc_example_file_id).strip()
        kb = build_first_stage_keyboard(task_id=int(t.id))
        ok = await send_qc_private_open(
            bot=bot,
            tg_id=int(reg.tg_id),
            caption_html=_first_touch_caption_html(
                english_name=str(reg.english_name or ""),
                employee_id=str(t.employee_id),
            ),
            example_file_id=example_fid,
            reply_markup=kb,
        )
        if not ok:
            continue
        sent_at = datetime.now(timezone.utc)
        with transaction() as cur:
            n = qc_task_queue_repo.mark_first_private_notify_sent_cur(
                cur,
                task_id=int(t.id),
                sent_at_utc=sent_at,
            )
        if n != 1:
            log.warning(
                "qc_private_notify mark not applied task_id=%s rowcount=%s",
                t.id,
                n,
            )
