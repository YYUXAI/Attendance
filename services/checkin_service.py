from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from domain.shared.result import ServiceResult
from repositories.clock_records_repo import insert_clock_record
from repositories.organizations_repo import get_department_name_by_id
from repositories.registrations_repo import (
    get_by_tg_id,
    list_by_shift_id,
    update_assignment_by_tg_id,
)
from repositories.shifts_repo import get_by_id as get_shift_by_id
from repositories.shifts_repo import list_by_attendance_group_id


ALLOWED_TIMEZONES = frozenset(
    {
        "Asia/Shanghai",
        "Asia/Kuala_Lumpur",
        "Asia/Bangkok",
        "Asia/Dubai",
    }
)


def _try_auto_assign_from_group(*, tg_id: int, chat_id: int) -> None:
    """
    基于打卡群自动补配置：
    - shift_id：由 shifts.attendance_group_id 唯一匹配时补齐
    - organization_id：在该 shift 下历史注册组织唯一时补齐；否则保持为空
    """
    shifts = list_by_attendance_group_id(attendance_group_id=int(chat_id))
    if len(shifts) != 1:
        return
    shift = shifts[0]

    org_candidates = {
        int(r.organization_id)
        for r in list_by_shift_id(shift_id=int(shift.id))
        if r.organization_id is not None
    }
    org_id = next(iter(org_candidates)) if len(org_candidates) == 1 else None
    update_assignment_by_tg_id(
        tg_id=int(tg_id),
        shift_id=int(shift.id),
        organization_id=org_id,
    )


def switch_attendance_group_to_chat(*, tg_id: int, chat_id: int) -> ServiceResult:
    """将用户班次绑定改为当前群对应的唯一班次（「改用本群打卡」）。"""
    reg = get_by_tg_id(tg_id)
    if not reg:
        return ServiceResult(ok=False, message="您尚未注册。", error_code="NOT_REGISTERED")

    shifts = list_by_attendance_group_id(attendance_group_id=int(chat_id))
    if len(shifts) != 1:
        return ServiceResult(
            ok=False,
            message="本群未绑定唯一班次，无法切换，请联系管理员。",
            error_code="GROUP_NOT_BOUND",
        )
    shift = shifts[0]
    org_candidates = {
        int(r.organization_id)
        for r in list_by_shift_id(shift_id=int(shift.id))
        if r.organization_id is not None
    }
    org_id = next(iter(org_candidates)) if len(org_candidates) == 1 else reg.organization_id
    update_assignment_by_tg_id(
        tg_id=int(tg_id),
        shift_id=int(shift.id),
        organization_id=org_id,
    )
    return ServiceResult(ok=True, message="已切换为本群考勤，请重新发送打卡截图。")


def validate_and_prepare(
    *,
    tg_id: int,
    chat_id: int,
    file_id: str | None,
) -> ServiceResult | tuple[str, int, str, str | None, object, object, str]:
    reg = get_by_tg_id(tg_id)
    if not reg:
        return ServiceResult(ok=False, message="打卡失败，您尚未注册", error_code="NOT_REGISTERED")

    if reg.shift_id is None:
        _try_auto_assign_from_group(tg_id=tg_id, chat_id=chat_id)
        reg = get_by_tg_id(tg_id)
        if not reg:
            return ServiceResult(ok=False, message="打卡失败，您尚未注册", error_code="NOT_REGISTERED")

    if reg.shift_id is None or reg.organization_id is None:
        return ServiceResult(
            ok=False,
            message=(
                "打卡失败，您的账号尚未分配部门/班次（organization_id、shift_id 为空）。\n"
                f"当前工号：{reg.employee_id}，请联系管理员在系统中补全配置。"
            ),
            error_code="NOT_CONFIGURED",
        )

    shift = get_shift_by_id(int(reg.shift_id))
    if not shift or shift.attendance_group_id is None or int(shift.attendance_group_id) != int(chat_id):
        expected = int(shift.attendance_group_id) if shift and shift.attendance_group_id is not None else None
        return ServiceResult(
            ok=False,
            message="打卡失败，请前往您的考勤群打卡。",
            error_code="WRONG_GROUP",
            expected_attendance_group_id=expected,
            current_attendance_group_id=int(chat_id),
        )

    if not file_id:
        return ServiceResult(ok=False, message="打卡失败，请发送打卡截图", error_code="INVALID_INPUT")

    department_name = get_department_name_by_id(int(reg.organization_id))

    return (
        reg.employee_id,
        int(reg.shift_id),
        (reg.english_name or ""),
        department_name,
        shift.checkin_time,
        shift.checkout_time,
        shift.timezone,
    )


def persist_clock_record(
    *,
    tg_id: int,
    chat_id: int,
    file_id: str,
    employee_id: str,
    shift_id: int,
    clock_time_utc: datetime | None = None,
    clock_action: str | None = None,
) -> datetime:
    resolved = clock_time_utc or datetime.now(timezone.utc)
    if resolved.tzinfo is None:
        resolved = resolved.replace(tzinfo=timezone.utc)
    else:
        resolved = resolved.astimezone(timezone.utc)
    insert_clock_record(
        chat_id=chat_id,
        file_id=file_id,
        tg_id=tg_id,
        employee_id=employee_id,
        shift_id=shift_id,
        clock_time_utc=resolved,
        clock_action=clock_action,
    )
    return resolved


def _format_time_hm(t: object) -> str:
    if isinstance(t, time):
        return t.strftime("%H:%M")
    if isinstance(t, datetime):
        return t.strftime("%H:%M")
    return str(t)


def format_success_message(
    *,
    english_name: str,
    employee_id: str,
    department_name: str | None,
    shift_checkin_time: object,
    shift_checkout_time: object,
    timezone_name: str,
    clock_time_utc: datetime,
    file_id: str,
    used_ai_time: bool = False,
    verified_image_user: bool = False,
    image_display_name: str | None = None,
) -> str:
    dept = department_name if department_name else "未配置"
    tz_name = timezone_name
    if tz_name not in ALLOWED_TIMEZONES:
        tz_name = "Asia/Shanghai"
    local_dt = clock_time_utc.astimezone(ZoneInfo(tz_name))
    local_str = local_dt.strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"英文名：{english_name}",
        f"工号：{employee_id}",
        f"部门：{dept}",
        f"班次：{_format_time_hm(shift_checkin_time)} - {_format_time_hm(shift_checkout_time)}",
        f"时区：{timezone_name}",
        f"打卡时间：{local_str}",
    ]
    if used_ai_time:
        lines.append("时间来源：截图 AI 识别")
    elif image_display_name or verified_image_user:
        lines.append("时间来源：服务器时间（AI 未采用截图时间）")
    if verified_image_user and image_display_name:
        lines.append(f"截图用户：{image_display_name}（Slack 浮窗已校验）")
    elif verified_image_user and not image_display_name:
        lines.append("截图用户：已按 Telegram 账号校验（AI 未读出 Slack 姓名）")
    lines.append(f"文件ID：{file_id}")
    return "\n".join(lines)
