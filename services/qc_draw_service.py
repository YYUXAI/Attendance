from __future__ import annotations

from datetime import datetime
from typing import Any, List

from psycopg2.extensions import cursor as Cursor

from repositories import (
    effective_leave_days_repo,
    effective_temporary_leaves_repo,
    qc_exemption_fixed_list_repo,
    qc_task_queue_repo,
    registrations_repo,
    shifts_repo,
)


def pick_employees_for_round_cur(
    cur: Cursor,
    *,
    shift: shifts_repo.ShiftRow,
    work_date,
    qc_draw_time_utc: Any,
    draw_count: int,
) -> List[str]:
    """
    一期全集：registrations.shift_id == shift.id；不叠组织。
    排除：固定免检、当日 effective 休假、抽检时刻命中 effective 临时离岗、未终结质检任务、无 tg_id 不可私信者。
    优先本日尚未被抽中者，再补足已抽中者。
    """
    n = int(draw_count)
    if n <= 0:
        return []

    regs = registrations_repo.list_by_shift_id_cur(cur, shift_id=int(shift.id))
    candidates: List[str] = []
    for r in regs:
        if not r.employee_id:
            continue
        if r.tg_id is None or int(r.tg_id) == 0:
            continue
        candidates.append(str(r.employee_id))
    if not candidates:
        return []

    fixed = qc_exemption_fixed_list_repo.list_employee_ids_by_shift_cur(cur, shift_id=int(shift.id))
    on_leave = effective_leave_days_repo.list_on_leave_employee_ids_cur(
        cur,
        shift_id=int(shift.id),
        leave_date=work_date,
        employee_ids=candidates,
    )
    open_tasks = qc_task_queue_repo.list_employee_ids_with_open_tasks_cur(
        cur,
        shift_id=int(shift.id),
        qc_date=work_date,
        employee_ids=candidates,
    )

    eligible: List[str] = []
    for eid in candidates:
        if eid in fixed:
            continue
        if eid in on_leave:
            continue
        if eid in open_tasks:
            continue
        if effective_temporary_leaves_repo.exists_covering_instant_cur(
            cur,
            employee_id=eid,
            shift_id=int(shift.id),
            instant_utc=qc_draw_time_utc,
        ):
            continue
        eligible.append(eid)

    if not eligible:
        return []

    drawn_today = qc_task_queue_repo.list_drawn_employee_ids_for_shift_date_cur(
        cur,
        shift_id=int(shift.id),
        qc_date=work_date,
    )
    not_drawn = [e for e in eligible if e not in drawn_today]
    drawn_before = [e for e in eligible if e in drawn_today]
    ordered = not_drawn + drawn_before
    out: List[str] = []
    seen: set[str] = set()
    for eid in ordered:
        if eid in seen:
            continue
        seen.add(eid)
        out.append(eid)
        if len(out) >= n:
            break
    return out
