from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Sequence

from infra.audit_notice_key import encode_shift_work_date_key
from infra.db import transaction
from repositories import event_logs_repo, notification_queue_repo, qc_task_queue_repo, registrations_repo, shifts_repo
from services import qc_draw_service, qc_notice_display, qc_schedule_service

log = logging.getLogger(__name__)


def _drawn_member_lines_html(*, employee_ids: Sequence[str]) -> str:
    reg_by = {str(r.employee_id): r for r in registrations_repo.list_by_employee_ids(employee_ids=employee_ids)}
    lines: list[str] = []
    for eid in employee_ids:
        r = reg_by.get(str(eid))
        name = (r.english_name or "").strip() if r else ""
        lines.append(html.escape(name if name else str(eid)))
    return "\n".join(lines)


def _round_start_group_notice_reply_html(
    *,
    shift: shifts_repo.ShiftRow,
    qc_round: int,
    employee_ids: Sequence[str],
) -> str:
    """2004 入队正文：入队前完整生成（HTML），不得在 notification_worker 拼装。"""
    dept = qc_notice_display.department_display_for_shift_id(shift_id=int(shift.id))
    shift_range = qc_notice_display.format_shift_time_range_hhmm(shift=shift)
    tz = html.escape(str(shift.timezone))
    rnd = html.escape(str(int(qc_round)))
    members = _drawn_member_lines_html(employee_ids=employee_ids)
    return (
        "质检开启公告\n"
        "\n"
        f"部门：{html.escape(dept)}\n"
        f"班次：{shift_range}\n"
        f"时区：{tz}\n"
        "\n"
        f"今日第{rnd}轮抽检已经开始，请以下成员留意本机器人私信并在15分钟内完成质检任务，质检结果将写入数据库。\n"
        "\n"
        f"{members}\n"
        "\n"
        "ps：如果您未收到质检任务请私信机器人并发送指令 /qc ，可重启质检流程。"
    )


def try_open_next_round_for_shift(*, shift_id: int, now_utc: datetime | None = None) -> bool:
    """
    事务内：加锁 → 计算 next_round → 调度判定 → 抽人 → event_logs → qc_task_queue → 2004 入队。
    返回是否新建了至少一条任务。
    """
    now = now_utc or datetime.now(timezone.utc)
    shift = shifts_repo.get_by_id(int(shift_id))
    if not shift or shift.qc_enabled is None:
        log.info("qc_round_open skip reason=qc_enabled_null shift_id=%s", shift_id)
        return False
    if shift.qc_enabled is False:
        return False
    if shift.qc_draw_count is None:
        log.info("qc_round_open skip reason=qc_draw_count_null shift_id=%s", shift_id)
        return False

    work_date = qc_schedule_service.work_date_for_shift_now(now_utc=now, shift=shift)
    log_id_out: int | None = None
    next_r_out: int | None = None
    inserted_out = 0

    with transaction() as cur:
        qc_task_queue_repo.acquire_round_open_lock(cur, shift_id=int(shift.id), work_date=work_date)
        max_r = qc_task_queue_repo.max_qc_round_for_shift_date_cur(
            cur, shift_id=int(shift.id), qc_date=work_date
        )
        next_r = int(max_r) + 1
        if not qc_schedule_service.should_open_round(
            shift=shift, work_date=work_date, next_round=next_r, now_utc=now
        ):
            return False

        employee_ids = qc_draw_service.pick_employees_for_round_cur(
            cur,
            shift=shift,
            work_date=work_date,
            qc_draw_time_utc=now,
            draw_count=int(shift.qc_draw_count),
        )
        if not employee_ids:
            log.info("qc_round_open skip reason=no_eligible shift_id=%s work_date=%s", shift.id, work_date)
            return False

        related_event_id = int(encode_shift_work_date_key(shift_id=int(shift.id), work_date=work_date))
        log_id = event_logs_repo.insert_event(
            cur,
            event_name="QC_ROUND_OPENED",
            related_event_name="qc_round",
            related_event_id=related_event_id,
            result="CREATED",
            created_at_utc=now,
        )

        inserted = qc_task_queue_repo.bulk_insert_round_tasks_cur(
            cur,
            log_id=int(log_id),
            shift_id=int(shift.id),
            qc_date=work_date,
            qc_round=int(next_r),
            employee_ids=employee_ids,
            created_at_utc=now,
        )
        if inserted <= 0:
            log.warning(
                "qc_round_open bulk_insert inserted=0 shift_id=%s work_date=%s round=%s",
                shift.id,
                work_date,
                next_r,
            )
            return False
        if inserted != len(employee_ids):
            raise RuntimeError("qc_round_open partial insert")

        log_id_out = int(log_id)
        next_r_out = int(next_r)
        inserted_out = int(inserted)

        gid = shift.attendance_group_id
        if gid is not None and int(gid) != 0:
            notification_queue_repo.insert_qc_round_start_pending(
                cur,
                log_id=int(log_id),
                notify_tg_id=int(gid),
                reply_content=_round_start_group_notice_reply_html(
                    shift=shift,
                    qc_round=next_r,
                    employee_ids=employee_ids,
                ),
                created_at_utc=now,
            )
        else:
            log.info("qc_round_open skip nq2004 reason=no_attendance_group_id shift_id=%s", shift.id)

    log.info(
        "qc_round_open ok shift_id=%s work_date=%s qc_round=%s tasks=%s log_id=%s",
        shift.id,
        work_date,
        next_r_out,
        inserted_out,
        log_id_out,
    )
    return True
