from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple

from psycopg2.extensions import cursor as Cursor

from infra.db import get_cursor


@dataclass(frozen=True)
class LeaveApplicationRow:
    id: int
    employee_id: str
    organization_id: int
    shift_id: int
    start_at: Any
    end_at: Any
    leave_reason: str
    remark: str
    status: str
    created_at: Any


def insert_leave_application(
    cur: Cursor,
    *,
    employee_id: str,
    organization_id: int,
    shift_id: int,
    start_at_utc: Any,
    end_at_utc: Any,
    leave_reason: str,
    remark: str,
    status: str,
    created_at_utc: Any,
) -> Tuple[int, Any]:
    cur.execute(
        """
        INSERT INTO public.leave_applications (
            employee_id,
            organization_id,
            shift_id,
            start_at,
            end_at,
            leave_reason,
            remark,
            status,
            created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, created_at
        """,
        (
            employee_id,
            organization_id,
            shift_id,
            start_at_utc,
            end_at_utc,
            leave_reason,
            remark,
            status,
            created_at_utc,
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0]), row[1]


def exists_overlapping_leave(
    cur: Cursor,
    *,
    employee_id: str,
    shift_id: int,
    new_start_at_utc: Any,
    new_end_at_utc: Any,
) -> bool:
    """
    仅与「进行中 / 已通过 / 已生效」类申请判重叠；REJECTED、CANCELLED、COMPLETED、EXPIRED
    等不在白名单内，不拦截新申请。
    """
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM public.leave_applications
            WHERE employee_id = %s
              AND shift_id = %s
              AND status IN ('APPROVING', 'APPROVED', 'EFFECTIVE')
              AND start_at <= %s
              AND end_at >= %s
        )
        """,
        (employee_id, shift_id, new_end_at_utc, new_start_at_utc),
    )
    row = cur.fetchone()
    return bool(row and row[0])


def get_by_id(*, leave_application_id: int) -> Optional[LeaveApplicationRow]:
    with get_cursor() as cur:
        return get_by_id_cur(cur, leave_application_id=leave_application_id)


def get_by_id_cur(cur: Cursor, *, leave_application_id: int) -> Optional[LeaveApplicationRow]:
    cur.execute(
        """
        SELECT id, employee_id, organization_id, shift_id, start_at, end_at,
               leave_reason, remark, status, created_at
        FROM public.leave_applications
        WHERE id = %s
        """,
        (leave_application_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return LeaveApplicationRow(*row)


def update_status_completed(
    cur: Cursor,
    *,
    leave_application_id: int,
    status: str,
    completed_at_utc: Any,
) -> int:
    cur.execute(
        """
        UPDATE public.leave_applications
        SET status = %s, completed_at = %s
        WHERE id = %s
        """,
        (status, completed_at_utc, leave_application_id),
    )
    return cur.rowcount
