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


def grant_admin_all_registered() -> tuple[int, int]:
    """将全部已注册工号写入 admin_list；不改运行时判定逻辑。"""
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.admin_list (admin_employee_id)
            SELECT r.employee_id
            FROM public.registrations r
            ON CONFLICT (admin_employee_id) DO NOTHING
            RETURNING id
            """
        )
        inserted = len(cur.fetchall() or [])
        cur.execute("SELECT COUNT(*) FROM public.admin_list")
        total = int((cur.fetchone() or (0,))[0])
    return inserted, total


def grant_admin_by_employee_id(*, employee_id: str) -> bool:
    """将工号加入 admin_list；已存在则跳过。返回是否新插入。"""
    eid = str(employee_id).strip()
    if not eid:
        return False
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.admin_list (admin_employee_id)
            VALUES (%s)
            ON CONFLICT (admin_employee_id) DO NOTHING
            RETURNING id
            """,
            (eid,),
        )
        row = cur.fetchone()
    return bool(row and row[0] is not None)


def grant_admin_by_tg_username(*, tg_username: str) -> tuple[bool, str | None]:
    """按 Telegram 用户名授权管理员。返回 (成功与否, employee_id)。"""
    from repositories.registrations_repo import get_by_tg_username

    reg = get_by_tg_username(tg_username)
    if reg is None:
        return False, None
    grant_admin_by_employee_id(employee_id=str(reg.employee_id))
    return True, str(reg.employee_id)
