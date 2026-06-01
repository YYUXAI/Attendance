from __future__ import annotations

import html
import logging
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Dict, Optional, Tuple, Union

from domain.shared.result import ServiceResult
from domain.temporary_leave_rules import (
    compute_logic_work_date,
    local_window_to_utc_start_end,
    parse_hour_minute_dollar,
    validate_temporary_leave_same_day_window,
)
from infra.db import transaction
from repositories import approval_task_queue_repo, notification_queue_repo, organizations_repo, temporary_leave_applications_repo
from repositories import event_logs_repo
from repositories.registrations_repo import get_by_employee_id, get_by_tg_id
from repositories.shifts_repo import get_by_id as get_shift_by_id

log = logging.getLogger(__name__)

APPLICATION_TYPE_TEMPORARY_LEAVE = "TEMPORARY_LEAVE"
TEMPLATE_APPROVAL_DISPATCH_TO_APPROVER = 1001

STATE_WAIT_START = "wait_tleave_start"
STATE_WAIT_END = "wait_tleave_end"
STATE_WAIT_REASON = "wait_tleave_reason"
STATE_WAIT_CONFIRM = "wait_tleave_confirm"

MSG_NOT_PRIVATE = "请在私聊中使用该功能"
MSG_NOT_REGISTERED = "您尚未注册，无法使用离岗报备。"
MSG_NOT_CONFIGURED = "您的组织或班次尚未配置完整，请联系管理员后再使用离岗报备。"
MSG_NO_TIMEZONE = "未找到班次时区配置，请联系管理员。"
MSG_BAD_TIME_FORMAT = "时间格式不正确，请严格按时$分（24小时制）输入，例如：\n16$25"
MSG_EMPTY_REASON = "离岗原因不能为空，请重新输入。"

MSG_NO_LEADER = "当前未配置审批负责人，请联系管理员"
MSG_APPROVER_NOT_READY = "审批负责人尚未完成机器人注册，暂时无法提交申请，请联系管理员"

EVENT_NAME_APPROVAL_NOTIFICATION_TRIGGERED = "APPROVAL_NOTIFICATION_TRIGGERED"
RELATED_NAME_APPROVAL_TASK = "approval_task"


@dataclass
class TemporaryLeaveDraft:
    start_h: Optional[int] = None
    start_m: Optional[int] = None
    end_h: Optional[int] = None
    end_m: Optional[int] = None


@dataclass
class TemporaryLeaveSubmitPayload:
    token: str
    tg_id: int
    employee_id: str
    organization_id: int
    shift_id: int
    shift_timezone: str
    work_date: date
    start_h: int
    start_m: int
    end_h: int
    end_m: int
    leave_reason: str
    english_name: str
    approver_employee_id: str
    approver_confirm_display: str


_tleave_phase: Dict[int, str] = {}
_tleave_draft: Dict[int, TemporaryLeaveDraft] = {}
_pending_submit: Dict[str, TemporaryLeaveSubmitPayload] = {}


def clear_temporary_leave_session(*, tg_id: int) -> None:
    _tleave_phase.pop(tg_id, None)
    _tleave_draft.pop(tg_id, None)
    dead: list[str] = []
    for tok, p in _pending_submit.items():
        if p.tg_id == tg_id:
            dead.append(tok)
    for t in dead:
        _pending_submit.pop(t, None)


def is_temporary_leave_flow_expecting_text(*, tg_id: int) -> bool:
    return _tleave_phase.get(tg_id) in {
        STATE_WAIT_START,
        STATE_WAIT_END,
        STATE_WAIT_REASON,
    }


def get_temporary_leave_phase(*, tg_id: int) -> Optional[str]:
    return _tleave_phase.get(tg_id)


def _ensure_registered_with_org_shift(*, tg_id: int) -> Union[ServiceResult, Tuple[object, object, str]]:
    reg = get_by_tg_id(tg_id)
    if not reg:
        return ServiceResult(ok=False, message=MSG_NOT_REGISTERED, error_code="NOT_REGISTERED")
    if reg.organization_id is None or reg.shift_id is None:
        return ServiceResult(ok=False, message=MSG_NOT_CONFIGURED, error_code="NOT_CONFIGURED")
    shift = get_shift_by_id(int(reg.shift_id))
    if not shift or not shift.timezone:
        return ServiceResult(ok=False, message=MSG_NO_TIMEZONE, error_code="NO_TIMEZONE")
    return reg, shift, str(shift.timezone)


def _leader_employee_id_strict(*, organization_id: int) -> str:
    leader, _h = organizations_repo.get_leader_fields(organization_id)
    return (leader or "").strip()


def _approver_display_for_confirm(*, leader_employee_id: str) -> str:
    if not leader_employee_id:
        return "（未配置负责人）"
    reg = get_by_employee_id(leader_employee_id)
    if not reg:
        return "（未注册）"
    name = (reg.english_name or "").strip()
    if not name:
        return "（未填英文名）"
    return name


def _build_temporary_leave_dispatch_html(
    *,
    applicant_english: str,
    employee_id: str,
    department_name: Optional[str],
    work_date: date,
    start_h: int,
    start_m: int,
    end_h: int,
    end_m: int,
    leave_reason: str,
) -> str:
    dept = department_name if department_name else "未配置"
    name_plain = html.escape((applicant_english or "").strip() or "（未填英文名）")
    dept_e = html.escape(dept)
    reason = html.escape((leave_reason or "").strip())
    wd = html.escape(work_date.strftime("%Y-%m-%d"))
    eid = html.escape(str(employee_id))
    st = html.escape(f"{start_h:02d}:{start_m:02d}")
    et = html.escape(f"{end_h:02d}:{end_m:02d}")
    return (
        f"{name_plain} 申请离岗报备，信息如下：\n\n"
        f"工号：{eid}\n"
        f"部门：{dept_e}\n"
        f"日期：{wd}\n"
        f"离岗时间：{st}-{et}\n"
        f"离岗原因：{reason}\n\n"
        "请审批这条离岗申请"
    )


def begin_temporary_leave_application(*, tg_id: int) -> ServiceResult:
    got = _ensure_registered_with_org_shift(tg_id=tg_id)
    if isinstance(got, ServiceResult):
        return got
    clear_temporary_leave_session(tg_id=tg_id)
    _tleave_phase[tg_id] = STATE_WAIT_START
    _tleave_draft[tg_id] = TemporaryLeaveDraft()
    return ServiceResult(ok=True, message="")


def consume_tleave_start_time(*, tg_id: int, text: str) -> ServiceResult:
    if _tleave_phase.get(tg_id) != STATE_WAIT_START:
        return ServiceResult(ok=False, message="", error_code="SKIP")

    parsed = parse_hour_minute_dollar(text)
    if not parsed:
        return ServiceResult(ok=False, message=MSG_BAD_TIME_FORMAT, error_code="BAD_TIME")

    h, m = parsed
    draft = _tleave_draft.get(tg_id)
    if not draft:
        return ServiceResult(ok=False, message="流程已失效，请重新点击【离岗报备】。", error_code="STALE")

    draft.start_h, draft.start_m = h, m
    _tleave_phase[tg_id] = STATE_WAIT_END
    return ServiceResult(ok=True, message="")


def consume_tleave_end_time(*, tg_id: int, text: str) -> ServiceResult:
    if _tleave_phase.get(tg_id) != STATE_WAIT_END:
        return ServiceResult(ok=False, message="", error_code="SKIP")

    parsed = parse_hour_minute_dollar(text)
    if not parsed:
        return ServiceResult(ok=False, message=MSG_BAD_TIME_FORMAT, error_code="BAD_TIME")

    h, m = parsed
    draft = _tleave_draft.get(tg_id)
    if not draft or draft.start_h is None or draft.start_m is None:
        return ServiceResult(ok=False, message="流程已失效，请重新点击【离岗报备】。", error_code="STALE")

    got = _ensure_registered_with_org_shift(tg_id=tg_id)
    if isinstance(got, ServiceResult):
        return got
    reg, shift, tz_name = got

    now_utc = datetime.now(timezone.utc)
    work_date = compute_logic_work_date(
        now_utc=now_utc,
        timezone_name=tz_name,
        is_overnight=bool(shift.is_overnight),
        checkin_time=shift.checkin_time,
    )
    err = validate_temporary_leave_same_day_window(
        work_date=work_date,
        timezone_name=tz_name,
        is_overnight=bool(shift.is_overnight),
        checkin_time=shift.checkin_time,
        checkout_time=shift.checkout_time,
        start_h=int(draft.start_h),
        start_m=int(draft.start_m),
        end_h=h,
        end_m=m,
    )
    if err:
        return ServiceResult(ok=False, message=err, error_code="WINDOW")

    draft.end_h, draft.end_m = h, m
    _tleave_phase[tg_id] = STATE_WAIT_REASON
    return ServiceResult(ok=True, message="")


def consume_tleave_reason(*, tg_id: int, text: str) -> Tuple[ServiceResult, Optional[str]]:
    if _tleave_phase.get(tg_id) != STATE_WAIT_REASON:
        return ServiceResult(ok=False, message="", error_code="SKIP"), None

    reason = (text or "").strip()
    if not reason:
        return ServiceResult(ok=False, message=MSG_EMPTY_REASON, error_code="EMPTY"), None

    draft = _tleave_draft.get(tg_id)
    if (
        not draft
        or draft.start_h is None
        or draft.start_m is None
        or draft.end_h is None
        or draft.end_m is None
    ):
        return ServiceResult(ok=False, message="流程已失效，请重新点击【离岗报备】。", error_code="STALE"), None

    got = _ensure_registered_with_org_shift(tg_id=tg_id)
    if isinstance(got, ServiceResult):
        return got, None
    reg, shift, tz_name = got

    now_utc = datetime.now(timezone.utc)
    work_date = compute_logic_work_date(
        now_utc=now_utc,
        timezone_name=tz_name,
        is_overnight=bool(shift.is_overnight),
        checkin_time=shift.checkin_time,
    )

    leader_id = _leader_employee_id_strict(organization_id=int(reg.organization_id))
    approver_show = _approver_display_for_confirm(leader_employee_id=leader_id)

    token = secrets.token_urlsafe(16)
    payload = TemporaryLeaveSubmitPayload(
        token=token,
        tg_id=tg_id,
        employee_id=str(reg.employee_id),
        organization_id=int(reg.organization_id),
        shift_id=int(reg.shift_id),
        shift_timezone=tz_name,
        work_date=work_date,
        start_h=int(draft.start_h),
        start_m=int(draft.start_m),
        end_h=int(draft.end_h),
        end_m=int(draft.end_m),
        leave_reason=reason,
        english_name=(reg.english_name or "").strip(),
        approver_employee_id=leader_id,
        approver_confirm_display=approver_show,
    )
    _pending_submit[token] = payload
    _tleave_phase[tg_id] = STATE_WAIT_CONFIRM

    wd_s = work_date.strftime("%Y-%m-%d")
    st_s = f"{payload.start_h:02d}:{payload.start_m:02d}"
    et_s = f"{payload.end_h:02d}:{payload.end_m:02d}"
    applicant_show = (payload.english_name or "").strip() or "（未填英文名）"
    en_e = html.escape(applicant_show)
    eid_e = html.escape(str(payload.employee_id))
    wd_e = html.escape(wd_s)
    st_e = html.escape(st_s)
    et_e = html.escape(et_s)
    reason_e = html.escape(reason)
    appr_e = html.escape(approver_show)

    msg = (
        "请确认您的离岗申请是否正确：\n\n"
        f"申请人：{en_e}\n"
        f"工号：{eid_e}\n"
        f"日期：{wd_e}\n"
        f"离岗时间：{st_e}-{et_e}\n"
        f"离岗原因：{reason_e}\n\n"
        f"如果确认无误，请点击“确认”，随后您的离岗申请将发给 {appr_e} 进行审批，请提醒 TA 留意机器人私信。"
    )
    return ServiceResult(ok=True, message=msg), token


def cancel_temporary_leave_confirm(*, token: str, tg_id: int) -> None:
    _pending_submit.pop(token, None)
    clear_temporary_leave_session(tg_id=tg_id)


def submit_temporary_leave_application(*, token: str, tg_id: int) -> ServiceResult:
    payload = _pending_submit.get(token)
    if not payload or payload.tg_id != tg_id:
        return ServiceResult(ok=False, message="确认已失效，请重新发起离岗报备。", error_code="EXPIRED")

    reg = get_by_tg_id(tg_id)
    if not reg or reg.organization_id is None or reg.shift_id is None:
        return ServiceResult(ok=False, message="您的注册信息已变更，请重新发起申请。", error_code="STALE_REG")

    shift = get_shift_by_id(int(reg.shift_id))
    if not shift or not shift.timezone:
        return ServiceResult(ok=False, message=MSG_NO_TIMEZONE, error_code="NO_TIMEZONE")

    leader_id = _leader_employee_id_strict(organization_id=int(reg.organization_id))
    if not leader_id:
        return ServiceResult(ok=False, message=MSG_NO_LEADER, error_code="NO_LEADER")

    approver_reg = get_by_employee_id(leader_id)
    if not approver_reg or approver_reg.tg_id is None:
        return ServiceResult(ok=False, message=MSG_APPROVER_NOT_READY, error_code="APPROVER_NOT_READY")

    try:
        notify_tg_id = int(approver_reg.tg_id)
    except (TypeError, ValueError):
        return ServiceResult(ok=False, message=MSG_APPROVER_NOT_READY, error_code="APPROVER_NOT_READY")
    if notify_tg_id == 0:
        return ServiceResult(ok=False, message=MSG_APPROVER_NOT_READY, error_code="APPROVER_NOT_READY")

    tz_name = str(shift.timezone)
    err = validate_temporary_leave_same_day_window(
        work_date=payload.work_date,
        timezone_name=tz_name,
        is_overnight=bool(shift.is_overnight),
        checkin_time=shift.checkin_time,
        checkout_time=shift.checkout_time,
        start_h=payload.start_h,
        start_m=payload.start_m,
        end_h=payload.end_h,
        end_m=payload.end_m,
    )
    if err:
        return ServiceResult(ok=False, message=err, error_code="WINDOW")

    start_at_utc, end_at_utc = local_window_to_utc_start_end(
        work_date=payload.work_date,
        timezone_name=tz_name,
        start_h=payload.start_h,
        start_m=payload.start_m,
        end_h=payload.end_h,
        end_m=payload.end_m,
    )

    if str(reg.employee_id) != payload.employee_id or int(reg.organization_id) != payload.organization_id or int(reg.shift_id) != payload.shift_id:
        return ServiceResult(ok=False, message="您的注册信息已变更，请重新发起申请。", error_code="STALE_REG")

    if leader_id != payload.approver_employee_id:
        return ServiceResult(ok=False, message="组织审批负责人已变更，请重新发起离岗报备。", error_code="STALE_APPROVER")

    created_at = datetime.now(timezone.utc)
    task_created_at = datetime.now(timezone.utc)

    dept = organizations_repo.get_department_name_by_id(int(reg.organization_id))
    dispatch_html = _build_temporary_leave_dispatch_html(
        applicant_english=(reg.english_name or "") or "",
        employee_id=str(reg.employee_id),
        department_name=dept,
        work_date=payload.work_date,
        start_h=payload.start_h,
        start_m=payload.start_m,
        end_h=payload.end_h,
        end_m=payload.end_m,
        leave_reason=payload.leave_reason,
    )

    try:
        with transaction() as cur:
            app_id, app_created_at = temporary_leave_applications_repo.insert_submitted(
                cur,
                employee_id=str(reg.employee_id),
                organization_id=int(reg.organization_id),
                shift_id=int(reg.shift_id),
                start_at_utc=start_at_utc,
                end_at_utc=end_at_utc,
                leave_reason=payload.leave_reason,
                created_at_utc=created_at,
            )

            task_id = approval_task_queue_repo.insert_approval_task_returning_id(
                cur,
                application_type=APPLICATION_TYPE_TEMPORARY_LEAVE,
                application_id=int(app_id),
                application_submitted_at=app_created_at,
                approval_level=1,
                applicant_employee_id=str(reg.employee_id),
                approver_employee_id=leader_id,
                task_status="PENDING",
                approval_result="NONE",
                task_created_at_utc=task_created_at,
            )

            n_up = temporary_leave_applications_repo.update_status_submitted_to_approving(cur, application_id=int(app_id))
            if n_up != 1:
                raise RuntimeError("temporary_leave application status transition failed")

            log_id = event_logs_repo.insert_notification_triggered(
                cur,
                event_name=EVENT_NAME_APPROVAL_NOTIFICATION_TRIGGERED,
                related_event_name=RELATED_NAME_APPROVAL_TASK,
                related_event_id=int(task_id),
                created_at_utc=created_at,
            )
            notification_queue_repo.insert_pending_notification(
                cur,
                log_id=int(log_id),
                notify_tg_id=int(notify_tg_id),
                template_id=TEMPLATE_APPROVAL_DISPATCH_TO_APPROVER,
                reply_content=dispatch_html,
                attachment_id=None,
                created_at_utc=created_at,
            )
    except Exception:
        log.exception("submit_temporary_leave_application failed")
        return ServiceResult(ok=False, message="提交失败，请稍后重试或联系管理员。", error_code="DB_ERROR")

    _pending_submit.pop(token, None)
    clear_temporary_leave_session(tg_id=tg_id)
    return ServiceResult(ok=True, message="您的离岗申请已提交，等待审批。")
