from __future__ import annotations

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
