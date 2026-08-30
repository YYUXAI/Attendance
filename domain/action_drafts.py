from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from domain.registration.rules import (
    normalize_employee_id_for_template,
    normalize_english_name_for_template,
)


def build_checkin_draft(
    *,
    english_name: str,
    employee_id: str,
    action: str,
) -> str:
    employee = normalize_employee_id_for_template(employee_id)
    name = normalize_english_name_for_template(english_name) or employee
    return f"#打卡\n英文名：{name}\n工号：{employee}\n事项：{action}"


def report_reason(text: str | None) -> str:
    for line in (text or "").splitlines():
        value = line.strip()
        if value.startswith("原因：") or value.startswith("原因:"):
            return value.split("：", 1)[-1].split(":", 1)[-1].strip()[:500]
    return (text or "").strip()[:500]


def build_leave_draft(
    *,
    english_name: str,
    employee_id: str,
    now_local: datetime | None = None,
) -> str:
    del employee_id
    name = normalize_english_name_for_template(english_name) or "未命名"
    return (
        "\n#离岗报备\n"
        f"人员：{name}\n"
        f"时间：{_time_text(now_local)}\n"
        "原因："
    )


def build_back_draft(
    *,
    english_name: str,
    employee_id: str,
    leave_duration: str | None = None,
    leave_overtime: bool = False,
    leave_reason: str | None = None,
    now_local: datetime | None = None,
) -> str:
    del employee_id
    name = normalize_english_name_for_template(english_name) or "未命名"
    text = (
        "\n#返岗报备\n"
        f"人员：{name}\n"
        f"时间：{_time_text(now_local)}\n"
    )
    if leave_duration is not None:
        text += f"离岗时长：{leave_duration}\n"
    if leave_overtime:
        text += "提示：你已超时\n"
    reason = " ".join(str(leave_reason or "").split()).strip()[:500]
    return text + f"原因：{reason}"


def _time_text(value: datetime | None) -> str:
    resolved = value or datetime.now(ZoneInfo("Asia/Shanghai"))
    return resolved.strftime("%H:%M:%S")
