from __future__ import annotations

import os
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

from domain.shared.result import ServiceResult
from repositories.clock_records_repo import (
    insert_clock_record,
)
from repositories.organizations_repo import get_department_name_by_id
from repositories import employee_shift_config_repo, employee_shift_roster_repo, profile_repo
from services.employee_shift_day_service import get_daily_shift
from repositories.registrations_repo import get_by_tg_id, update_registered_chat_by_tg_id


ALLOWED_TIMEZONES = frozenset(
    {
        "Asia/Shanghai",
        "Asia/Kuala_Lumpur",
        "Asia/Bangkok",
        "Asia/Dubai",
    }
)

_AI_DRY_RUN_EMPLOYEE_IDS_IN_YYMG = frozenset({"99999"})
# 非正式群但全员跑 AI、不入库（勿并入「测试群」Google 回写名单）
_DEFAULT_AI_DRY_RUN_CHAT_IDS: frozenset[int] = frozenset()
_DEFAULT_AI_DRY_RUN_GROUP_TITLES: frozenset[str] = frozenset({"New-考勤测试群"})


def formal_group_roster_source_for_chat(*, chat_id: int) -> str | None:
    """Gateway classification already proves this is an Attendance group."""
    del chat_id
    return "main"


def should_accept_checkin_for_chat_roster(
    *, chat_id: int, employee_id: str, tz_name: str
) -> tuple[bool, str]:
    """
    Dynamic Attendance groups share the canonical main roster source.
    """
    del chat_id
    roster_source = "main"
    ym = datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m")
    allowed = employee_shift_roster_repo.roster_set(year_month=ym, source=roster_source)
    if str(employee_id).strip() in allowed:
        return True, ""
    return False, "不在本群对应班表"


def _ai_dry_run_chat_ids() -> frozenset[int]:
    raw = (os.getenv("AI_DRY_RUN_CHAT_IDS") or "").strip()
    if not raw:
        return _DEFAULT_AI_DRY_RUN_CHAT_IDS
    out: set[int] = set()
    for part in raw.replace("，", ",").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.add(int(p))
        except ValueError:
            continue
    return frozenset(out) if out else _DEFAULT_AI_DRY_RUN_CHAT_IDS


def _ai_dry_run_group_titles() -> frozenset[str]:
    raw = (os.getenv("AI_DRY_RUN_GROUP_TITLES") or "").strip()
    if not raw:
        return _DEFAULT_AI_DRY_RUN_GROUP_TITLES
    out = {p.strip() for p in raw.replace("，", ",").split(",") if p.strip()}
    return frozenset(out) if out else _DEFAULT_AI_DRY_RUN_GROUP_TITLES


def _yymg_chat_id() -> int | None:
    raw = (os.getenv("YYMG_CHAT_ID") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def should_run_ai_without_persist(
    *,
    chat_id: int,
    employee_id: str,
    roster_allowed: bool,
    chat_title: str | None = None,
) -> bool:
    """指定场景：走完整 AI 校验，但不写入打卡记录。"""
    if roster_allowed:
        return False
    # 「测试群」：全员跑 AI，前台按结果回复，不入库（含 Google 回写配置，勿混用）
    from infra.test_group_google_config import is_test_group_chat

    if is_test_group_chat(chat_id=int(chat_id), chat_title=chat_title):
        return True
    # New-考勤测试群等：过 AI、不入库（不触发测试群 Google 回写）
    if int(chat_id) in _ai_dry_run_chat_ids():
        return True
    title = (chat_title or "").strip()
    if title and title in _ai_dry_run_group_titles():
        return True
    # YYMG 内指定测试工号
    yymg_chat_id = _yymg_chat_id()
    if yymg_chat_id is None or int(chat_id) != yymg_chat_id:
        return False
    return str(employee_id).strip() in _AI_DRY_RUN_EMPLOYEE_IDS_IN_YYMG


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
    today = datetime.now(ZoneInfo(tz_name)).date()
    employee_shift_config_repo.ensure_table()
    daily = get_daily_shift(
        employee_id=str(reg.employee_id),
        work_date=today,
        year_month=ym,
    )
    if daily is not None and not daily.is_rest:
        cin = daily.checkin
        cout = daily.checkout
    else:
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


def format_test_group_success_message(
    *,
    english_name: str,
    clock_time_utc: datetime,
    matter: str,
    timezone_name: str = "Asia/Shanghai",
) -> str:
    tz_name = timezone_name if timezone_name in ALLOWED_TIMEZONES else "Asia/Shanghai"
    local_dt = clock_time_utc.astimezone(ZoneInfo(tz_name))
    return (
        f"{matter}成功\n"
        f"姓名：{english_name}\n"
        f"时间：{local_dt.strftime('%H:%M:%S')}\n"
        f"日期：{local_dt.strftime('%m-%d')}"
    )


def format_ai_dry_run_success_message(
    *,
    english_name: str,
    employee_id: str,
    clock_time_utc: datetime,
    matter: str,
    used_ai_time: bool,
    verified_image_user: bool,
    image_display_name: str | None = None,
    timezone_name: str = "Asia/Shanghai",
) -> str:
    """非正式群 AI 试跑：完整校验后给用户可读结果，不入库。"""
    body = format_test_group_success_message(
        english_name=english_name,
        clock_time_utc=clock_time_utc,
        matter=matter,
        timezone_name=timezone_name,
    )
    lines = [body, f"工号：{employee_id}"]
    if used_ai_time:
        lines.append("时间来源：截图 AI 识别")
    else:
        lines.append("时间来源：服务器时间（AI 未采用截图时间）")
    if verified_image_user and image_display_name:
        lines.append(f"截图用户：{image_display_name}（已校验）")
    elif verified_image_user:
        lines.append("截图用户：已与账号校验")
    lines.append("说明：本地试跑，未写入打卡数据库")
    return "\n".join(lines)


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
