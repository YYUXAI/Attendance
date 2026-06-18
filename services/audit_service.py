from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from zoneinfo import ZoneInfo

from domain import audit_rules
from domain.audit_notification_builder import (
    DepartmentGroupSummaryLine,
    LeaveLineDisplay,
    PersonDisplay,
    build_shift_start_department_head_dm_html,
    build_shift_start_group_notice_html,
    build_shift_start_leader_dm_html,
)
from domain.shared.person_html import person_display_html
from infra.db import transaction
from infra.audit_notice_key import RELATED_EVENT_NAME_AUDIT_NOTICE, encode_shift_work_date_key
from repositories import (
    audit_results_repo,
    audit_task_queue_repo,
    clock_records_repo,
    effective_leave_days_repo,
    effective_temporary_leaves_repo,
    event_logs_repo,
    notification_queue_repo,
    organizations_repo,
    registrations_repo,
    shifts_repo,
)
from services import group_attendance_summary_service
from services.leave_calendar_utils import format_utc_in_shift_timezone

log = logging.getLogger(__name__)

# template_id（docs05：审计模块 3000-3999）
TEMPLATE_AUDIT_SHIFT_START_GROUP_NOTICE = 3003
TEMPLATE_AUDIT_SHIFT_START_LEADER_DM_NOTICE = 3004
TEMPLATE_AUDIT_SHIFT_START_DEPARTMENT_HEAD_NOTICE = 3005
TEMPLATE_AUDIT_SHIFT_END_GROUP_REMINDER_NOTICE = 3006

AUDIT_STAGE_CHECKIN = "CHECKIN"
AUDIT_STAGE_CHECKOUT = "CHECKOUT"


def _shift_label(*, shift: shifts_repo.ShiftRow) -> str:
    # 不引入新字段，仅用现有时间展示
    def _fmt(t: object) -> str:
        if isinstance(t, time):
            return t.strftime("%H:%M")
        if isinstance(t, datetime):
            return t.strftime("%H:%M")
        return str(t)

    return f"{_fmt(shift.checkin_time)} - {_fmt(shift.checkout_time)}"


def _local_dt(*, work_date: date, t: object, tz: ZoneInfo) -> datetime:
    tt = t if isinstance(t, time) else audit_rules.as_time(t)
    return datetime.combine(work_date, tt, tzinfo=tz)


def _checkout_center_local(*, work_date: date, shift: shifts_repo.ShiftRow, tz: ZoneInfo) -> datetime:
    # 下班提醒必须严格按“下班时间”触发。
    # 若配置未标记 is_overnight 但 checkout_time <= checkin_time，会导致“上班时间就满足 now>=checkout”而提前发送。
    checkin_t = shift.checkin_time if isinstance(shift.checkin_time, time) else audit_rules.as_time(shift.checkin_time)
    checkout_t = shift.checkout_time if isinstance(shift.checkout_time, time) else audit_rules.as_time(shift.checkout_time)
    overnight = bool(shift.is_overnight) or (checkout_t <= checkin_t)
    d = work_date + timedelta(days=1) if overnight else work_date
    tt = checkout_t
    return datetime.combine(d, tt, tzinfo=tz)


def _work_date_for_now(*, now_utc: datetime, shift: shifts_repo.ShiftRow) -> date:
    return audit_rules.work_date_for_shift_day(
        shift_checkin_time=shift.checkin_time,
        instant_utc=now_utc,
        timezone_name=shift.timezone,
        is_overnight=bool(shift.is_overnight),
    )


def _is_time_reached(*, now_utc: datetime, target_local: datetime) -> bool:
    return now_utc >= target_local.astimezone(timezone.utc)


def init_checkin_tasks_for_shift(*, shift_id: int, now_utc: Optional[datetime] = None) -> int:
    """
    CHECKIN 初始化建任务（每阶段一次）：到达“最早上班有效窗口开始时”触发。
    """
    now = now_utc or datetime.now(timezone.utc)
    shift = shifts_repo.get_by_id(shift_id)
    if not shift:
        return 0
    tz = ZoneInfo(shift.timezone)
    work_date = _work_date_for_now(now_utc=now, shift=shift)
    win = audit_rules.compute_checkin_window_utc(
        target_work_date=work_date,
        shift_checkin_time=shift.checkin_time,
        timezone_name=shift.timezone,
        attendance_flex_interval=shift.attendance_flex_interval,
    )
    # 触发时机：最早有效打卡时间开始时（窗口 start）
    if now < win.start_utc:
        return 0

    regs = registrations_repo.list_by_shift_id(shift_id=shift_id)
    employee_ids = [r.employee_id for r in regs if r.employee_id]
    if not employee_ids:
        return 0

    with transaction() as cur:
        audit_task_queue_repo.acquire_init_lock(cur, shift_id=shift_id, work_date=work_date, audit_stage=AUDIT_STAGE_CHECKIN)
        existing = set(
            audit_task_queue_repo.list_existing_employee_ids_for_stage(
                cur,
                employee_ids=employee_ids,
                target_date=work_date,
                audit_stage=AUDIT_STAGE_CHECKIN,
            )
        )
        missing_employee_ids = [eid for eid in employee_ids if eid not in existing]
        if not missing_employee_ids:
            return 0

        log_id = event_logs_repo.insert_event(
            cur,
            event_name="AUDIT_TASK_TRIGGERED",
            related_event_name="audit_task_init_checkin",
            related_event_id=encode_shift_work_date_key(shift_id=shift_id, work_date=work_date),
            result="CREATED",
            created_at_utc=now,
        )
        inserted = audit_task_queue_repo.bulk_insert_init_tasks(
            cur,
            log_id=log_id,
            audit_started_at_utc=now,
            employee_ids=missing_employee_ids,
            target_date=work_date,
            audit_stage=AUDIT_STAGE_CHECKIN,
            created_at_utc=now,
        )
    return inserted


def init_checkout_tasks_for_shift(*, shift_id: int, now_utc: Optional[datetime] = None) -> int:
    """
    CHECKOUT 初始化建任务：到达“最早下班有效窗口开始时”触发。
    """
    now = now_utc or datetime.now(timezone.utc)
    shift = shifts_repo.get_by_id(shift_id)
    if not shift:
        return 0
    tz = ZoneInfo(shift.timezone)
    work_date = _work_date_for_now(now_utc=now, shift=shift)
    win = audit_rules.compute_checkout_window_utc(
        target_work_date=work_date,
        shift_checkin_time=shift.checkin_time,
        shift_checkout_time=shift.checkout_time,
        timezone_name=shift.timezone,
        is_overnight=shift.is_overnight,
        attendance_flex_interval=shift.attendance_flex_interval,
    )
    if now < win.start_utc:
        return 0

    regs = registrations_repo.list_by_shift_id(shift_id=shift_id)
    employee_ids = [r.employee_id for r in regs if r.employee_id]
    if not employee_ids:
        return 0

    with transaction() as cur:
        audit_task_queue_repo.acquire_init_lock(cur, shift_id=shift_id, work_date=work_date, audit_stage=AUDIT_STAGE_CHECKOUT)
        existing = set(
            audit_task_queue_repo.list_existing_employee_ids_for_stage(
                cur,
                employee_ids=employee_ids,
                target_date=work_date,
                audit_stage=AUDIT_STAGE_CHECKOUT,
            )
        )
        missing_employee_ids = [eid for eid in employee_ids if eid not in existing]
        if not missing_employee_ids:
            return 0

        log_id = event_logs_repo.insert_event(
            cur,
            event_name="AUDIT_TASK_TRIGGERED",
            related_event_name="audit_task_init_checkout",
            related_event_id=encode_shift_work_date_key(shift_id=shift_id, work_date=work_date),
            result="CREATED",
            created_at_utc=now,
        )
        inserted = audit_task_queue_repo.bulk_insert_init_tasks(
            cur,
            log_id=log_id,
            audit_started_at_utc=now,
            employee_ids=missing_employee_ids,
            target_date=work_date,
            audit_stage=AUDIT_STAGE_CHECKOUT,
            created_at_utc=now,
        )
    return inserted


def _clock_times_in_window(
    *,
    employee_id: str,
    shift_id: int,
    start_utc: datetime,
    end_utc: datetime,
) -> List[datetime]:
    rows = clock_records_repo.list_clock_records_in_range(
        employee_id=employee_id,
        shift_id=shift_id,
        start_at_utc=start_utc,
        end_at_utc=end_utc,
    )
    out: List[datetime] = []
    for r in rows:
        if isinstance(r.clock_time, datetime):
            out.append(r.clock_time)
        else:
            # psycopg2 通常返回 datetime；若不是，强制字符串化会破坏比较，直接跳过
            continue
    out.sort()
    return out


def _stage_instant_for_leave_check_utc(*, work_date: date, shift: shifts_repo.ShiftRow, stage: str) -> datetime:
    if stage == AUDIT_STAGE_CHECKIN:
        return datetime.combine(
            work_date,
            audit_rules.as_time(shift.checkin_time),
            tzinfo=ZoneInfo(shift.timezone),
        ).astimezone(timezone.utc)
    if stage == AUDIT_STAGE_CHECKOUT:
        center_local = _checkout_center_local(work_date=work_date, shift=shift, tz=ZoneInfo(shift.timezone))
        return center_local.astimezone(timezone.utc)
    raise ValueError("Unsupported audit stage (BREAK not allowed)")


def run_one_task(*, task: audit_task_queue_repo.AuditTaskRow, now_utc: Optional[datetime] = None) -> None:
    """
    执行单条审计任务：
    - 调 domain 完成判定
    - upsert audit_results
    - 回写 audit_task_queue
    """
    now = now_utc or datetime.now(timezone.utc)

    # 抢占
    if not audit_task_queue_repo.claim_task_processing(task_id=task.id):
        return

    try:
        reg = registrations_repo.get_by_employee_id(task.employee_id)
        if not reg or reg.shift_id is None or reg.organization_id is None:
            # 无法审计：配置缺失，按系统失败记录，不污染业务结果
            new_retry = audit_task_queue_repo.increment_retry_count(task_id=task.id)
            with transaction() as cur:
                audit_task_queue_repo.mark_system_failed(
                    cur,
                    task_id=task.id,
                    processed_at_utc=now,
                    retry_count=new_retry,
                    error_message="registration missing org/shift",
                )
            return

        shift = shifts_repo.get_by_id(int(reg.shift_id))
        if not shift:
            new_retry = audit_task_queue_repo.increment_retry_count(task_id=task.id)
            with transaction() as cur:
                audit_task_queue_repo.mark_system_failed(
                    cur,
                    task_id=task.id,
                    processed_at_utc=now,
                    retry_count=new_retry,
                    error_message="shift missing",
                )
            return

        stage = task.audit_stage
        if stage not in (AUDIT_STAGE_CHECKIN, AUDIT_STAGE_CHECKOUT):
            # 禁止实现 BREAK：遇到 BREAK 直接 SKIPPED
            with transaction() as cur:
                audit_task_queue_repo.update_after_run(
                    cur,
                    task_id=task.id,
                    audit_result="NONE",
                    processed_at_utc=now,
                    task_status="SKIPPED",
                    error_message="BREAK not supported",
                )
            return

        work_date = task.target_date  # docs00：target_date 已是“上班日”语义

        is_on_leave = effective_leave_days_repo.exists_leave_day(
            employee_id=task.employee_id,
            shift_id=int(shift.id),
            leave_date=work_date,
        )
        instant_utc = _stage_instant_for_leave_check_utc(work_date=work_date, shift=shift, stage=stage)
        is_temp_leave = effective_temporary_leaves_repo.exists_covering_instant(
            employee_id=task.employee_id,
            shift_id=int(shift.id),
            instant_utc=instant_utc,
        )
        # EXEMPT：一期无明确来源，按兼容分支保留为 False
        is_exempt = False

        if stage == AUDIT_STAGE_CHECKIN:
            win = audit_rules.compute_checkin_window_utc(
                target_work_date=work_date,
                shift_checkin_time=shift.checkin_time,
                timezone_name=shift.timezone,
                attendance_flex_interval=shift.attendance_flex_interval,
            )
            clocks = _clock_times_in_window(
                employee_id=task.employee_id,
                shift_id=int(shift.id),
                start_utc=win.start_utc,
                end_utc=win.end_utc,
            )
            decision = audit_rules.decide_checkin(
                now_utc=now,
                target_work_date=work_date,
                shift_checkin_time=shift.checkin_time,
                timezone_name=shift.timezone,
                attendance_flex_interval=shift.attendance_flex_interval,
                max_late_early_tolerance=shift.max_late_early_tolerance,
                is_on_leave=is_on_leave,
                is_temporary_leave_covering=is_temp_leave,
                is_exempt=is_exempt,
                window_clock_times_utc=clocks,
            )
        else:
            win = audit_rules.compute_checkout_window_utc(
                target_work_date=work_date,
                shift_checkin_time=shift.checkin_time,
                shift_checkout_time=shift.checkout_time,
                timezone_name=shift.timezone,
                is_overnight=shift.is_overnight,
                attendance_flex_interval=shift.attendance_flex_interval,
            )
            clocks = _clock_times_in_window(
                employee_id=task.employee_id,
                shift_id=int(shift.id),
                start_utc=win.start_utc,
                end_utc=win.end_utc,
            )
            decision = audit_rules.decide_checkout(
                now_utc=now,
                target_work_date=work_date,
                shift_checkin_time=shift.checkin_time,
                shift_checkout_time=shift.checkout_time,
                timezone_name=shift.timezone,
                is_overnight=shift.is_overnight,
                attendance_flex_interval=shift.attendance_flex_interval,
                max_late_early_tolerance=shift.max_late_early_tolerance,
                is_on_leave=is_on_leave,
                is_temporary_leave_covering=is_temp_leave,
                is_exempt=is_exempt,
                window_clock_times_utc=clocks,
            )

        # 落结果表（幂等 upsert）
        with transaction() as cur:
            # audit_results 是“最终审计结果”，非终态缺卡（result=NONE）不写入 audit_results
            if decision.result != audit_rules.AUDIT_RESULT_NONE:
                audit_results_repo.upsert_audit_result(
                    cur,
                    employee_id=task.employee_id,
                    shift_id=int(shift.id),
                    organization_id=int(reg.organization_id),
                    audit_date=work_date,
                    audit_stage=stage,
                    checked_at_utc=now,
                    valid_clock_time_utc=decision.valid_clock_time_utc,
                    result=decision.result,
                )
            # 回写任务：非终态继续 PENDING，等待下一轮刷新
            task_status = "DONE" if decision.is_terminal else "PENDING"
            audit_task_queue_repo.update_after_run(
                cur,
                task_id=task.id,
                audit_result=decision.result,
                processed_at_utc=now,
                task_status=task_status,
                error_message=None,
            )
    except Exception as e:
        new_retry = audit_task_queue_repo.increment_retry_count(task_id=task.id)
        with transaction() as cur:
            audit_task_queue_repo.mark_system_failed(
                cur,
                task_id=task.id,
                processed_at_utc=now,
                retry_count=new_retry,
                error_message=str(e),
            )


def run_batch(*, limit: int = 200) -> int:
    tasks = audit_task_queue_repo.list_runnable_tasks(limit=limit)
    for t in tasks:
        run_one_task(task=t)
    return len(tasks)


def _enqueue_audit_notice(
    *,
    template_id: int,
    notify_tg_id: int,
    shift_id: int,
    work_date: date,
    reply_content: str,
    now_utc: datetime,
) -> bool:
    with transaction() as cur:
        return notification_queue_repo.insert_audit_notice_if_missing(
            cur,
            shift_id=shift_id,
            work_date=work_date,
            notify_tg_id=notify_tg_id,
            template_id=template_id,
            reply_content=reply_content,
            created_at_utc=now_utc,
        )


def _canonical_shift_id_for_attendance_group(*, attendance_group_id: int) -> Optional[int]:
    """多班次共用同一考勤群时，开班群公告只由 shift_id 最小的一条班次产出。"""
    rows = shifts_repo.list_by_attendance_group_id(attendance_group_id=int(attendance_group_id))
    if not rows:
        return None
    return min(int(s.id) for s in rows)


def _person_display_from_notice_person(
    p: group_attendance_summary_service.ShiftStartNoticePerson,
) -> PersonDisplay:
    return PersonDisplay(english_name=p.english_name, tg_username=p.tg_username)


def build_shift_start_group_notice_html_for_shift(
    *,
    shift_id: int,
    work_date: Optional[date] = None,
    now_utc: Optional[datetime] = None,
) -> Optional[str]:
    """组装 3003 开班考勤群公告 HTML（统计口径与当日导出一致）。"""
    shift = shifts_repo.get_by_id(int(shift_id))
    if not shift or shift.attendance_group_id is None:
        return None
    now = now_utc or datetime.now(timezone.utc)
    wd = work_date or _work_date_for_now(now_utc=now, shift=shift)
    chat_id = int(shift.attendance_group_id)
    year_month = wd.strftime("%Y-%m")
    buckets = group_attendance_summary_service.compute_shift_start_notice_buckets(
        chat_id=chat_id,
        target_date=wd,
        shift_id=int(shift_id),
    )
    shift_label = group_attendance_summary_service.distinct_shift_labels_for_group(
        chat_id=chat_id,
        year_month=year_month,
    )
    if not shift_label:
        shift_label = _shift_label(shift=shift)

    return build_shift_start_group_notice_html(
        work_date=wd,
        shift_label=shift_label,
        timezone_name=shift.timezone,
        should_count=buckets.should_count,
        checked_in=[_person_display_from_notice_person(p) for p in buckets.arrived],
        on_leave=[_person_display_from_notice_person(p) for p in buckets.on_rest],
        late=[_person_display_from_notice_person(p) for p in buckets.late],
        absent=[_person_display_from_notice_person(p) for p in buckets.absent],
    )


def check_and_backfill_notifications_for_shift(*, shift_id: int, now_utc: Optional[datetime] = None) -> Dict[str, str]:
    """
    通知缺失检查与补建（只补建缺失，不处理发送失败重试）。

    当前一期必须真正落地：
    - 3003 开班考勤群公告（多班次共用群时仅 shift_id 最小者发送，当前为 shift 0）
    - 3006 下班群提醒已关闭（业务不要求 23:30 下班提醒）
    并尝试实现 3004（若 leader->tg_id 链路可用）。
    3005 仅保留接口，不强行发送。
    """
    now = now_utc or datetime.now(timezone.utc)
    shift = shifts_repo.get_by_id(shift_id)
    if not shift:
        return {"status": "skip", "reason": "shift_missing"}

    work_date = _work_date_for_now(now_utc=now, shift=shift)
    tz = ZoneInfo(shift.timezone)
    checkin_center_local = datetime.combine(
        work_date,
        audit_rules.as_time(shift.checkin_time),
        tzinfo=tz,
    )
    out: Dict[str, str] = {"status": "ok"}

    # 3003：开班群公告（到达上班时间；共用群时仅 canonical shift 发送）
    if shift.attendance_group_id is not None and _is_time_reached(now_utc=now, target_local=checkin_center_local):
        gid = int(shift.attendance_group_id)
        canonical_shift_id = _canonical_shift_id_for_attendance_group(attendance_group_id=gid)
        if canonical_shift_id is None or int(shift_id) != int(canonical_shift_id):
            out["3003"] = "skip_not_canonical_shift"
        elif notification_queue_repo.exists_audit_notice_by_business_key(
            shift_id=int(canonical_shift_id),
            work_date=work_date,
            notify_tg_id=gid,
            template_id=TEMPLATE_AUDIT_SHIFT_START_GROUP_NOTICE,
        ):
            out["3003"] = "exists"
        else:
            reply = build_shift_start_group_notice_html_for_shift(
                shift_id=int(canonical_shift_id),
                work_date=work_date,
                now_utc=now,
            )
            if not reply:
                out["3003"] = "skip_build_failed"
            else:
                inserted = _enqueue_audit_notice(
                    template_id=TEMPLATE_AUDIT_SHIFT_START_GROUP_NOTICE,
                    notify_tg_id=gid,
                    shift_id=int(canonical_shift_id),
                    work_date=work_date,
                    reply_content=reply,
                    now_utc=now,
                )
                out["3003"] = "enqueued" if inserted else "exists"
    elif shift.attendance_group_id is not None and not _is_time_reached(
        now_utc=now, target_local=checkin_center_local
    ):
        out["3003"] = "skip_not_time_reached_checkin"

    # 3004：组长私信（条件实现：leader_employee_id -> registrations.tg_id 链路当前可用）
    if not _is_time_reached(now_utc=now, target_local=checkin_center_local):
        out["3004"] = "skip_not_time_reached_checkin"
        log.info(
            "audit_notice template_id=%s shift_id=%s work_date=%s outcome=skip reason=%s",
            TEMPLATE_AUDIT_SHIFT_START_LEADER_DM_NOTICE,
            shift_id,
            work_date,
            out["3004"],
        )
    else:
        regs = registrations_repo.list_by_shift_id(shift_id=shift_id)
        org_id = regs[0].organization_id if regs and regs[0].organization_id is not None else None
        if org_id is not None:
            leader_eid, _highest = organizations_repo.get_leader_fields(int(org_id))
            leader_eid_n = (leader_eid or "").strip()
            if leader_eid_n:
                leader_reg = registrations_repo.get_by_employee_id(leader_eid_n)
                if leader_reg and leader_reg.tg_id:
                    if not notification_queue_repo.exists_audit_notice_by_business_key(
                        shift_id=shift_id,
                        work_date=work_date,
                        notify_tg_id=int(leader_reg.tg_id),
                        template_id=TEMPLATE_AUDIT_SHIFT_START_LEADER_DM_NOTICE,
                    ):
                        # 复用 3003 的统计结果（简化：只给人数 + 名单）
                        win = audit_rules.compute_checkin_window_utc(
                            target_work_date=work_date,
                            shift_checkin_time=shift.checkin_time,
                            timezone_name=shift.timezone,
                            attendance_flex_interval=shift.attendance_flex_interval,
                        )
                        should_count = len(regs)
                        checked_in_count = 0
                        on_leave_people: List[PersonDisplay] = []
                        on_leave_eids: List[str] = []
                        not_clocked_list: List[PersonDisplay] = []
                        for r in regs:
                            clocks = _clock_times_in_window(
                                employee_id=r.employee_id,
                                shift_id=int(shift.id),
                                start_utc=win.start_utc,
                                end_utc=win.end_utc,
                            )
                            is_leave = effective_leave_days_repo.exists_leave_day(
                                employee_id=r.employee_id,
                                shift_id=int(shift.id),
                                leave_date=work_date,
                            )
                            instant_utc = _stage_instant_for_leave_check_utc(
                                work_date=work_date, shift=shift, stage=AUDIT_STAGE_CHECKIN
                            )
                            is_temp = effective_temporary_leaves_repo.exists_covering_instant(
                                employee_id=r.employee_id,
                                shift_id=int(shift.id),
                                instant_utc=instant_utc,
                            )
                            decision = audit_rules.decide_checkin(
                                now_utc=now,
                                target_work_date=work_date,
                                shift_checkin_time=shift.checkin_time,
                                timezone_name=shift.timezone,
                                attendance_flex_interval=shift.attendance_flex_interval,
                                max_late_early_tolerance=shift.max_late_early_tolerance,
                                is_on_leave=is_leave,
                                is_temporary_leave_covering=is_temp,
                                is_exempt=False,
                                window_clock_times_utc=clocks,
                            )
                            p = PersonDisplay(english_name=r.english_name or "", tg_username=r.tg_username)
                            if decision.result in (audit_rules.AUDIT_RESULT_NORMAL, audit_rules.AUDIT_RESULT_LATE):
                                checked_in_count += 1
                            if decision.result == audit_rules.AUDIT_RESULT_ON_LEAVE:
                                on_leave_people.append(p)
                                if r.employee_id:
                                    on_leave_eids.append(str(r.employee_id))
                            if decision.result in (audit_rules.AUDIT_RESULT_NONE, audit_rules.AUDIT_RESULT_ABSENT):
                                not_clocked_list.append(p)
                        # 组长私信：报备休息名单需要“审批人+审批时间”
                        leave_lines: list[LeaveLineDisplay] = []
                        if on_leave_people:
                            # 只在当日生效表里找 application_id，再回查审批任务表拿 approved_at/approver
                            leave_day_rows = effective_leave_days_repo.list_leave_days_for_shift_date(
                                shift_id=int(shift.id),
                                leave_date=work_date,
                                employee_ids=on_leave_eids,
                            )
                            app_by_eid = {eid: app_id for eid, app_id in leave_day_rows}
                            for r in regs:
                                if not r.employee_id or r.employee_id not in app_by_eid:
                                    continue
                                app_id = app_by_eid[r.employee_id]
                                meta = approval_task_queue_repo.get_latest_leave_approval_meta_by_application_id(application_id=int(app_id))
                                if meta:
                                    approver_eid, approved_at_utc = meta
                                    approver_reg = registrations_repo.get_by_employee_id(str(approver_eid))
                                    approver_html = (
                                        person_display_html(
                                            english_name=approver_reg.english_name if approver_reg else None,
                                            tg_username=approver_reg.tg_username if approver_reg else None,
                                            missing_name_fallback="（审批人未填英文名）",
                                        )
                                        if approver_reg
                                        else "（审批人未注册）"
                                    )
                                    approved_at_local = format_utc_in_shift_timezone(
                                        approved_at_utc, timezone_name=shift.timezone
                                    )
                                else:
                                    approver_html = "（审批信息缺失）"
                                    approved_at_local = "（审批时间缺失）"
                                leave_lines.append(
                                    LeaveLineDisplay(
                                        person=PersonDisplay(english_name=r.english_name or "", tg_username=r.tg_username),
                                        approver=approver_html,
                                        approved_at_local=str(approved_at_local),
                                    )
                                )

                        reply = build_shift_start_leader_dm_html(
                            timezone_name=shift.timezone,
                            shift_label=_shift_label(shift=shift),
                            should_count=should_count,
                            checked_in_count=checked_in_count,
                            on_leave_lines=leave_lines,
                            not_clocked=not_clocked_list,
                        )
                        inserted = _enqueue_audit_notice(
                            template_id=TEMPLATE_AUDIT_SHIFT_START_LEADER_DM_NOTICE,
                            notify_tg_id=int(leader_reg.tg_id),
                            shift_id=shift_id,
                            work_date=work_date,
                            reply_content=reply,
                            now_utc=now,
                        )
                        out["3004"] = "enqueued" if inserted else "exists"
                        log.info(
                            "audit_notice template_id=%s shift_id=%s work_date=%s notify_tg_id=%s outcome=%s",
                            TEMPLATE_AUDIT_SHIFT_START_LEADER_DM_NOTICE,
                            shift_id,
                            work_date,
                            int(leader_reg.tg_id),
                            out["3004"],
                        )
                    else:
                        out["3004"] = "exists"
                        log.info(
                            "audit_notice template_id=%s shift_id=%s work_date=%s notify_tg_id=%s outcome=exists_skip",
                            TEMPLATE_AUDIT_SHIFT_START_LEADER_DM_NOTICE,
                            shift_id,
                            work_date,
                            int(leader_reg.tg_id),
                        )
                else:
                    out["3004"] = "blocked_leader_not_registered_or_no_tg"
                    log.info(
                        "audit_notice template_id=%s shift_id=%s work_date=%s outcome=skip reason=%s leader_employee_id=%s",
                        TEMPLATE_AUDIT_SHIFT_START_LEADER_DM_NOTICE,
                        shift_id,
                        work_date,
                        out["3004"],
                        leader_eid_n,
                    )
            else:
                out["3004"] = "blocked_no_leader_employee_id"
                log.info(
                    "audit_notice template_id=%s shift_id=%s work_date=%s outcome=skip reason=%s org_id=%s",
                    TEMPLATE_AUDIT_SHIFT_START_LEADER_DM_NOTICE,
                    shift_id,
                    work_date,
                    out["3004"],
                    org_id,
                )
        else:
            out["3004"] = "blocked_no_org_id"
            log.info(
                "audit_notice template_id=%s shift_id=%s work_date=%s outcome=skip reason=%s",
                TEMPLATE_AUDIT_SHIFT_START_LEADER_DM_NOTICE,
                shift_id,
                work_date,
                out["3004"],
            )

    # 3005：部门负责人跨组汇总（一期：按 highest_responsible_employee_id 聚合）
    if not _is_time_reached(now_utc=now, target_local=checkin_center_local):
        out["3005"] = "skip_not_time_reached"
        log.info(
            "audit_notice template_id=%s shift_id=%s work_date=%s outcome=skip reason=%s",
            TEMPLATE_AUDIT_SHIFT_START_DEPARTMENT_HEAD_NOTICE,
            shift_id,
            work_date,
            out["3005"],
        )
    else:
        regs_all = registrations_repo.list_by_shift_id(shift_id=shift_id)
        org_ids_in_shift = sorted({int(r.organization_id) for r in regs_all if r.organization_id is not None})
        org_rows_in_shift = organizations_repo.list_by_ids(organization_ids=org_ids_in_shift)
        highest_ids = sorted(
            {str(o.highest_responsible_employee_id).strip() for o in org_rows_in_shift if o.highest_responsible_employee_id}
        )
        org_rows_all = organizations_repo.list_by_highest_responsible_employee_ids(
            highest_responsible_employee_ids=highest_ids
        )

        # highest -> organizations
        by_highest: dict[str, list[organizations_repo.OrganizationRow]] = {}
        for o in org_rows_all:
            hid = (o.highest_responsible_employee_id or "").strip()
            if not hid:
                continue
            by_highest.setdefault(hid, []).append(o)

        blocked_heads: list[str] = []
        sent_heads: int = 0
        total_groups: int = 0

        win = audit_rules.compute_checkin_window_utc(
            target_work_date=work_date,
            shift_checkin_time=shift.checkin_time,
            timezone_name=shift.timezone,
            attendance_flex_interval=shift.attendance_flex_interval,
        )

        for hid, orgs in by_highest.items():
            head_reg = registrations_repo.get_by_employee_id(hid)
            notify_tg_id = int(head_reg.tg_id) if (head_reg and getattr(head_reg, "tg_id", None)) else None
            if not notify_tg_id:
                blocked_heads.append(hid)
                log.info(
                    "audit_notice template_id=%s shift_id=%s work_date=%s department_head_employee_id=%s outcome=blocked reason=blocked_no_tg_id",
                    TEMPLATE_AUDIT_SHIFT_START_DEPARTMENT_HEAD_NOTICE,
                    shift_id,
                    work_date,
                    hid,
                )
                continue

            if notification_queue_repo.exists_audit_notice_by_business_key(
                shift_id=shift_id,
                work_date=work_date,
                notify_tg_id=notify_tg_id,
                template_id=TEMPLATE_AUDIT_SHIFT_START_DEPARTMENT_HEAD_NOTICE,
            ):
                log.info(
                    "audit_notice template_id=%s shift_id=%s work_date=%s department_head_employee_id=%s notify_tg_id=%s outcome=exists_skip",
                    TEMPLATE_AUDIT_SHIFT_START_DEPARTMENT_HEAD_NOTICE,
                    shift_id,
                    work_date,
                    hid,
                    notify_tg_id,
                )
                continue

            head_name_html = (
                person_display_html(
                    english_name=head_reg.english_name if head_reg else None,
                    tg_username=head_reg.tg_username if head_reg else None,
                    missing_name_fallback="（未填英文名）",
                )
                if head_reg
                else "（未注册）"
            )

            # department_name 展示：取该部门下任意一个 organization 的 department_name（不作为聚合键）
            dept_name = next((o.department_name for o in orgs if (o.department_name or "").strip()), "") or "未配置"

            group_lines: list[DepartmentGroupSummaryLine] = []
            for o in orgs:
                members = [r for r in regs_all if r.organization_id is not None and int(r.organization_id) == int(o.id)]
                expected = len(members)
                present = 0
                leave_count = 0
                not_clocked = 0

                for m in members:
                    clocks = _clock_times_in_window(
                        employee_id=m.employee_id,
                        shift_id=int(shift.id),
                        start_utc=win.start_utc,
                        end_utc=win.end_utc,
                    )
                    is_leave = effective_leave_days_repo.exists_leave_day(
                        employee_id=m.employee_id,
                        shift_id=int(shift.id),
                        leave_date=work_date,
                    )
                    instant_utc = _stage_instant_for_leave_check_utc(
                        work_date=work_date, shift=shift, stage=AUDIT_STAGE_CHECKIN
                    )
                    is_temp = effective_temporary_leaves_repo.exists_covering_instant(
                        employee_id=m.employee_id,
                        shift_id=int(shift.id),
                        instant_utc=instant_utc,
                    )
                    decision = audit_rules.decide_checkin(
                        now_utc=now,
                        target_work_date=work_date,
                        shift_checkin_time=shift.checkin_time,
                        timezone_name=shift.timezone,
                        attendance_flex_interval=shift.attendance_flex_interval,
                        max_late_early_tolerance=shift.max_late_early_tolerance,
                        is_on_leave=is_leave,
                        is_temporary_leave_covering=is_temp,
                        is_exempt=False,
                        window_clock_times_utc=clocks,
                    )
                    if decision.result in (audit_rules.AUDIT_RESULT_NORMAL, audit_rules.AUDIT_RESULT_LATE):
                        present += 1
                    if decision.result == audit_rules.AUDIT_RESULT_ON_LEAVE:
                        leave_count += 1
                    if decision.result in (audit_rules.AUDIT_RESULT_NONE, audit_rules.AUDIT_RESULT_ABSENT):
                        not_clocked += 1

                leader_eid = (o.leader_employee_id or "").strip()
                leader_reg = registrations_repo.get_by_employee_id(leader_eid) if leader_eid else None
                leader_name_html = (
                    person_display_html(
                        english_name=leader_reg.english_name if leader_reg else None,
                        tg_username=leader_reg.tg_username if leader_reg else None,
                        missing_name_fallback=("（未注册）" if not leader_reg else "（未填英文名）"),
                    )
                    if leader_reg or leader_eid
                    else "（组长未配置）"
                )
                group_name_html = f"{leader_name_html}组"
                group_lines.append(
                    DepartmentGroupSummaryLine(
                        group_name_html=group_name_html,
                        expected_count=expected,
                        present_count=present,
                        leave_count=leave_count,
                        not_clocked_count=not_clocked,
                    )
                )

            total_groups += len(group_lines)
            msg = build_shift_start_department_head_dm_html(
                department_head_name_html=head_name_html,
                department_name=dept_name,
                shift_label=_shift_label(shift=shift),
                timezone_name=shift.timezone,
                groups=group_lines,
            )
            inserted = _enqueue_audit_notice(
                template_id=TEMPLATE_AUDIT_SHIFT_START_DEPARTMENT_HEAD_NOTICE,
                notify_tg_id=notify_tg_id,
                shift_id=shift_id,
                work_date=work_date,
                reply_content=msg,
                now_utc=now,
            )
            sent_heads += 1 if inserted else 0
            log.info(
                "audit_notice template_id=%s shift_id=%s work_date=%s department_head_employee_id=%s notify_tg_id=%s outcome=%s groups=%s",
                TEMPLATE_AUDIT_SHIFT_START_DEPARTMENT_HEAD_NOTICE,
                shift_id,
                work_date,
                hid,
                notify_tg_id,
                ("enqueued" if inserted else "exists_skip"),
                len(group_lines),
            )

        out["3005"] = f"heads={len(by_highest)} enqueued_or_exists={sent_heads} blocked_no_tg_id={len(blocked_heads)} groups={total_groups}"
        if blocked_heads:
            out["3005_blocked_heads"] = ",".join(blocked_heads[:50])

    # 3006：下班群提醒（已关闭，避免与 3003 在同一时刻重复刷屏）
    out["3006"] = "disabled"

    return out

