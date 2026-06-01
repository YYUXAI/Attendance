from __future__ import annotations

import html
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from zoneinfo import ZoneInfo

from domain.shared.result import ServiceResult
from repositories import profile_repo


def _display_name_or_fallback(english_name: Optional[str]) -> str:
    """
    docs00：对外展示优先 english_name，不得用 employee_id 当人名。
    """
    raw = (english_name or "").strip()
    return raw if raw else "（未填英文名）"


def _leader_name_fallback() -> str:
    return "（未注册）"


def _yyyymmdd(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _month_range_local(*, tz_name: str, now_utc: datetime) -> tuple[date, date, ZoneInfo]:
    tz = ZoneInfo(tz_name)
    local_now = now_utc.astimezone(tz)
    first = date(local_now.year, local_now.month, 1)
    # next month first day
    if local_now.month == 12:
        next_first = date(local_now.year + 1, 1, 1)
    else:
        next_first = date(local_now.year, local_now.month + 1, 1)
    last = next_first - timedelta(days=1)
    return first, last, tz


def _day_bounds_utc(*, d_local: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start_local = datetime.combine(d_local, time(0, 0, 0), tzinfo=tz)
    end_local = datetime.combine(d_local + timedelta(days=1), time(0, 0, 0), tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def get_my_profile_by_tg_id(*, tg_id: int, now_utc: Optional[datetime] = None) -> ServiceResult:
    now = now_utc or datetime.now(timezone.utc)

    prof = profile_repo.get_registration_profile_by_tg_id(tg_id=tg_id)
    if not prof:
        return ServiceResult(ok=False, message="你还未完成注册，请先注册后再查看我的信息。", error_code="NOT_REGISTERED")

    english_name = _display_name_or_fallback(prof.english_name)
    employee_id = str(prof.employee_id)
    department_name = (prof.department_name or "").strip() or "未配置"

    if prof.shift_id is None or prof.timezone is None:
        return ServiceResult(ok=False, message="你的班次信息未配置完整，请联系管理员。", error_code="NO_SHIFT")
    if prof.organization_id is None:
        return ServiceResult(ok=False, message="你的组织信息未配置完整，请联系管理员。", error_code="NO_ORG")

    shift_id = int(prof.shift_id)
    tz_name = str(prof.timezone)
    month_start, month_end, tz = _month_range_local(tz_name=tz_name, now_utc=now)

    # 负责人展示：organizations 字段存的是 employee_id，需要反查 registrations.english_name
    leader_name = _leader_name_fallback()
    if prof.leader_employee_id and str(prof.leader_employee_id).strip():
        leader_en = profile_repo.get_employee_english_name_by_employee_id(employee_id=str(prof.leader_employee_id).strip())
        leader_name = _display_name_or_fallback(leader_en) if leader_en is not None else "（未注册）"

    head_name = _leader_name_fallback()
    if prof.highest_responsible_employee_id and str(prof.highest_responsible_employee_id).strip():
        head_en = profile_repo.get_employee_english_name_by_employee_id(
            employee_id=str(prof.highest_responsible_employee_id).strip()
        )
        head_name = _display_name_or_fallback(head_en) if head_en is not None else "（未注册）"

    # 本月审计结果
    rows = profile_repo.list_month_audit_results(
        employee_id=employee_id,
        shift_id=shift_id,
        month_start_date=month_start,
        month_end_date=month_end,
    )

    missing_clock_count = sum(1 for r in rows if r.result == "ABSENT")
    late_early_count = sum(1 for r in rows if r.result in ("LATE", "EARLY_LEAVE"))

    # 出勤天数（谨慎口径）：同一日只要存在非 ABSENT 的结果（仅 CHECKIN/CHECKOUT），计为出勤日
    present_dates: set[date] = set()
    for r in rows:
        if r.result != "ABSENT":
            present_dates.add(r.audit_date)
    attendance_days = len(present_dates)

    # 本月已审批通过假期（effective_leave_days）
    leave_days = profile_repo.list_month_effective_leave_days(
        employee_id=employee_id,
        shift_id=shift_id,
        month_start_date=month_start,
        month_end_date=month_end,
    )
    leave_day_set = set(leave_days)

    # 本月离岗覆盖（effective_temporary_leaves），用于 DAILY_ABSENT 推导
    month_start_utc, _ = _day_bounds_utc(d_local=month_start, tz=tz)
    _, month_end_next_utc = _day_bounds_utc(d_local=month_end, tz=tz)
    temp_spans = profile_repo.list_effective_temporary_leaves_in_range(
        employee_id=employee_id,
        shift_id=shift_id,
        start_utc=month_start_utc,
        end_utc=month_end_next_utc,
    )

    def _day_has_temp_leave(d0: date) -> bool:
        start_utc, end_utc = _day_bounds_utc(d_local=d0, tz=tz)
        for sp in temp_spans:
            # overlap: [a,b) with [start,end)
            if sp.leave_start_at_utc < end_utc and sp.leave_end_at_utc > start_utc:
                return True
        return False

    # DAILY_ABSENT（按天）：CHECKIN=ABSENT 且 CHECKOUT=ABSENT 且未休假且未离岗覆盖
    by_day: dict[date, dict[str, str]] = {}
    for r in rows:
        by_day.setdefault(r.audit_date, {})[r.audit_stage] = r.result

    daily_absent_count = 0
    for d0, st in by_day.items():
        if st.get("CHECKIN") != "ABSENT" or st.get("CHECKOUT") != "ABSENT":
            continue
        if d0 in leave_day_set:
            continue
        if _day_has_temp_leave(d0):
            continue
        daily_absent_count += 1

    # 文案组装（同步查询展示，不入队、不写 event_logs）
    cin = str(prof.checkin_time)
    cout = str(prof.checkout_time)
    shift_time_display = f"{cin} - {cout}（{tz_name}）"

    # 输出尽量稳定，避免 HTML 依赖；仅做 escape 防止异常字符破坏显示
    msg = (
        f"姓名：{html.escape(english_name)}\n"
        f"工号：{html.escape(employee_id)}\n"
        f"部门：{html.escape(department_name)}\n"
        f"班次时间：{html.escape(shift_time_display)}\n"
        f"上级负责人：{html.escape(leader_name)}\n"
        f"部门负责人：{html.escape(head_name)}\n"
        "-----------------------\n"
        f"本月已出勤天数：{attendance_days}天\n"
        f"本月缺卡次数：{missing_clock_count}次\n"
        f"迟到/早退次数：{late_early_count}次\n"
        f"缺勤次数：{daily_absent_count}次"
    )
    return ServiceResult(ok=True, message=msg)

