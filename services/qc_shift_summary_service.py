from __future__ import annotations

import html
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Tuple

from infra.db import transaction
from repositories import (
    notification_queue_repo,
    qc_results_repo,
    qc_task_queue_repo,
    registrations_repo,
    shifts_repo,
)
from services import qc_notice_display, qc_schedule_service

log = logging.getLogger(__name__)

_SUMMARY_LOOKBACK_DAYS = 60
_SCAN_PAIR_LIMIT = 300


def _escaped_display_name(
    *,
    employee_id: str,
    reg_by_eid: Dict[str, registrations_repo.RegistrationRow],
) -> str:
    reg = reg_by_eid.get(str(employee_id))
    name = (reg.english_name or "").strip() if reg else ""
    text = name if name else str(employee_id)
    return html.escape(text)


def _join_names(names: List[str]) -> str:
    return "、".join(names) if names else "无"


def _build_reply_html(
    *,
    shift: shifts_repo.ShiftRow,
    qc_date: date,
    round_sections: List[Tuple[int, List[str], List[str]]],
) -> str:
    dept = qc_notice_display.department_display_for_shift_id(shift_id=int(shift.id))
    shift_range = qc_notice_display.format_shift_time_range_hhmm(shift=shift)
    tz = html.escape(str(shift.timezone))
    qd = html.escape(qc_date.isoformat())
    n_rounds = len(round_sections)

    lines: List[str] = [
        "<b>质检班次汇总公告</b>",
        f"日期：{qd}",
        f"部门：{html.escape(dept)}",
        f"班次：{shift_range}",
        f"时区：{tz}",
        "",
        f"今日共质检{html.escape(str(n_rounds))}轮，质检结果如下：",
        "",
    ]

    for rno, pass_names, incomplete_names in round_sections:
        lines.append(f"第{html.escape(str(int(rno)))}轮：")
        lines.append(f"完成：{_join_names(pass_names)}")
        lines.append(f"未完成：{_join_names(incomplete_names)}")
        lines.append("")
    lines.append("质检结果已经录入，如有问题请及时联系管理员。")
    return "\n".join(lines).rstrip() + "\n"


def _registration_map(*, employee_ids: List[str]) -> Dict[str, registrations_repo.RegistrationRow]:
    rows = registrations_repo.list_by_employee_ids(employee_ids=employee_ids)
    return {str(r.employee_id): r for r in rows}


def _is_pass(*, snap: Dict[Tuple[str, int], str], employee_id: str, qc_round: int) -> bool:
    raw = snap.get((str(employee_id), int(qc_round)))
    if raw is None or not str(raw).strip():
        return False
    return str(raw).strip().upper() == "PASS"


def try_enqueue_shift_qc_summary_for_pair(*, shift_id: int, qc_date: date, now_utc: datetime) -> None:
    shift = shifts_repo.get_by_id(int(shift_id))
    if not shift:
        return
    gid = shift.attendance_group_id
    if gid is None or int(gid) == 0:
        log.info("qc_shift_summary skip reason=no_attendance_group shift_id=%s qc_date=%s", shift_id, qc_date)
        return

    end_utc = qc_schedule_service.shift_end_utc_for_qc_date(qc_date=qc_date, shift=shift)
    if now_utc < end_utc + timedelta(minutes=10):
        return

    rounds = qc_task_queue_repo.list_qc_rounds_for_shift_qc_date(shift_id=int(shift_id), qc_date=qc_date)
    if not rounds:
        return

    employee_ids = qc_task_queue_repo.list_employee_ids_for_shift_qc_date_from_tasks(
        shift_id=int(shift_id), qc_date=qc_date
    )
    if not employee_ids:
        return

    result_rows = qc_results_repo.list_for_shift_and_qc_date(shift_id=int(shift_id), qc_date=qc_date)
    snap: Dict[Tuple[str, int], str] = {}
    for r in result_rows:
        snap[(str(r.employee_id), int(r.qc_round))] = str(r.result)

    reg_by_eid = _registration_map(employee_ids=employee_ids)

    round_sections: List[Tuple[int, List[str], List[str]]] = []
    for rno in rounds:
        eids = qc_task_queue_repo.list_employee_ids_for_shift_qc_date_round(
            shift_id=int(shift_id), qc_date=qc_date, qc_round=int(rno)
        )
        pass_names: List[str] = []
        incomplete_names: List[str] = []
        for eid in eids:
            disp = _escaped_display_name(employee_id=str(eid), reg_by_eid=reg_by_eid)
            if _is_pass(snap=snap, employee_id=str(eid), qc_round=int(rno)):
                pass_names.append(disp)
            else:
                incomplete_names.append(disp)
        round_sections.append((int(rno), pass_names, incomplete_names))

    body = _build_reply_html(shift=shift, qc_date=qc_date, round_sections=round_sections)

    with transaction() as cur:
        inserted = notification_queue_repo.insert_qc_shift_summary_if_missing(
            cur,
            shift_id=int(shift_id),
            work_date=qc_date,
            notify_tg_id=int(gid),
            template_id=int(notification_queue_repo.TEMPLATE_QC_SHIFT_SUMMARY_GROUP_NOTICE),
            reply_content=body,
            created_at_utc=now_utc,
        )
    if inserted:
        log.info("qc_shift_summary enqueued shift_id=%s qc_date=%s", shift_id, qc_date)


def run_shift_summary_cycle(*, now_utc: datetime | None = None) -> None:
    now = now_utc or datetime.now(timezone.utc)
    min_qc = now.date() - timedelta(days=_SUMMARY_LOOKBACK_DAYS)
    pairs = qc_task_queue_repo.list_distinct_shift_qc_date_pairs_for_summary(
        min_qc_date=min_qc,
        limit=_SCAN_PAIR_LIMIT,
    )
    for sid, qd in pairs:
        try:
            try_enqueue_shift_qc_summary_for_pair(shift_id=int(sid), qc_date=qd, now_utc=now)
        except Exception:
            log.exception("qc_shift_summary pair failed shift_id=%s qc_date=%s", sid, qd)
