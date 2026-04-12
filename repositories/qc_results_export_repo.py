from __future__ import annotations

from datetime import date
from typing import List, Sequence, Tuple

from infra.db import get_cursor

# 显式列顺序 = CSV 表头顺序；禁止 SELECT *
_QC_RESULTS_COLUMNS: Tuple[str, ...] = (
    "id",
    "employee_id",
    "shift_id",
    "organization_id",
    "qc_date",
    "qc_round",
    "checked_at",
    "completed_at",
    "result",
    "attachment_id",
)


def fetch_rows_for_export(
    *,
    shift_id: int,
    start_date: date,
    end_date: date,
) -> Tuple[List[str], List[Tuple]]:
    cols_sql = ", ".join(_QC_RESULTS_COLUMNS)
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT {cols_sql}
            FROM public.qc_results
            WHERE shift_id = %s
              AND qc_date >= %s
              AND qc_date <= %s
            ORDER BY id ASC
            """,
            (int(shift_id), start_date, end_date),
        )
        rows: Sequence[Tuple] = cur.fetchall() or []
    return list(_QC_RESULTS_COLUMNS), [tuple(r) for r in rows]
