from __future__ import annotations

from typing import Set

from psycopg2.extensions import cursor as Cursor

from infra.db import get_cursor


def list_employee_ids_by_shift_cur(cur: Cursor, *, shift_id: int) -> Set[str]:
    cur.execute(
        """
        SELECT employee_id
        FROM public.qc_exemption_fixed_list
        WHERE shift_id = %s
        """,
        (int(shift_id),),
    )
    rows = cur.fetchall() or []
    out: Set[str] = set()
    for r in rows:
        if r and r[0] is not None:
            out.add(str(r[0]))
    return out


def list_employee_ids_by_shift(*, shift_id: int) -> Set[str]:
    with get_cursor() as cur:
        return list_employee_ids_by_shift_cur(cur, shift_id=shift_id)
