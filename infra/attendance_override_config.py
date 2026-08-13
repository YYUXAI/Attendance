from __future__ import annotations

from dataclasses import dataclass

from repositories import attendance_runtime_config_repo


@dataclass(frozen=True)
class AttendanceOverrideConfig:
    export_employee_chat: dict[str, int]
    export_mirror_from: dict[str, str]
    leave_mutual_exclusion_chat_ids: frozenset[int]


def load_attendance_override_config() -> AttendanceOverrideConfig:
    raw_export = attendance_runtime_config_repo.business_fact_map(
        fact_kind="export_employee_chat_override"
    )
    export_map: dict[str, int] = {}
    for employee_id, chat_id in raw_export.items():
        try:
            export_map[employee_id] = int(chat_id)
        except ValueError:
            continue
    mirror_map = attendance_runtime_config_repo.business_fact_map(
        fact_kind="export_mirror_employee"
    )
    return AttendanceOverrideConfig(
        export_employee_chat=export_map,
        export_mirror_from=mirror_map,
        leave_mutual_exclusion_chat_ids=frozenset(),
    )
