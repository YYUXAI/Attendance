from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from psycopg2.extensions import cursor as Cursor

from infra.db import get_cursor


@dataclass(frozen=True)
class TemporaryLeaveApplicationRow:
    id: int
    employee_id: str
    organization_id: int
    shift_id: int
    start_at: Any
    end_at: Any
    leave_reason: str
    remark: Any
    status: str
    created_at: Any
    completed_at: Any


def insert_submitted(
    cur: Cursor,
    *,
    employee_id: str,
    organization_id: int,
    shift_id: int,
    start_at_utc: Any,
    end_at_utc: Any,
    leave_reason: str,
    created_at_utc: Any,
) -> Tuple[int, Any]:
    cur.execute(
        """
        INSERT INTO public.temporary_leave_applications (
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
        VALUES (%s, %s, %s, %s, %s, %s, NULL, 'SUBMITTED', %s)
        RETURNING id, created_at
        """,
        (
            employee_id,
            organization_id,
            shift_id,
            start_at_utc,
            end_at_utc,
            leave_reason,
            created_at_utc,
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0]), row[1]


def update_status_submitted_to_approving(cur: Cursor, *, application_id: int) -> int:
    cur.execute(
        """
        UPDATE public.temporary_leave_applications
        SET status = 'APPROVING'
        WHERE id = %s AND status = 'SUBMITTED'
        """,
        (application_id,),
    )
    return int(cur.rowcount)


def get_by_id(*, application_id: int) -> Optional[TemporaryLeaveApplicationRow]:
    with get_cursor() as cur:
        return get_by_id_cur(cur, application_id=application_id)


def get_by_id_cur(cur: Cursor, *, application_id: int) -> Optional[TemporaryLeaveApplicationRow]:
    cur.execute(
        """
        SELECT id, employee_id, organization_id, shift_id, start_at, end_at,
               leave_reason, remark, status, created_at, completed_at
        FROM public.temporary_leave_applications
        WHERE id = %s
        """,
        (application_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return TemporaryLeaveApplicationRow(*row)


def update_rejected_from_approving(
    cur: Cursor,
    *,
    application_id: int,
    completed_at_utc: Any,
) -> int:
    cur.execute(
        """
        UPDATE public.temporary_leave_applications
        SET status = 'REJECTED', completed_at = %s
        WHERE id = %s AND status = 'APPROVING'
        """,
        (completed_at_utc, application_id),
    )
    return int(cur.rowcount)


def update_approved_from_approving(
    cur: Cursor,
    *,
    application_id: int,
    completed_at_utc: Optional[Any],
) -> int:
    cur.execute(
        """
        UPDATE public.temporary_leave_applications
        SET status = 'APPROVED', completed_at = %s
        WHERE id = %s AND status = 'APPROVING'
        """,
        (completed_at_utc, application_id),
    )
    return int(cur.rowcount)


def update_effective_from_approved(cur: Cursor, *, application_id: int) -> int:
    """APPROVED -> EFFECTIVE，WHERE status='APPROVED'。"""
    cur.execute(
        """
        UPDATE public.temporary_leave_applications
        SET status = 'EFFECTIVE'
        WHERE id = %s AND status = 'APPROVED'
        """,
        (application_id,),
    )
    return int(cur.rowcount)


def update_effective_from_approved_by_id(
    cur: Cursor,
    *,
    application_id: int,
    completed_at_utc: Optional[Any],
) -> int:
    """
    APPROVED -> EFFECTIVE；显式带 completed_at（轮询路径可置 NULL）。
    """
    cur.execute(
        """
        UPDATE public.temporary_leave_applications
        SET status = 'EFFECTIVE', completed_at = %s
        WHERE id = %s AND status = 'APPROVED'
        """,
        (completed_at_utc, application_id),
    )
    return int(cur.rowcount)


def update_completed_from_effective_by_id(
    cur: Cursor,
    *,
    application_id: int,
    completed_at_utc: Any,
) -> int:
    """EFFECTIVE -> COMPLETED，WHERE status='EFFECTIVE'。"""
    cur.execute(
        """
        UPDATE public.temporary_leave_applications
        SET status = 'COMPLETED', completed_at = %s
        WHERE id = %s AND status = 'EFFECTIVE'
        """,
        (completed_at_utc, application_id),
    )
    return int(cur.rowcount)


def update_expired_from_approved_by_id(
    cur: Cursor,
    *,
    application_id: int,
    completed_at_utc: Any,
) -> int:
    """APPROVED -> EXPIRED（窗口已过仍未生效），WHERE status='APPROVED'。"""
    cur.execute(
        """
        UPDATE public.temporary_leave_applications
        SET status = 'EXPIRED', completed_at = %s
        WHERE id = %s AND status = 'APPROVED'
        """,
        (completed_at_utc, application_id),
    )
    return int(cur.rowcount)


def list_apps_ready_to_effective(*, now_utc: Any, limit: int) -> List[TemporaryLeaveApplicationRow]:
    """status=APPROVED 且 start_at <= now < end_at。"""
    lim = max(1, min(int(limit), 500))
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, employee_id, organization_id, shift_id, start_at, end_at,
                   leave_reason, remark, status, created_at, completed_at
            FROM public.temporary_leave_applications
            WHERE status = 'APPROVED'
              AND start_at <= %s
              AND %s < end_at
            ORDER BY id ASC
            LIMIT %s
            """,
            (now_utc, now_utc, lim),
        )
        rows = cur.fetchall() or []
    return [TemporaryLeaveApplicationRow(*r) for r in rows]


def list_apps_ready_to_complete(*, now_utc: Any, limit: int) -> List[TemporaryLeaveApplicationRow]:
    """status=EFFECTIVE 且 now >= end_at。"""
    lim = max(1, min(int(limit), 500))
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, employee_id, organization_id, shift_id, start_at, end_at,
                   leave_reason, remark, status, created_at, completed_at
            FROM public.temporary_leave_applications
            WHERE status = 'EFFECTIVE'
              AND end_at <= %s
            ORDER BY id ASC
            LIMIT %s
            """,
            (now_utc, lim),
        )
        rows = cur.fetchall() or []
    return [TemporaryLeaveApplicationRow(*r) for r in rows]


def list_apps_approved_past_end(*, now_utc: Any, limit: int) -> List[TemporaryLeaveApplicationRow]:
    """status=APPROVED 且 now >= end_at（从未进入生效窗口，应 EXPIRED）。"""
    lim = max(1, min(int(limit), 500))
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, employee_id, organization_id, shift_id, start_at, end_at,
                   leave_reason, remark, status, created_at, completed_at
            FROM public.temporary_leave_applications
            WHERE status = 'APPROVED'
              AND end_at <= %s
            ORDER BY id ASC
            LIMIT %s
            """,
            (now_utc, lim),
        )
        rows = cur.fetchall() or []
    return [TemporaryLeaveApplicationRow(*r) for r in rows]
