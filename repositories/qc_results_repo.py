from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, List, Optional

from psycopg2.extensions import cursor as Cursor

from infra.db import get_cursor


@dataclass(frozen=True)
class QcResultRow:
    id: int
    employee_id: str
    shift_id: int
    organization_id: Optional[int]
    qc_date: Any
    qc_round: int
    checked_at: Any
    completed_at: Any
    result: str
    attachment_id: Optional[str]


def get_by_id_cur(cur: Cursor, *, result_id: int) -> Optional[QcResultRow]:
    """按主键读取终态快照（供后续【查看截图】等链路使用）。"""
    cur.execute(
        """
        SELECT id, employee_id, shift_id, organization_id, qc_date, qc_round,
               checked_at, completed_at, result, attachment_id
        FROM public.qc_results
        WHERE id = %s
        """,
        (int(result_id),),
    )
    row = cur.fetchone()
    if not row:
        return None
    return QcResultRow(*row)


def get_by_id(*, result_id: int) -> Optional[QcResultRow]:
    with get_cursor() as cur:
        return get_by_id_cur(cur, result_id=result_id)


def list_for_shift_and_qc_date(*, shift_id: int, qc_date: date) -> List[QcResultRow]:
    """该班次该 qc_date 下全部结果行（按轮次、员工排序）；不得按 employee 取最新替代多轮。"""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, employee_id, shift_id, organization_id, qc_date, qc_round,
                   checked_at, completed_at, result, attachment_id
            FROM public.qc_results
            WHERE shift_id = %s
              AND qc_date = %s
            ORDER BY qc_round ASC, employee_id ASC
            """,
            (int(shift_id), qc_date),
        )
        rows = cur.fetchall() or []
    return [QcResultRow(*r) for r in rows]


def get_by_unique_key_cur(
    cur: Cursor,
    *,
    employee_id: str,
    shift_id: int,
    qc_date: date,
    qc_round: int,
) -> Optional[QcResultRow]:
    cur.execute(
        """
        SELECT id, employee_id, shift_id, organization_id, qc_date, qc_round,
               checked_at, completed_at, result, attachment_id
        FROM public.qc_results
        WHERE employee_id = %s
          AND shift_id = %s
          AND qc_date = %s
          AND qc_round = %s
        """,
        (str(employee_id), int(shift_id), qc_date, int(qc_round)),
    )
    row = cur.fetchone()
    if not row:
        return None
    return QcResultRow(*row)


def upsert_terminal_result_cur(
    cur: Cursor,
    *,
    employee_id: str,
    shift_id: int,
    organization_id: int,
    qc_date: date,
    qc_round: int,
    result: str,
    attachment_id: Optional[str],
    at_utc: Any,
) -> None:
    cur.execute(
        """
        INSERT INTO public.qc_results (
            employee_id,
            shift_id,
            organization_id,
            qc_date,
            qc_round,
            checked_at,
            completed_at,
            result,
            attachment_id
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (employee_id, qc_date, shift_id, qc_round)
        DO UPDATE SET
            organization_id = EXCLUDED.organization_id,
            checked_at = EXCLUDED.checked_at,
            completed_at = EXCLUDED.completed_at,
            result = EXCLUDED.result,
            attachment_id = EXCLUDED.attachment_id
        """,
        (
            str(employee_id),
            int(shift_id),
            int(organization_id),
            qc_date,
            int(qc_round),
            at_utc,
            at_utc,
            str(result),
            attachment_id,
        ),
    )
