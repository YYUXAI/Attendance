from __future__ import annotations

from datetime import date
from typing import Optional, Sequence

from psycopg2.extensions import cursor as Cursor

from infra.db import get_cursor


def list_on_leave_employee_ids_cur(
    cur: Cursor,
    *,
    shift_id: int,
    leave_date: date,
    employee_ids: Sequence[str],
) -> set[str]:
    """给定候选 employee_id，返回在 effective_leave_days 命中当日休假的子集。"""
    if not employee_ids:
        return set()
    cur.execute(
        """
        SELECT employee_id
        FROM public.effective_leave_days
        WHERE shift_id = %s
          AND leave_date = %s
          AND employee_id IN %s
        """,
        (shift_id, leave_date, tuple(employee_ids)),
    )
    rows = cur.fetchall() or []
    return {str(r[0]) for r in rows if r and r[0] is not None}


def list_leave_days_for_shift_date(
    *,
    shift_id: int,
    leave_date: date,
    employee_ids: Sequence[str],
) -> list[tuple[str, int]]:
    """
    用于“对外通知”展示：批量获取请假员工对应的 application_id。
    返回 (employee_id, application_id) 列表。

    注意：effective_leave_days 是按日生效表；同一员工在同一日只会有一条记录。
    """
    if not employee_ids:
        return []
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT employee_id, application_id
            FROM public.effective_leave_days
            WHERE shift_id = %s
              AND leave_date = %s
              AND employee_id IN %s
            """,
            (shift_id, leave_date, tuple(employee_ids)),
        )
        rows = cur.fetchall() or []
    out: list[tuple[str, int]] = []
    for r in rows:
        try:
            out.append((str(r[0]), int(r[1])))
        except Exception:
            continue
    return out

def insert_day(
    cur: Cursor,
    *,
    employee_id: str,
    leave_date: date,
    shift_id: int,
    leave_reason: Optional[str],
    application_remark: Optional[str],
    application_id: int,
) -> None:
    """
    按 (employee_id, leave_date, shift_id) 幂等插入。
    leave_reason / application_remark 无内容时传 None 写 NULL。
    """
    cur.execute(
        """
        INSERT INTO public.effective_leave_days (
            employee_id,
            leave_date,
            shift_id,
            leave_reason,
            application_remark,
            application_id
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (employee_id, leave_date, shift_id) DO NOTHING
        """,
        (employee_id, leave_date, shift_id, leave_reason, application_remark, application_id),
    )


def exists_any_conflicting_day(
    cur: Cursor,
    *,
    employee_id: str,
    shift_id: int,
    leave_dates: Sequence[date],
) -> bool:
    """
    判断给定日历日是否在 effective_leave_days 中已有记录。
    leave_dates 应由 service 层用与写入相同的日历展开逻辑生成；本函数不做 UTC/时区换算。
    """
    if not leave_dates:
        return False
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM public.effective_leave_days
            WHERE employee_id = %s
              AND shift_id = %s
              AND leave_date IN %s
        )
        """,
        (employee_id, shift_id, tuple(leave_dates)),
    )
    row = cur.fetchone()
    return bool(row and row[0])


def exists_leave_day(*, employee_id: str, shift_id: int, leave_date: date) -> bool:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM public.effective_leave_days
                WHERE employee_id = %s
                  AND shift_id = %s
                  AND leave_date = %s
            )
            """,
            (employee_id, shift_id, leave_date),
        )
        row = cur.fetchone()
    return bool(row and row[0])
