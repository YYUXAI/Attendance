from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from domain.shared.result import ServiceResult
from repositories.clock_records_repo import insert_clock_record
from repositories.organizations_repo import get_department_name_by_id
from repositories import employee_shift_config_repo, profile_repo
from repositories.registrations_repo import get_by_tg_id, update_registered_chat_by_tg_id


ALLOWED_TIMEZONES = frozenset(
    {
        "Asia/Shanghai",
        "Asia/Kuala_Lumpur",
        "Asia/Bangkok",
        "Asia/Dubai",
    }
)


def switch_attendance_group_to_chat(*, tg_id: int, chat_id: int) -> ServiceResult:
    """记录常用考勤群（「改用本群打卡」），不写入 registrations.shift_id。"""
    reg = get_by_tg_id(tg_id)
    if not reg:
        return ServiceResult(ok=False, message="您尚未注册。", error_code="NOT_REGISTERED")

    update_registered_chat_by_tg_id(tg_id=int(tg_id), registered_chat_id=int(chat_id))
    return ServiceResult(ok=True, message="已记录本群为考勤群，请重新发送打卡截图。")


def validate_and_prepare(
    *,
    tg_id: int,
    chat_id: int,
    file_id: str | None,
) -> ServiceResult | tuple[str, int | None, str, str | None, object, object, str]:
    reg = get_by_tg_id(tg_id)
    if not reg:
        return ServiceResult(ok=False, message="打卡失败，您尚未注册", error_code="NOT_REGISTERED")

    if not file_id:
        return ServiceResult(ok=False, message="打卡失败，请发送打卡截图", error_code="INVALID_INPUT")

    department_name = (
        get_department_name_by_id(int(reg.organization_id))
        if reg.organization_id is not None
        else None
    )
    tz_name = "Asia/Shanghai"
    cin = None
    cout = None
    ym = datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m")
    employee_shift_config_repo.ensure_table()
    cfg = profile_repo.get_employee_shift_config_for_month(
        employee_id=str(reg.employee_id),
        year_month=ym,
    )
    if cfg:
        cin = cfg.shift_checkin_time
        cout = cfg.shift_checkout_time

    return (
        reg.employee_id,
        None,
        (reg.english_name or ""),
        department_name,
        cin,
        cout,
        tz_name,
    )


def persist_clock_record(
    *,
    tg_id: int,
    chat_id: int,
    file_id: str,
    employee_id: str,
    shift_id: int | None,
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
