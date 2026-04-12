from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo
from urllib.parse import quote
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from domain.shared.result import ServiceResult
from domain.shared.person_html import person_display_html
from infra.db import transaction
from repositories import approval_task_queue_repo, effective_leave_days_repo, effective_temporary_leaves_repo
from repositories import leave_applications_repo, notification_queue_repo, organizations_repo
from repositories import temporary_leave_applications_repo, temporary_qc_exemption_list_repo
from repositories import event_logs_repo
from repositories.leave_applications_repo import LeaveApplicationRow
from repositories.registrations_repo import get_by_employee_id, get_by_tg_id
from repositories.shifts_repo import get_by_id as get_shift_by_id
from services.leave_calendar_utils import (
    format_utc_in_shift_timezone,
    iter_leave_dates_in_shift_timezone,
    leave_span_calendar_day_count,
)

log = logging.getLogger(__name__)


def _temporary_leave_instant_as_utc_aware(value: Any) -> datetime:
    """
    将 start_at/end_at 与 now(UTC) 对齐为同一语义后再比较。
    - naive datetime：按 UTC 解释（与“库存 UTC”口径一致，避免与 utcnow 比较报错或误判）。
    - 已带 tzinfo：归一化到 UTC。
    """
    if not isinstance(value, datetime):
        raise TypeError(f"temporary_leave time field expected datetime, got {type(value)!r}")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


APPLICATION_TYPE_LEAVE = "LEAVE"
APPLICATION_TYPE_TEMPORARY_LEAVE = "TEMPORARY_LEAVE"

MSG_TEMPORARY_LEAVE_ALREADY_HANDLED = "该申请已处理，请勿重复操作"
MSG_TEMPORARY_LEAVE_EXPIRED = "该离岗申请已过期，无法审批"
MSG_TLEAVE_APPROVER_REMARK_PROMPT = "请输入您的审批理由，输入 /null 可跳过"

TEMPLATE_APPROVAL_DISPATCH_TO_APPROVER = 1001
TEMPLATE_APPROVAL_RESULT_TO_APPLICANT = 1002
TEMPLATE_APPROVAL_APPROVED_GROUP_NOTICE = 1003

TASK_PENDING = "PENDING"
TASK_PROCESSING = "PROCESSING"
TASK_APPROVED_DONE = "APPROVED_DONE"
TASK_REJECTED_DONE = "REJECTED_DONE"

RESULT_APPROVED = "APPROVED"
RESULT_REJECTED = "REJECTED"

DECISION_APPROVED = "APPROVED"
DECISION_REJECTED = "REJECTED"

_dispatch_lock = asyncio.Lock()

_pending_remark: Dict[int, "ApprovalRemarkDraft"] = {}


@dataclass
class ApprovalRemarkDraft:
    task_id: int
    application_id: int
    approver_employee_id: str
    pending_decision: str
    application_type: str = APPLICATION_TYPE_LEAVE


def has_pending_approval_remark(*, tg_id: int) -> bool:
    return tg_id in _pending_remark


def pop_pending_approval_remark(*, tg_id: int) -> Optional[ApprovalRemarkDraft]:
    return _pending_remark.pop(tg_id, None)


def get_pending_approval_remark(*, tg_id: int) -> Optional[ApprovalRemarkDraft]:
    return _pending_remark.get(tg_id)


def clear_pending_approval_remark(*, tg_id: int) -> None:
    _pending_remark.pop(tg_id, None)


def set_pending_approval_remark(*, tg_id: int, draft: ApprovalRemarkDraft) -> None:
    _pending_remark[tg_id] = draft


def _resolved_attendance_group_notify_tg_id(raw: object) -> Optional[int]:
    """None、空串、0 视为无效群通知目标。"""
    if raw is None:
        return None
    if isinstance(raw, str) and not raw.strip():
        return None
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return None
    if n == 0:
        return None
    return n


def _temporary_leave_work_date_and_times(
    *,
    start_at_utc: Any,
    end_at_utc: Any,
    timezone_name: str,
) -> tuple[str, str, str]:
    tz = ZoneInfo(timezone_name)
    s = start_at_utc.astimezone(tz)
    e = end_at_utc.astimezone(tz)
    return s.strftime("%Y-%m-%d"), s.strftime("%H:%M"), e.strftime("%H:%M")


def _english_plain_from_registration(reg: object | None) -> str:
    if not reg:
        return "（未填英文名）"
    name = (getattr(reg, "english_name", None) or "").strip()
    return name if name else "（未填英文名）"


def _build_temporary_leave_applicant_result_html(
    *,
    work_date_s: str,
    start_hhmm: str,
    end_hhmm: str,
    leave_reason: str,
    approved: bool,
    approver_remark_display: str,
) -> str:
    wd = html.escape(work_date_s)
    st = html.escape(start_hhmm)
    et = html.escape(end_hhmm)
    lr = html.escape((leave_reason or "").strip() or "（无）")
    ar = html.escape(approver_remark_display)
    result_cn = "通过" if approved else "驳回"
    return (
        "您的离岗申请：\n"
        "\"\n"
        f"日期：{wd}\n"
        f"离岗时间：{st}-{et}\n"
        f"离岗原因：{lr}\n"
        "\"\n"
        f"审批结果为：{result_cn}\n"
        f"审批理由：{ar}"
    )


def _build_temporary_leave_group_notice_html(
    *,
    applicant_english_name: str,
    employee_id: str,
    department_name: str,
    work_date_s: str,
    start_hhmm: str,
    end_hhmm: str,
    leave_reason: str,
    approver_english_name: str,
) -> str:
    en = html.escape((applicant_english_name or "").strip() or "（未填英文名）")
    eid = html.escape(str(employee_id))
    dept = html.escape(department_name or "未配置")
    wd = html.escape(work_date_s)
    st = html.escape(start_hhmm)
    et = html.escape(end_hhmm)
    lr = html.escape((leave_reason or "").strip() or "（无）")
    ap = html.escape((approver_english_name or "").strip() or "（未填英文名）")
    return (
        "离岗报备公告\n\n"
        f"姓名：{en}\n"
        f"工号：{eid}\n"
        f"部门：{dept}\n"
        f"日期：{wd}\n"
        f"离岗时间：{st}-{et}\n"
        f"离岗原因：{lr}\n\n"
        f"审批人：{ap}"
    )


def _enqueue_temporary_leave_post_approval_notifications(
    *,
    draft: ApprovalRemarkDraft,
    approved: bool,
    remark_for_db: Optional[str],
    now_utc: datetime,
) -> None:
    app = temporary_leave_applications_repo.get_by_id(application_id=draft.application_id)
    if not app:
        log.warning("tleave post-approval notify skip missing application id=%s", draft.application_id)
        return
    shift = get_shift_by_id(int(app.shift_id))
    if not shift or not shift.timezone:
        log.warning("tleave post-approval notify skip missing shift tz application_id=%s", draft.application_id)
        return
    tz_name = str(shift.timezone)
    work_date_s, st_s, et_s = _temporary_leave_work_date_and_times(
        start_at_utc=app.start_at,
        end_at_utc=app.end_at,
        timezone_name=tz_name,
    )
    dept_name = organizations_repo.get_department_name_by_id(int(app.organization_id))
    dept_s = dept_name if dept_name else "未配置"
    applicant = get_by_employee_id(app.employee_id)
    approver_reg = get_by_employee_id(draft.approver_employee_id)

    if remark_for_db is None:
        remark_show = "无"
    else:
        remark_show = (remark_for_db.strip() or "无")

    applicant_html = _build_temporary_leave_applicant_result_html(
        work_date_s=work_date_s,
        start_hhmm=st_s,
        end_hhmm=et_s,
        leave_reason=app.leave_reason,
        approved=approved,
        approver_remark_display=remark_show,
    )

    if applicant and applicant.tg_id:
        try:
            with transaction() as cur:
                log_id = event_logs_repo.insert_notification_triggered(
                    cur,
                    related_event_name="approval_task",
                    related_event_id=int(draft.task_id),
                    created_at_utc=now_utc,
                )
                notification_queue_repo.insert_pending_notification(
                    cur,
                    log_id=int(log_id),
                    notify_tg_id=int(applicant.tg_id),
                    template_id=TEMPLATE_APPROVAL_RESULT_TO_APPLICANT,
                    reply_content=applicant_html,
                    attachment_id=None,
                    created_at_utc=now_utc,
                )
        except Exception:
            log.exception(
                "tleave enqueue applicant result notify failed task_id=%s application_id=%s",
                draft.task_id,
                draft.application_id,
            )

    if not approved:
        return

    group_tg_id = _resolved_attendance_group_notify_tg_id(shift.attendance_group_id)
    if group_tg_id is None:
        log.warning(
            "tleave skip group notice application_id=%s shift_id=%s raw_attendance_group_id=%r",
            draft.application_id,
            app.shift_id,
            shift.attendance_group_id,
        )
        return

    group_html = _build_temporary_leave_group_notice_html(
        applicant_english_name=_english_plain_from_registration(applicant),
        employee_id=str(app.employee_id),
        department_name=dept_s,
        work_date_s=work_date_s,
        start_hhmm=st_s,
        end_hhmm=et_s,
        leave_reason=app.leave_reason,
        approver_english_name=_english_plain_from_registration(approver_reg),
    )
    try:
        with transaction() as cur:
            log_id = event_logs_repo.insert_notification_triggered(
                cur,
                related_event_name="approval_task",
                related_event_id=int(draft.task_id),
                created_at_utc=now_utc,
            )
            notification_queue_repo.insert_pending_notification(
                cur,
                log_id=int(log_id),
                notify_tg_id=int(group_tg_id),
                template_id=TEMPLATE_APPROVAL_APPROVED_GROUP_NOTICE,
                reply_content=group_html,
                attachment_id=None,
                created_at_utc=now_utc,
            )
    except Exception:
        log.exception(
            "tleave enqueue group notice failed task_id=%s application_id=%s",
            draft.task_id,
            draft.application_id,
        )


def _finalize_temporary_leave_approval_in_transaction(
    *,
    draft: ApprovalRemarkDraft,
    remark_text: str,
) -> ServiceResult:
    now = datetime.now(timezone.utc)
    approved = draft.pending_decision == DECISION_APPROVED
    approval_result = RESULT_APPROVED if approved else RESULT_REJECTED
    task_done = TASK_APPROVED_DONE if approved else TASK_REJECTED_DONE
    remark_for_db: Optional[str] = remark_text if remark_text else None

    try:
        with transaction() as cur:
            task = approval_task_queue_repo.get_by_id_cur(cur, task_id=draft.task_id)
            if (
                not task
                or task.application_type != APPLICATION_TYPE_TEMPORARY_LEAVE
                or task.task_status != TASK_PROCESSING
                or task.approval_result != "NONE"
            ):
                return ServiceResult(ok=False, message=MSG_TEMPORARY_LEAVE_ALREADY_HANDLED, error_code="STALE")

            if task.approver_employee_id != draft.approver_employee_id:
                return ServiceResult(ok=False, message="您不是该申请的审批人。", error_code="FORBIDDEN")

            app = temporary_leave_applications_repo.get_by_id_cur(cur, application_id=draft.application_id)
            if not app or app.status != "APPROVING":
                return ServiceResult(ok=False, message=MSG_TEMPORARY_LEAVE_ALREADY_HANDLED, error_code="STALE")

            shift = get_shift_by_id(int(app.shift_id))
            if not shift or not shift.timezone:
                return ServiceResult(ok=False, message="班次时区缺失，无法完成审批。", error_code="NO_TIMEZONE")

            if not approved:
                n_task = approval_task_queue_repo.finalize_leave_task(
                    cur,
                    task_id=draft.task_id,
                    approval_result=approval_result,
                    task_status_done=task_done,
                    approver_remark=remark_for_db,
                    approved_at_utc=now,
                )
                if n_task != 1:
                    return ServiceResult(ok=False, message=MSG_TEMPORARY_LEAVE_ALREADY_HANDLED, error_code="STALE")
                n_app = temporary_leave_applications_repo.update_rejected_from_approving(
                    cur,
                    application_id=draft.application_id,
                    completed_at_utc=now,
                )
                if n_app != 1:
                    raise RuntimeError("temporary_leave reject update affected 0 rows")
            else:
                start_u = _temporary_leave_instant_as_utc_aware(app.start_at)
                end_u = _temporary_leave_instant_as_utc_aware(app.end_at)
                now_u = now

                cond_expired = now_u >= end_u
                cond_early = now_u < start_u
                cond_in_effective_window = (not cond_expired) and (not cond_early)

                if cond_expired:
                    branch = "expired_before_finalize"
                elif cond_early:
                    branch = "approve_early_no_effective"
                else:
                    branch = "approve_in_window_insert_effective"

                log.info(
                    "tleave_finalize_window application_id=%s task_id=%s shift_id=%s shift_tz=%r "
                    "now_utc=%s start_at_raw=%r end_at_raw=%r start_at_utc=%s end_at_utc=%s "
                    "cond_now_ge_end=%s cond_now_lt_start=%s cond_in_effective_window=%s branch=%s",
                    draft.application_id,
                    draft.task_id,
                    int(app.shift_id),
                    getattr(shift, "timezone", None),
                    now_u.isoformat(),
                    app.start_at,
                    app.end_at,
                    start_u.isoformat(),
                    end_u.isoformat(),
                    cond_expired,
                    cond_early,
                    cond_in_effective_window,
                    branch,
                )

                if cond_expired:
                    log.info(
                        "tleave_finalize_skip_effective reason=expired application_id=%s task_id=%s",
                        draft.application_id,
                        draft.task_id,
                    )
                    return ServiceResult(ok=False, message=MSG_TEMPORARY_LEAVE_EXPIRED, error_code="EXPIRED")

                n_task = approval_task_queue_repo.finalize_leave_task(
                    cur,
                    task_id=draft.task_id,
                    approval_result=approval_result,
                    task_status_done=task_done,
                    approver_remark=remark_for_db,
                    approved_at_utc=now,
                )
                if n_task != 1:
                    return ServiceResult(ok=False, message=MSG_TEMPORARY_LEAVE_ALREADY_HANDLED, error_code="STALE")

                if cond_early:
                    log.info(
                        "tleave_finalize_skip_insert_effective reason=now_before_start application_id=%s task_id=%s",
                        draft.application_id,
                        draft.task_id,
                    )
                    n_app = temporary_leave_applications_repo.update_approved_from_approving(
                        cur,
                        application_id=draft.application_id,
                        completed_at_utc=None,
                    )
                    if n_app != 1:
                        raise RuntimeError("temporary_leave approve update affected 0 rows")
                else:
                    tz_name = str(shift.timezone)
                    eff_date = start_u.astimezone(ZoneInfo(tz_name)).date()
                    reason_rm = (app.leave_reason or "").strip() or None
                    n_app = temporary_leave_applications_repo.update_approved_from_approving(
                        cur,
                        application_id=draft.application_id,
                        completed_at_utc=None,
                    )
                    if n_app != 1:
                        raise RuntimeError("temporary_leave approve update affected 0 rows")
                    log.info(
                        "tleave_insert_effective_row_begin application_id=%s task_id=%s employee_id=%s "
                        "shift_id=%s effective_date=%s leave_start_at=%s leave_end_at=%s application_id_fk=%s "
                        "reason_remark=%r",
                        draft.application_id,
                        draft.task_id,
                        app.employee_id,
                        int(app.shift_id),
                        eff_date,
                        start_u.isoformat(),
                        end_u.isoformat(),
                        draft.application_id,
                        reason_rm,
                    )
                    effective_row_id = effective_temporary_leaves_repo.insert_effective_row(
                        cur,
                        employee_id=app.employee_id,
                        effective_date=eff_date,
                        shift_id=int(app.shift_id),
                        reason_remark=reason_rm,
                        leave_start_at=start_u,
                        leave_end_at=end_u,
                        application_id=draft.application_id,
                    )
                    log.info(
                        "tleave_insert_effective_row_done application_id=%s effective_temporary_leave_id=%s",
                        draft.application_id,
                        effective_row_id,
                    )
                    log.info(
                        "temporary_qc_exemption upsert begin source_effective_temporary_leave_id=%s "
                        "employee_id=%s shift_id=%s work_date=%s",
                        effective_row_id,
                        app.employee_id,
                        int(app.shift_id),
                        eff_date,
                    )
                    temporary_qc_exemption_list_repo.upsert_from_effective_row(
                        cur,
                        shift_id=int(app.shift_id),
                        employee_id=app.employee_id,
                        effective_date=eff_date,
                        exemption_start_at=start_u,
                        exemption_end_at=end_u,
                        source_effective_temporary_leave_id=int(effective_row_id),
                        updated_at_utc=now,
                    )
                    n_ef = temporary_leave_applications_repo.update_effective_from_approved(
                        cur,
                        application_id=draft.application_id,
                    )
                    if n_ef != 1:
                        raise RuntimeError("temporary_leave effective update affected 0 rows")

    except Exception as e:
        log.exception(
            "finalize_temporary_leave_approval failed task_id=%s application_id=%s exc_type=%s exc=%r",
            draft.task_id,
            draft.application_id,
            type(e).__name__,
            e,
        )
        return ServiceResult(ok=False, message="审批落库失败，请稍后重试或联系管理员。", error_code="DB_ERROR")

    _enqueue_temporary_leave_post_approval_notifications(
        draft=draft,
        approved=approved,
        remark_for_db=remark_for_db,
        now_utc=now,
    )
    return ServiceResult(ok=True, message="审批已提交。")


def _build_leave_approved_group_announcement_plain_text(
    *,
    leave: LeaveApplicationRow,
    applicant_english_name: str,
    department_name: Optional[str],
    approver_display: str,
    timezone_name: str,
) -> str:
    dates = iter_leave_dates_in_shift_timezone(
        leave.start_at,
        leave.end_at,
        timezone_name=timezone_name,
    )
    if dates:
        sd_s, ed_s = str(dates[0]), str(dates[-1])
        duration_days = len(dates)
    else:
        sd_s, ed_s, duration_days = "?", "?", 0
    # notification_queue 统一按 HTML parse_mode 发送：
    # 这里不引入 HTML 标签，但需要对动态字段 escape，避免用户输入的 <、& 等导致解析失败。
    dept = html.escape(department_name if department_name else "未配置")
    reason_line = html.escape((leave.leave_reason or "").strip() or "（无）")
    en_line = html.escape((applicant_english_name or "").strip() or "（无）")
    approver_show = html.escape((approver_display or "").strip() or "（无）")
    eid = html.escape(str(leave.employee_id))
    sd_s = html.escape(sd_s)
    ed_s = html.escape(ed_s)

    return (
        "休假审批通过通知：\n\n"
        f"英文名：{en_line}\n"
        f"工号：{eid}\n"
        f"部门：{dept}\n"
        f"休假类型：{reason_line}\n"
        f"休假日期：{sd_s} 至 {ed_s}\n"
        f"休假时长：{duration_days}天\n"
        f"审批人：{approver_show}\n\n"
        "该申请已审批通过，并已生效。"
    )


def _person_display_from_registration_or_fallback(
    *,
    reg: object | None,
    missing_reg_fallback: str,
    missing_name_fallback: str,
) -> str:
    """
    对外人员展示统一入口：
    - reg 为 registrations 行对象（需包含 english_name / tg_username）
    - reg 缺失时，不回退到 employee_id 当人名（明确展示原因）
    """
    if not reg:
        return missing_reg_fallback
    return person_display_html(
        english_name=getattr(reg, "english_name", None),
        tg_username=getattr(reg, "tg_username", None),
        missing_name_fallback=missing_name_fallback,
    )


def _build_leave_result_notification_plain_text(
    *,
    leave: LeaveApplicationRow,
    applicant_english_name: str,
    department_name: Optional[str],
    approved: bool,
    approver_remark: Optional[str],
    approver_display: str,
    approved_at_utc: datetime,
    timezone_name: str,
) -> str:
    dates = iter_leave_dates_in_shift_timezone(
        leave.start_at,
        leave.end_at,
        timezone_name=timezone_name,
    )
    if dates:
        sd_s, ed_s = str(dates[0]), str(dates[-1])
        duration_days = len(dates)
    else:
        sd_s, ed_s, duration_days = "?", "?", 0
    dept = html.escape(department_name if department_name else "未配置")
    apply_remark_line = html.escape((leave.remark or "").strip() or "（无）")
    reason_line = html.escape((leave.leave_reason or "").strip() or "（无）")
    approval_remark_line = html.escape((approver_remark or "").strip() or "（无）")
    # approver_display 为“对外人员展示 HTML 片段”（可能是 <a>），这里不再做 escape
    approver_show = (approver_display or "").strip() or "（审批人未配置）"
    result_cn = "同意" if approved else "驳回"
    approved_at_local = html.escape(format_utc_in_shift_timezone(approved_at_utc, timezone_name=timezone_name))
    en_line = html.escape((applicant_english_name or "").strip() or "（无）")
    eid = html.escape(str(leave.employee_id))
    sd_s = html.escape(sd_s)
    ed_s = html.escape(ed_s)

    return (
        "您的休假申请——\n\n"
        f"英文名：{en_line}\n"
        f"工号：{eid}\n"
        f"部门：{dept}\n"
        f"休假类型：{reason_line}\n"
        f"休假日期：{sd_s} 至 {ed_s}\n"
        f"休假时长：{duration_days}天\n"
        f"申请备注：{apply_remark_line}\n\n"
        f"审批结果为：{result_cn}\n"
        f"理由为：{approval_remark_line}\n"
        f"审批人：{approver_show}\n"
        f"审批时间：{approved_at_local}"
    )


def _applicant_headline_html(*, english_name: str, tg_username: Optional[str]) -> str:
    return person_display_html(english_name=english_name, tg_username=tg_username)


def _build_leave_dispatch_html(
    *,
    leave: LeaveApplicationRow,
    applicant_english: str,
    applicant_username: Optional[str],
    department_name: Optional[str],
    duration_days: int,
    start_date_local: date,
    end_date_local: date,
) -> str:
    dept = department_name if department_name else "未配置"
    headline = _applicant_headline_html(english_name=applicant_english, tg_username=applicant_username)
    remark_show = leave.remark if (leave.remark or "").strip() else "（无）"
    en = html.escape(applicant_english or "")
    eid = html.escape(str(leave.employee_id))
    dept_e = html.escape(dept)
    reason = html.escape(leave.leave_reason)
    sd = html.escape(str(start_date_local))
    ed = html.escape(str(end_date_local))
    dur = html.escape(str(duration_days))
    rem = html.escape(remark_show)
    return (
        f"{headline} 申请休假，信息如下：\n\n"
        f"英文名：{en}\n"
        f"工号：{eid}\n"
        f"部门：{dept_e}\n"
        f"休假类型：{reason}\n"
        f"休假日期：{sd} 至 {ed}\n"
        f"休假时长：{dur}天\n"
        f"申请备注：{rem}\n\n"
        "请选择您的审批结果："
    )


def _dispatch_keyboard(*, task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="同意", callback_data=f"leave:apr:{task_id}:Y"),
                InlineKeyboardButton(text="驳回", callback_data=f"leave:apr:{task_id}:N"),
            ],
        ],
    )


async def try_dispatch_task_by_id(*, bot: Bot, task_id: int) -> None:
    """
    派发内核：仅处理 task_status=PENDING 且 application_type=LEAVE；
    发送成功后置 PROCESSING；失败保持 PENDING，仅打日志。
    """
    async with _dispatch_lock:
        task = approval_task_queue_repo.get_by_id(task_id=task_id)
        if not task or task.task_status != TASK_PENDING:
            return
        if task.application_type != APPLICATION_TYPE_LEAVE:
            log.warning(
                "approval_dispatch skip non-LEAVE task_id=%s application_type=%s",
                task_id,
                task.application_type,
            )
            return

        leave = leave_applications_repo.get_by_id(leave_application_id=task.application_id)
        if not leave:
            log.warning("approval_dispatch leave missing task_id=%s application_id=%s", task_id, task.application_id)
            return

        shift = get_shift_by_id(int(leave.shift_id))
        if not shift or not shift.timezone:
            log.warning("approval_dispatch shift missing task_id=%s shift_id=%s", task_id, leave.shift_id)
            return

        applicant_reg = get_by_employee_id(leave.employee_id)
        approver_reg = get_by_employee_id(task.approver_employee_id)
        if not approver_reg:
            log.warning(
                "approval_dispatch approver not registered task_id=%s approver_employee_id=%s",
                task_id,
                task.approver_employee_id,
            )
            return

        dept = organizations_repo.get_department_name_by_id(int(leave.organization_id))
        cal_dates = iter_leave_dates_in_shift_timezone(
            leave.start_at,
            leave.end_at,
            timezone_name=shift.timezone,
        )
        start_local = cal_dates[0] if cal_dates else leave.start_at.date()
        end_local = cal_dates[-1] if cal_dates else start_local
        duration = leave_span_calendar_day_count(
            leave.start_at,
            leave.end_at,
            timezone_name=shift.timezone,
        )
        text = _build_leave_dispatch_html(
            leave=leave,
            applicant_english=(applicant_reg.english_name if applicant_reg else "") or "",
            applicant_username=applicant_reg.tg_username if applicant_reg else None,
            department_name=dept,
            duration_days=duration,
            start_date_local=start_local,
            end_date_local=end_local,
        )

        # docs05：审批派发属于异步通知任务（template_id=1001），不得直接发送。
        now = datetime.now(timezone.utc)
        try:
            with transaction() as cur:
                log_id = event_logs_repo.insert_notification_triggered(
                    cur,
                    related_event_name="approval_task_queue",
                    related_event_id=int(task.id),
                    created_at_utc=now,
                )
                notification_queue_repo.insert_pending_notification(
                    cur,
                    log_id=log_id,
                    notify_tg_id=int(approver_reg.tg_id),
                    template_id=TEMPLATE_APPROVAL_DISPATCH_TO_APPROVER,
                    reply_content=text,
                    attachment_id=None,
                    created_at_utc=now,
                )
                updated = approval_task_queue_repo.update_task_status_to_processing_cur(cur, task_id=task_id)
                if updated == 0:
                    log.warning("approval_dispatch PROCESSING update lost (race) task_id=%s", task_id)
        except Exception:
            log.exception("approval_dispatch enqueue failed task_id=%s", task_id)
            return


async def run_pending_dispatch_poll(*, bot: Bot) -> None:
    pending = approval_task_queue_repo.list_pending_leave_dispatch_tasks(limit=50)
    for row in pending:
        if row.application_type != APPLICATION_TYPE_LEAVE:
            log.info(
                "approval_poll skip unsupported application_type task_id=%s application_type=%s",
                row.id,
                row.application_type,
            )
            continue
        await try_dispatch_task_by_id(bot=bot, task_id=row.id)


async def try_dispatch_after_leave_submit(*, bot: Bot, leave_application_id: int) -> None:
    task_id = approval_task_queue_repo.find_pending_leave_task_id_by_application_id(
        application_id=leave_application_id,
    )
    if task_id is None:
        return
    await try_dispatch_task_by_id(bot=bot, task_id=task_id)


def handle_approve_reject_callback(
    *,
    tg_id: int,
    task_id: int,
    approve: bool,
) -> ServiceResult:
    task = approval_task_queue_repo.get_by_id(task_id=task_id)
    if not task or task.task_status != TASK_PROCESSING or task.application_type != APPLICATION_TYPE_LEAVE:
        return ServiceResult(ok=False, message="该审批任务已失效或已处理。", error_code="STALE")

    reg_user = get_by_tg_id(tg_id)
    if not reg_user or reg_user.employee_id != task.approver_employee_id:
        return ServiceResult(ok=False, message="您不是该申请的审批人。", error_code="FORBIDDEN")

    decision = DECISION_APPROVED if approve else DECISION_REJECTED
    set_pending_approval_remark(
        tg_id=tg_id,
        draft=ApprovalRemarkDraft(
            task_id=task.id,
            application_id=task.application_id,
            approver_employee_id=task.approver_employee_id,
            pending_decision=decision,
        ),
    )
    return ServiceResult(ok=True, message="请输入您的审批理由。输入 /null 可跳过此步骤。")


def handle_temporary_leave_approve_reject_callback(
    *,
    tg_id: int,
    task_id: int,
    approve: bool,
) -> ServiceResult:
    task = approval_task_queue_repo.get_by_id(task_id=task_id)
    if not task or task.application_type != APPLICATION_TYPE_TEMPORARY_LEAVE:
        clear_pending_approval_remark(tg_id=tg_id)
        return ServiceResult(ok=False, message=MSG_TEMPORARY_LEAVE_ALREADY_HANDLED, error_code="STALE")
    if task.task_status != TASK_PROCESSING or task.approval_result != "NONE":
        clear_pending_approval_remark(tg_id=tg_id)
        return ServiceResult(ok=False, message=MSG_TEMPORARY_LEAVE_ALREADY_HANDLED, error_code="STALE")

    reg_user = get_by_tg_id(tg_id)
    if not reg_user or reg_user.employee_id != task.approver_employee_id:
        return ServiceResult(ok=False, message="您不是该申请的审批人。", error_code="FORBIDDEN")

    decision = DECISION_APPROVED if approve else DECISION_REJECTED
    set_pending_approval_remark(
        tg_id=tg_id,
        draft=ApprovalRemarkDraft(
            task_id=task.id,
            application_id=task.application_id,
            approver_employee_id=task.approver_employee_id,
            pending_decision=decision,
            application_type=APPLICATION_TYPE_TEMPORARY_LEAVE,
        ),
    )
    return ServiceResult(ok=True, message=MSG_TLEAVE_APPROVER_REMARK_PROMPT)


def _finalize_leave_approval_in_transaction(
    *,
    draft: ApprovalRemarkDraft,
    remark_text: str,
) -> ServiceResult:
    now = datetime.now(timezone.utc)
    approved = draft.pending_decision == DECISION_APPROVED
    approval_result = RESULT_APPROVED if approved else RESULT_REJECTED
    task_done = TASK_APPROVED_DONE if approved else TASK_REJECTED_DONE
    leave_status = "APPROVED" if approved else "REJECTED"
    remark_for_db: Optional[str] = remark_text if remark_text else None

    try:
        with transaction() as cur:
            leave = leave_applications_repo.get_by_id_cur(cur, leave_application_id=draft.application_id)
            if not leave or leave.status != "APPROVING":
                return ServiceResult(ok=False, message="申请状态已变更，无法完成审批。", error_code="CONFLICT")

            shift = get_shift_by_id(int(leave.shift_id))
            if not shift or not shift.timezone:
                return ServiceResult(ok=False, message="班次时区缺失，无法完成审批。", error_code="NO_TIMEZONE")

            n = approval_task_queue_repo.finalize_leave_task(
                cur,
                task_id=draft.task_id,
                approval_result=approval_result,
                task_status_done=task_done,
                approver_remark=remark_for_db,
                approved_at_utc=now,
            )
            if n == 0:
                return ServiceResult(ok=False, message="审批任务状态已变更，请刷新后重试。", error_code="CONFLICT")

            n_leave = leave_applications_repo.update_status_completed(
                cur,
                leave_application_id=draft.application_id,
                status=leave_status,
                completed_at_utc=now,
            )
            if n_leave == 0:
                raise RuntimeError("leave application update affected 0 rows")

            if approved:
                lr = (leave.leave_reason or "").strip() or None
                ar = (leave.remark or "").strip() or None
                for ld in iter_leave_dates_in_shift_timezone(
                    leave.start_at,
                    leave.end_at,
                    timezone_name=shift.timezone,
                ):
                    effective_leave_days_repo.insert_day(
                        cur,
                        employee_id=leave.employee_id,
                        leave_date=ld,
                        shift_id=int(leave.shift_id),
                        leave_reason=lr,
                        application_remark=ar,
                        application_id=draft.application_id,
                    )

            # docs05：1002 / 1003 可共用同一次触发 log_id
            notify_log_id = event_logs_repo.insert_notification_triggered(
                cur,
                related_event_name="leave_approval_result",
                related_event_id=int(draft.application_id),
                created_at_utc=now,
            )

            approver_reg = get_by_employee_id(draft.approver_employee_id)
            # fallback（明确位置）：审批人未注册 / 已注册但未填英文名
            approver_display = _person_display_from_registration_or_fallback(
                reg=approver_reg,
                missing_reg_fallback="（审批人未注册）",
                missing_name_fallback="（审批人未填英文名）",
            )
            dept_name = organizations_repo.get_department_name_by_id(int(leave.organization_id))

            applicant = get_by_employee_id(leave.employee_id)
            if applicant:
                reply_content = _build_leave_result_notification_plain_text(
                    leave=leave,
                    applicant_english_name=applicant.english_name or "",
                    department_name=dept_name,
                    approved=approved,
                    approver_remark=remark_for_db,
                    approver_display=approver_display,
                    approved_at_utc=now,
                    timezone_name=shift.timezone,
                )
                notification_queue_repo.insert_pending_notification(
                    cur,
                    log_id=notify_log_id,
                    notify_tg_id=int(applicant.tg_id),
                    template_id=TEMPLATE_APPROVAL_RESULT_TO_APPLICANT,
                    reply_content=reply_content,
                    attachment_id=None,
                    created_at_utc=now,
                )

            if approved:
                group_tg_id = _resolved_attendance_group_notify_tg_id(shift.attendance_group_id)
                if group_tg_id is None:
                    log.info(
                        "leave_approval skip group notify application_id=%s shift_id=%s "
                        "reason_type=no_valid_attendance_group_id raw=%r",
                        draft.application_id,
                        leave.shift_id,
                        shift.attendance_group_id,
                    )
                else:
                    applicant_en = (applicant.english_name or "") if applicant else ""
                    group_reply = _build_leave_approved_group_announcement_plain_text(
                        leave=leave,
                        applicant_english_name=applicant_en,
                        department_name=dept_name,
                        approver_display=approver_display,
                        timezone_name=shift.timezone,
                    )
                    notification_queue_repo.insert_pending_notification(
                        cur,
                        log_id=notify_log_id,
                        notify_tg_id=group_tg_id,
                        template_id=TEMPLATE_APPROVAL_APPROVED_GROUP_NOTICE,
                        reply_content=group_reply,
                        attachment_id=None,
                        created_at_utc=now,
                    )
    except Exception:
        log.exception("finalize_leave_approval failed task_id=%s", draft.task_id)
        return ServiceResult(ok=False, message="审批落库失败，请稍后重试或联系管理员。", error_code="DB_ERROR")

    return ServiceResult(ok=True, message="审批已提交。")


def handle_approver_remark_text(*, tg_id: int, text: str) -> ServiceResult:
    draft = get_pending_approval_remark(tg_id=tg_id)
    if not draft:
        return ServiceResult(ok=False, message="", error_code="NO_DRAFT")

    raw = (text or "").strip()
    tl = raw.casefold()
    if tl == "null" or tl == "/null":
        remark = ""
    else:
        remark = raw

    now = datetime.now(timezone.utc)
    if draft.application_type == APPLICATION_TYPE_TEMPORARY_LEAVE and draft.pending_decision == DECISION_APPROVED:
        app_row = temporary_leave_applications_repo.get_by_id(application_id=draft.application_id)
        if not app_row:
            clear_pending_approval_remark(tg_id=tg_id)
            return ServiceResult(ok=False, message=MSG_TEMPORARY_LEAVE_ALREADY_HANDLED, error_code="STALE")
        end_pre = _temporary_leave_instant_as_utc_aware(app_row.end_at)
        if now >= end_pre:
            log.info(
                "tleave_remark_precheck_expired application_id=%s now_utc=%s end_at_raw=%r end_at_utc=%s",
                draft.application_id,
                now.isoformat(),
                app_row.end_at,
                end_pre.isoformat(),
            )
            clear_pending_approval_remark(tg_id=tg_id)
            return ServiceResult(ok=False, message=MSG_TEMPORARY_LEAVE_EXPIRED, error_code="EXPIRED")

    clear_pending_approval_remark(tg_id=tg_id)

    if draft.application_type == APPLICATION_TYPE_TEMPORARY_LEAVE:
        return _finalize_temporary_leave_approval_in_transaction(draft=draft, remark_text=remark)
    return _finalize_leave_approval_in_transaction(draft=draft, remark_text=remark)
