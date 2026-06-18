from __future__ import annotations

from datetime import date
from typing import List, Sequence, Tuple

from infra.db import get_cursor

_EFFECTIVE_LEAVE_DAYS_COLUMNS: Tuple[str, ...] = (
    "id",
    "employee_id",
    "leave_date",
    "shift_id",
    "leave_reason",
    "application_remark",
    "application_id",
)


def fetch_rows_for_export(
    *,
    shift_id: int,
    start_date: date,
    end_date: date,
) -> Tuple[List[str], List[Tuple]]:
    cols_sql = ", ".join(_EFFECTIVE_LEAVE_DAYS_COLUMNS)
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT {cols_sql}
            FROM public.effective_leave_days
            WHERE shift_id = %s
              AND leave_date >= %s
              AND leave_date <= %s
            ORDER BY id ASC
            """,
            (int(shift_id), start_date, end_date),
        )
        rows: Sequence[Tuple] = cur.fetchall() or []
    return list(_EFFECTIVE_LEAVE_DAYS_COLUMNS), [tuple(r) for r in rows]
