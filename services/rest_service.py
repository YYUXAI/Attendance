from __future__ import annotations

import html
import logging
import secrets
from urllib.parse import quote
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from typing import Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from domain.shared.result import ServiceResult
from domain.shared.person_html import person_display_html
from infra.db import transaction
from repositories import approval_task_queue_repo, effective_leave_days_repo, leave_applications_repo, organizations_repo
from repositories.registrations_repo import get_by_employee_id, get_by_tg_id
from repositories.shifts_repo import get_by_id as get_shift_by_id
from services.leave_calendar_utils import iter_leave_dates_in_shift_timezone

log = logging.getLogger(__name__)


class _SubmitLeaveInvalidPastDateError(Exception):
    """提交期：休假区间在班次时区下已完全早于今天。"""


class _SubmitLeaveApplicationOverlapError(Exception):
    """与 leave_applications 中审批中/已通过/已生效申请区间重叠。"""


class _SubmitLeaveEffectiveDaysConflictError(Exception):
    """与 effective_leave_days 已生效按日记录冲突。"""

# 可调：环境与业务确认默认 31 天
MAX_LEAVE_SPAN_DAYS = 31

# 与数据库 CHECK 一致：若库中 application_type 枚举不同，请改此常量并说明原因
APPLICATION_TYPE_LEAVE = "LEAVE"

LEAVE_TYPE_LABELS: Dict[str, str] = {
    "weekly": "周休",
    "visa": "签证假",
    "annual": "年假",
    "personal": "事假",
    "sick": "病假",
}

STATE_CHOOSE_TYPE = "choose_type"
STATE_WAIT_CUSTOM = "wait_custom"
STATE_WAIT_START = "wait_start"
STATE_WAIT_END = "wait_end"
STATE_WAIT_REMARK = "wait_remark"
STATE_WAIT_CONFIRM = "wait_confirm"


@dataclass
class LeaveDraft:
    leave_type_label: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    remark: Optional[str] = None


@dataclass
class LeaveSubmitPayload:
    token: str
    tg_id: int
    employee_id: str
    organization_id: int
    shift_id: int
    shift_timezone: str
    english_name: str
    department_name: Optional[str]
    leave_type_label: str
    start_date: date
    end_date: date
    remark: str
    start_at_utc: datetime
    end_at_utc: datetime


_leave_phase: Dict[int, str] = {}
_leave_draft: Dict[int, LeaveDraft] = {}
_pending_submit: Dict[str, LeaveSubmitPayload] = {}


def clear_leave_session(*, tg_id: int) -> None:
    """进入注册等其他流程时清空休假会话（避免双状态）。"""
    _leave_phase.pop(tg_id, None)
    _leave_draft.pop(tg_id, None)
    dead: list[str] = []
    for tok, p in _pending_submit.items():
        if p.tg_id == tg_id:
            dead.append(tok)
    for t in dead:
        _pending_submit.pop(t, None)


def is_leave_flow_expecting_text(*, tg_id: int) -> bool:
    st = _leave_phase.get(tg_id)
    return st in {
        STATE_WAIT_CUSTOM,
        STATE_WAIT_START,
        STATE_WAIT_END,
        STATE_WAIT_REMARK,
    }


def _ensure_registered_with_org_shift(*, tg_id: int) -> ServiceResult | Tuple[object, object, object]:
    reg = get_by_tg_id(tg_id)
    if not reg:
        return ServiceResult(ok=False, message="您尚未注册，无法提交休假申请。", error_code="NOT_REGISTERED")
    if reg.organization_id is None or reg.shift_id is None:
        return ServiceResult(
            ok=False,
            message="您的组织或班次尚未配置完整，请联系管理员后再申请休假。",
            error_code="NOT_CONFIGURED",
        )
    shift = get_shift_by_id(int(reg.shift_id))
    if not shift or not shift.timezone:
        return ServiceResult(ok=False, message="未找到班次时区配置，请联系管理员。", error_code="NO_TIMEZONE")
    return reg, shift, shift.timezone


def begin_leave_application(*, tg_id: int) -> ServiceResult:
    got = _ensure_registered_with_org_shift(tg_id=tg_id)
    if isinstance(got, ServiceResult):
        return got
    from services import temporary_leave_service

    temporary_leave_service.clear_temporary_leave_session(tg_id=tg_id)
    clear_leave_session(tg_id=tg_id)
    _leave_phase[tg_id] = STATE_CHOOSE_TYPE
    _leave_draft[tg_id] = LeaveDraft()
    return ServiceResult(ok=True, message="")


def on_leave_type_chosen(*, tg_id: int, type_key: str) -> ServiceResult:
    if _leave_phase.get(tg_id) != STATE_CHOOSE_TYPE:
        return ServiceResult(ok=False, message="流程已失效，请重新点击【报备休息】。", error_code="STALE")

    draft = _leave_draft.get(tg_id)
    if not draft:
        return ServiceResult(ok=False, message="流程已失效，请重新点击【报备休息】。", error_code="STALE")

    if type_key == "other":
        _leave_phase[tg_id] = STATE_WAIT_CUSTOM
        return ServiceResult(ok=True, message="")

    label = LEAVE_TYPE_LABELS.get(type_key)
    if not label:
        return ServiceResult(ok=False, message="无效的休假类型。", error_code="BAD_TYPE")

    draft.leave_type_label = label
    _leave_phase[tg_id] = STATE_WAIT_START
    return ServiceResult(ok=True, message="")


def consume_custom_leave_type(*, tg_id: int, text: str) -> ServiceResult:
    if _leave_phase.get(tg_id) != STATE_WAIT_CUSTOM:
        return ServiceResult(ok=False, message="", error_code="SKIP")

    raw = (text or "").strip()
    if not raw:
        return ServiceResult(ok=False, message="休假类型不能为空，请重新输入。", error_code="EMPTY")
    if len(raw) > 50:
        return ServiceResult(ok=False, message="休假类型长度不能超过 50 个字符。", error_code="TOO_LONG")

    draft = _leave_draft.get(tg_id)
    if not draft:
        return ServiceResult(ok=False, message="流程已失效，请重新点击【报备休息】。", error_code="STALE")

    draft.leave_type_label = raw
    _leave_phase[tg_id] = STATE_WAIT_START
    return ServiceResult(ok=True, message="")


def _parse_y_m_d(text: str) -> date | None:
    raw = (text or "").strip()
    parts = raw.split("$", 2)
    if len(parts) != 3:
        return None
    try:
        y, m, d = int(parts[0].strip()), int(parts[1].strip()), int(parts[2].strip())
        return date(y, m, d)
    except Exception:
        return None


def consume_start_date(*, tg_id: int, text: str) -> ServiceResult:
    log.info("[CONSUME_START_DATE_ENTER] tg_id=%s phase=%s", tg_id, _leave_phase.get(tg_id))
    if _leave_phase.get(tg_id) != STATE_WAIT_START:
        log.info("[CONSUME_START_DATE_RESULT] tg_id=%s outcome=SKIP", tg_id)
        return ServiceResult(ok=False, message="", error_code="SKIP")

    d = _parse_y_m_d(text)
    if not d:
        log.info("[CONSUME_START_DATE_RESULT] tg_id=%s outcome=BAD_DATE", tg_id)
        return ServiceResult(
            ok=False,
            message="日期格式不正确，请按 年$月$日 输入，例如：\n2026$4$3",
            error_code="BAD_DATE",
        )
    draft = _leave_draft.get(tg_id)
    if not draft:
        log.info("[CONSUME_START_DATE_RESULT] tg_id=%s outcome=STALE", tg_id)
        return ServiceResult(ok=False, message="流程已失效，请重新点击【报备休息】。", error_code="STALE")

    draft.start_date = d
    _leave_phase[tg_id] = STATE_WAIT_END
    log.info("[CONSUME_START_DATE_RESULT] tg_id=%s outcome=OK", tg_id)
    return ServiceResult(ok=True, message="")


def consume_end_date(*, tg_id: int, text: str) -> ServiceResult:
    if _leave_phase.get(tg_id) != STATE_WAIT_END:
        return ServiceResult(ok=False, message="", error_code="SKIP")

    d = _parse_y_m_d(text)
    if not d:
        return ServiceResult(
            ok=False,
            message="日期格式不正确，请按 年$月$日 输入，例如：\n2026$4$3",
            error_code="BAD_DATE",
        )
    draft = _leave_draft.get(tg_id)
    if not draft or draft.start_date is None:
        return ServiceResult(ok=False, message="流程已失效，请重新点击【报备休息】。", error_code="STALE")

    if d < draft.start_date:
        return ServiceResult(ok=False, message="结束日期不能早于开始日期。", error_code="ORDER")

    span = (d - draft.start_date).days + 1
    if span > MAX_LEAVE_SPAN_DAYS:
        return ServiceResult(
            ok=False,
            message=f"单次休假最长 {MAX_LEAVE_SPAN_DAYS} 天，请缩短区间后重试。",
            error_code="SPAN",
        )

    draft.end_date = d
    _leave_phase[tg_id] = STATE_WAIT_REMARK
    return ServiceResult(ok=True, message="")


def get_leave_phase(*, tg_id: int) -> Optional[str]:
    return _leave_phase.get(tg_id)


def consume_remark(*, tg_id: int, text: str) -> Tuple[ServiceResult, Optional[str]]:
    if _leave_phase.get(tg_id) != STATE_WAIT_REMARK:
        return ServiceResult(ok=False, message="", error_code="SKIP"), None

    draft = _leave_draft.get(tg_id)
    if not draft or draft.start_date is None or draft.end_date is None or not draft.leave_type_label:
        return ServiceResult(ok=False, message="流程已失效，请重新点击【报备休息】。", error_code="STALE"), None

    t = (text or "").strip()
    tl = t.casefold()
    if tl == "null" or tl == "/null":
        remark = ""
    else:
        remark = t

    draft.remark = remark

    got = _ensure_registered_with_org_shift(tg_id=tg_id)
    if isinstance(got, ServiceResult):
        return got, None
    reg, shift, tz_name = got

    dept = organizations_repo.get_department_name_by_id(int(reg.organization_id))

    start_utc, end_utc = build_leave_window_utc(
        start_date=draft.start_date,
        end_date=draft.end_date,
        timezone_name=tz_name,
    )

    token = secrets.token_urlsafe(16)
    duration_days = (draft.end_date - draft.start_date).days + 1

    payload = LeaveSubmitPayload(
        token=token,
        tg_id=tg_id,
        employee_id=reg.employee_id,
        organization_id=int(reg.organization_id),
        shift_id=int(reg.shift_id),
        shift_timezone=tz_name,
        english_name=reg.english_name or "",
        department_name=dept,
        leave_type_label=draft.leave_type_label,
        start_date=draft.start_date,
        end_date=draft.end_date,
        remark=draft.remark or "",
        start_at_utc=start_utc,
        end_at_utc=end_utc,
    )
    _pending_submit[token] = payload
    _leave_phase[tg_id] = STATE_WAIT_CONFIRM

    summary = format_confirm_summary(payload=payload, duration_days=duration_days)
    return ServiceResult(ok=True, message=summary), token


def format_confirm_summary(*, payload: LeaveSubmitPayload, duration_days: int) -> str:
    dept_raw = payload.department_name if payload.department_name else "未配置"
    remark_show_raw = payload.remark if payload.remark else "（无）"

    en = html.escape(payload.english_name or "")
    eid = html.escape(str(payload.employee_id))
    dept = html.escape(dept_raw)
    ltype = html.escape(payload.leave_type_label)
    sd = html.escape(str(payload.start_date))
    ed = html.escape(str(payload.end_date))
    dur = html.escape(str(duration_days))
    remark_show = html.escape(remark_show_raw)

    approver_id = resolve_approver_employee_id(
        applicant_employee_id=payload.employee_id,
        organization_id=payload.organization_id,
    )
    approver_reg = get_by_employee_id(approver_id)
    # 对外展示不回退为 employee_id 当人名（明确位置：休假确认摘要）
    if not approver_reg:
        approver_display = "（审批人未注册）"
    else:
        approver_display = person_display_html(
            english_name=approver_reg.english_name,
            tg_username=approver_reg.tg_username,
            missing_name_fallback="（审批人未填英文名）",
        )

    return (
        "请确认您的休假申请：\n\n"
        f"英文名：{en}\n"
        f"工号：{eid}\n"
        f"部门：{dept}\n"
        f"休假类型：{ltype}\n"
        f"休假日期：{sd} 至 {ed}\n"
        f"休假时长：{dur}天\n"
        f"申请备注：{remark_show}\n\n"
        f"如您确认无误，请点击下方确认按钮。您的休假申请将会递交您的上级管理 {approver_display} 处。"
    )


def build_leave_window_utc(*, start_date: date, end_date: date, timezone_name: str) -> Tuple[datetime, datetime]:
    tz = ZoneInfo(timezone_name)
    start_local = datetime.combine(start_date, time(0, 0, 0), tzinfo=tz)
    end_local = datetime.combine(end_date, time(23, 59, 59), tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def resolve_approver_employee_id(*, applicant_employee_id: str, organization_id: int) -> str:
    """
    审批人解析（业务口径）：
    - L=leader、highest、applicant 均先 strip，纯空白视为无值；比较大小写敏感。
    - L 有值且 L != A → 审批人为 L。
    - 否则若 H 有值 → 审批人为 H（允许 H == A）。
    - 否则 → 审批人为 A。
    只要最终审批人 == A，记录 warning（含 strip 后各字段）。
    """
    leader, highest = organizations_repo.get_leader_fields(organization_id)

    def _norm(s: Optional[str]) -> str:
        if s is None:
            return ""
        return str(s).strip()

    a = _norm(applicant_employee_id)
    l_val = _norm(leader)
    h_val = _norm(highest)

    if l_val and l_val != a:
        final = l_val
    elif h_val:
        final = h_val
    else:
        final = a

    if final == a:
        log.warning(
            "leave_approver_equals_applicant applicant_employee_id=%s organization_id=%s "
            "leader_employee_id=%s highest_responsible_employee_id=%s approver_employee_id=%s",
            a,
            organization_id,
            l_val,
            h_val,
            final,
        )
    return final


def cancel_leave_confirm(*, token: str, tg_id: int) -> None:
    _pending_submit.pop(token, None)
    clear_leave_session(tg_id=tg_id)


def submit_leave_application(*, token: str, tg_id: int) -> ServiceResult:
    payload = _pending_submit.get(token)
    if not payload or payload.tg_id != tg_id:
        return ServiceResult(ok=False, message="确认已失效，请重新发起休假申请。", error_code="EXPIRED")

    reg = get_by_tg_id(tg_id)
    if not reg or reg.organization_id is None or reg.shift_id is None:
        return ServiceResult(ok=False, message="您的注册信息已变更，请重新发起申请。", error_code="STALE_REG")

    approver_id = resolve_approver_employee_id(
        applicant_employee_id=payload.employee_id,
        organization_id=payload.organization_id,
    )

    created_at = datetime.now(timezone.utc)
    task_created_at = datetime.now(timezone.utc)

    try:
        with transaction() as cur:
            tz = ZoneInfo(payload.shift_timezone)
            today_shift = datetime.now(timezone.utc).astimezone(tz).date()
            end_shift = payload.end_at_utc.astimezone(tz).date()
            if end_shift < today_shift:
                log.info(
                    "submit_leave_application blocked employee_id=%s shift_id=%s "
                    "start_at_utc=%s end_at_utc=%s reason_type=invalid_past_date",
                    payload.employee_id,
                    payload.shift_id,
                    payload.start_at_utc,
                    payload.end_at_utc,
                )
                raise _SubmitLeaveInvalidPastDateError()

            if leave_applications_repo.exists_overlapping_leave(
                cur,
                employee_id=payload.employee_id,
                shift_id=payload.shift_id,
                new_start_at_utc=payload.start_at_utc,
                new_end_at_utc=payload.end_at_utc,
            ):
                log.info(
                    "submit_leave_application blocked employee_id=%s shift_id=%s "
                    "start_at_utc=%s end_at_utc=%s reason_type=application_overlap",
                    payload.employee_id,
                    payload.shift_id,
                    payload.start_at_utc,
                    payload.end_at_utc,
                )
                raise _SubmitLeaveApplicationOverlapError()

            proposed_leave_dates = iter_leave_dates_in_shift_timezone(
                payload.start_at_utc,
                payload.end_at_utc,
                timezone_name=payload.shift_timezone,
            )
            if effective_leave_days_repo.exists_any_conflicting_day(
                cur,
                employee_id=payload.employee_id,
                shift_id=payload.shift_id,
                leave_dates=proposed_leave_dates,
            ):
                log.info(
                    "submit_leave_application blocked employee_id=%s shift_id=%s "
                    "start_at_utc=%s end_at_utc=%s reason_type=effective_leave_conflict",
                    payload.employee_id,
                    payload.shift_id,
                    payload.start_at_utc,
                    payload.end_at_utc,
                )
                raise _SubmitLeaveEffectiveDaysConflictError()

            leave_id, leave_created_at = leave_applications_repo.insert_leave_application(
                cur,
                employee_id=payload.employee_id,
                organization_id=payload.organization_id,
                shift_id=payload.shift_id,
                start_at_utc=payload.start_at_utc,
                end_at_utc=payload.end_at_utc,
                leave_reason=payload.leave_type_label,
                remark=payload.remark,
                status="APPROVING",
                created_at_utc=created_at,
            )

            approval_task_queue_repo.insert_leave_approval_task(
                cur,
                application_type=APPLICATION_TYPE_LEAVE,
                application_id=leave_id,
                application_submitted_at=leave_created_at,
                approval_level=1,
                applicant_employee_id=payload.employee_id,
                approver_employee_id=approver_id,
                task_status="PENDING",
                approval_result="NONE",
                task_created_at_utc=task_created_at,
            )
    except _SubmitLeaveInvalidPastDateError:
        return ServiceResult(
            ok=False,
            message="该休假申请日期已全部早于当前班次日期，无法提交，请重新选择日期。",
            error_code="INVALID_PAST_DATE",
        )
    except _SubmitLeaveApplicationOverlapError:
        return ServiceResult(
            ok=False,
            message="该时段与您仍在审批中、已批准或已生效的休假申请重叠，请调整日期后重新提交。",
            error_code="APPLICATION_OVERLAP",
        )
    except _SubmitLeaveEffectiveDaysConflictError:
        return ServiceResult(
            ok=False,
            message="该时段与已生效的休假记录冲突，请调整日期后重新提交，或联系管理员核对历史记录。",
            error_code="EFFECTIVE_LEAVE_CONFLICT",
        )
    except Exception:
        log.exception("submit_leave_application failed")
        return ServiceResult(ok=False, message="提交失败，请稍后重试或联系管理员。", error_code="DB_ERROR")

    _pending_submit.pop(token, None)
    clear_leave_session(tg_id=tg_id)
    return ServiceResult(
        ok=True,
        message="您的休假申请已提交，请等待审批。",
        leave_application_id=leave_id,
    )

