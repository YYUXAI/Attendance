from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from domain.shared.result import ServiceResult
from repositories.clock_records_repo import insert_clock_record
from repositories.organizations_repo import get_department_name_by_id
from repositories.registrations_repo import get_by_tg_id
from repositories.shifts_repo import get_by_id as get_shift_by_id


ALLOWED_TIMEZONES = frozenset(
    {
        "Asia/Shanghai",
        "Asia/Kuala_Lumpur",
        "Asia/Bangkok",
        "Asia/Dubai",
    }
)


def validate_and_prepare(
    *,
    tg_id: int,
    chat_id: int,
    has_hashtag: bool,
    file_id: str | None,
) -> ServiceResult | tuple[str, int, str, str | None, object, object, str]:
    reg = get_by_tg_id(tg_id)
    if not reg:
        return ServiceResult(ok=False, message="打卡失败，您尚未注册", error_code="NOT_REGISTERED")

    if reg.shift_id is None or reg.organization_id is None:
        return ServiceResult(
            ok=False,
            message="打卡失败，您的配置信息尚未完善，请尽快联系管理员",
            error_code="NOT_CONFIGURED",
        )

    shift = get_shift_by_id(int(reg.shift_id))
    if not shift or shift.attendance_group_id is None or int(shift.attendance_group_id) != int(chat_id):
        return ServiceResult(ok=False, message="打卡失败，这不是您的考勤群", error_code="WRONG_GROUP")

    if (not has_hashtag) or (not file_id):
        return ServiceResult(ok=False, message="打卡失败，请按 #打卡 并附带附件", error_code="INVALID_INPUT")

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
) -> datetime:
    now_utc = datetime.now(timezone.utc)
    insert_clock_record(
        chat_id=chat_id,
        file_id=file_id,
        tg_id=tg_id,
        employee_id=employee_id,
        shift_id=shift_id,
        clock_time_utc=now_utc,
    )
    return now_utc


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
) -> str:
    dept = department_name if department_name else "未配置"
    tz_name = timezone_name
    if tz_name not in ALLOWED_TIMEZONES:
        tz_name = "Asia/Shanghai"
    local_dt = clock_time_utc.astimezone(ZoneInfo(tz_name))
    local_str = local_dt.strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"英文名：{english_name}\n"
        f"工号：{employee_id}\n"
        f"部门：{dept}\n"
        f"班次：{_format_time_hm(shift_checkin_time)} - {_format_time_hm(shift_checkout_time)}\n"
        f"时区：{timezone_name}\n"
        f"打卡时间：{local_str}\n"
        f"文件ID：{file_id}"
    )
