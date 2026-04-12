from __future__ import annotations

from infra.db import get_cursor


def is_admin_by_tg_id(*, tg_id: int) -> bool:
    """
    只读：registrations.tg_id -> employee_id，且 admin_list.admin_employee_id 命中则为管理员。
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM public.registrations r
                INNER JOIN public.admin_list a ON a.admin_employee_id = r.employee_id
                WHERE r.tg_id = %s
            )
            """,
            (int(tg_id),),
        )
        row = cur.fetchone()
    return bool(row and row[0])
