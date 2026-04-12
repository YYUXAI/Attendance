from __future__ import annotations

from datetime import date
from typing import List, Sequence, Tuple

from infra.db import get_cursor

_AUDIT_RESULTS_COLUMNS: Tuple[str, ...] = (
    "id",
    "employee_id",
    "shift_id",
    "organization_id",
    "audit_date",
    "audit_stage",
    "checked_at",
    "valid_clock_time",
    "result",
)


def fetch_rows_for_export(
    *,
    shift_id: int,
    start_date: date,
    end_date: date,
) -> Tuple[List[str], List[Tuple]]:
    cols_sql = ", ".join(_AUDIT_RESULTS_COLUMNS)
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT {cols_sql}
            FROM public.audit_results
            WHERE shift_id = %s
              AND audit_date >= %s
              AND audit_date <= %s
            ORDER BY id ASC
            """,
            (int(shift_id), start_date, end_date),
        )
        rows: Sequence[Tuple] = cur.fetchall() or []
    return list(_AUDIT_RESULTS_COLUMNS), [tuple(r) for r in rows]
