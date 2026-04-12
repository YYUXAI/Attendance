from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from psycopg2.extensions import cursor as Cursor

from infra.db import get_cursor


@dataclass(frozen=True)
class EffectiveTemporaryLeaveRow:
    id: int
    employee_id: str
    effective_date: Any
    shift_id: int
    reason_remark: Optional[str]
    leave_start_at: Any
    leave_end_at: Any
    application_id: int


def exists_covering_instant_cur(
    cur: Cursor,
    *,
    employee_id: str,
    shift_id: int,
    instant_utc: Any,
) -> bool:
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM public.effective_temporary_leaves
            WHERE employee_id = %s
              AND shift_id = %s
              AND leave_start_at <= %s
              AND %s < leave_end_at
        )
        """,
        (employee_id, shift_id, instant_utc, instant_utc),
    )
    row = cur.fetchone()
    return bool(row and row[0])


def exists_covering_instant(
    *,
    employee_id: str,
    shift_id: int,
    instant_utc: Any,
) -> bool:
    """
    一期口径：判定时点 instant_utc 是否被已生效离岗时段覆盖（[leave_start_at, leave_end_at)）。
    """
    with get_cursor() as cur:
        return exists_covering_instant_cur(
            cur,
            employee_id=employee_id,
            shift_id=shift_id,
            instant_utc=instant_utc,
        )


def get_by_application_id_cur(cur: Cursor, *, application_id: int) -> Optional[EffectiveTemporaryLeaveRow]:
    cur.execute(
        """
        SELECT id, employee_id, effective_date, shift_id, reason_remark,
               leave_start_at, leave_end_at, application_id
        FROM public.effective_temporary_leaves
        WHERE application_id = %s
        ORDER BY id DESC
        LIMIT 1
        """,
        (application_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return EffectiveTemporaryLeaveRow(*row)


def insert_effective_row(
    cur: Cursor,
    *,
    employee_id: str,
    effective_date: date,
    shift_id: int,
    reason_remark: Optional[str],
    leave_start_at: Any,
    leave_end_at: Any,
    application_id: int,
) -> int:
    cur.execute(
        """
        INSERT INTO public.effective_temporary_leaves (
            employee_id,
            effective_date,
            shift_id,
            reason_remark,
            leave_start_at,
            leave_end_at,
            application_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            employee_id,
            effective_date,
            shift_id,
            reason_remark,
            leave_start_at,
            leave_end_at,
            application_id,
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])
