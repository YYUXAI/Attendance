from __future__ import annotations

from repositories import attendance_runtime_config_repo

ADMIN_EXPORT_CHAT_SCOPE_FACT = "admin_export_chat_scope"


def load_admin_export_chat_scope() -> dict[str, int]:
    raw = attendance_runtime_config_repo.business_fact_map(
        fact_kind=ADMIN_EXPORT_CHAT_SCOPE_FACT
    )
    scope: dict[str, int] = {}
    for employee_id, chat_id_text in raw.items():
        eid = str(employee_id).strip()
        if not eid:
            continue
        try:
            scope[eid] = int(str(chat_id_text).strip())
        except ValueError:
            continue
    return scope


def admin_export_chat_id_for_employee(*, employee_id: str) -> int | None:
    eid = str(employee_id).strip()
    if not eid:
        return None
    return load_admin_export_chat_scope().get(eid)
