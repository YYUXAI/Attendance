from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional

from psycopg2.extensions import cursor as Cursor

from infra.db import get_cursor


@dataclass(frozen=True)
class ApprovalTaskRow:
    id: int
    application_type: str
    application_id: int
    application_submitted_at: Any
    approval_level: int
    applicant_employee_id: str
    approver_employee_id: str
    task_status: str
    approval_result: str
    approver_remark: Optional[str]
    task_created_at: Any


def insert_approval_task_returning_id(
    cur: Cursor,
    *,
    application_type: str,
    application_id: int,
    application_submitted_at: Any,
    approval_level: int,
    applicant_employee_id: str,
    approver_employee_id: str,
    task_status: str,
    approval_result: str,
    task_created_at_utc: Any,
) -> int:
    cur.execute(
        """
        INSERT INTO public.approval_task_queue (
            application_type,
            application_id,
            application_submitted_at,
            approval_level,
            applicant_employee_id,
            approver_employee_id,
            task_status,
            approval_result,
            approver_remark,
            task_created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, %s)
        RETURNING id
        """,
        (
            application_type,
            application_id,
            application_submitted_at,
            approval_level,
            applicant_employee_id,
            approver_employee_id,
            task_status,
            approval_result,
            task_created_at_utc,
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def insert_leave_approval_task(
    cur: Cursor,
    *,
    application_type: str,
    application_id: int,
    application_submitted_at: Any,
    approval_level: int,
    applicant_employee_id: str,
    approver_employee_id: str,
    task_status: str,
    approval_result: str,
    task_created_at_utc: Any,
) -> None:
    """
    application_type：业务口径为 LEAVE；若数据库 CHECK 不同，请改为 DBA 提供的合法值。
    approver_remark：插入 NULL（不显式写列则需在 SQL 中省略；这里用 NULL）。
    """
    cur.execute(
        """
        INSERT INTO public.approval_task_queue (
            application_type,
            application_id,
            application_submitted_at,
            approval_level,
            applicant_employee_id,
            approver_employee_id,
            task_status,
            approval_result,
            approver_remark,
            task_created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NULL, %s)
        """,
        (
            application_type,
            application_id,
            application_submitted_at,
            approval_level,
            applicant_employee_id,
            approver_employee_id,
            task_status,
            approval_result,
            task_created_at_utc,
        ),
    )


def list_pending_tasks(*, limit: int = 50) -> List[ApprovalTaskRow]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, application_type, application_id, application_submitted_at, approval_level,
                   applicant_employee_id, approver_employee_id, task_status, approval_result,
                   approver_remark, task_created_at
            FROM public.approval_task_queue
            WHERE task_status = 'PENDING'
            ORDER BY task_created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [ApprovalTaskRow(*r) for r in rows]


def list_pending_leave_dispatch_tasks(*, limit: int = 50) -> List[ApprovalTaskRow]:
    """
    休假审批派发轮询专用：仅 LEAVE，避免 TEMPORARY_LEAVE 等已入队通知的任务反复进入派发内核。
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, application_type, application_id, application_submitted_at, approval_level,
                   applicant_employee_id, approver_employee_id, task_status, approval_result,
                   approver_remark, task_created_at
            FROM public.approval_task_queue
            WHERE task_status = 'PENDING' AND application_type = 'LEAVE'
            ORDER BY task_created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [ApprovalTaskRow(*r) for r in rows]


def get_by_id(*, task_id: int) -> Optional[ApprovalTaskRow]:
    with get_cursor() as cur:
        return get_by_id_cur(cur, task_id=task_id)


def get_by_id_cur(cur: Cursor, *, task_id: int) -> Optional[ApprovalTaskRow]:
    cur.execute(
        """
        SELECT id, application_type, application_id, application_submitted_at, approval_level,
               applicant_employee_id, approver_employee_id, task_status, approval_result,
               approver_remark, task_created_at
        FROM public.approval_task_queue
        WHERE id = %s
        """,
        (task_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    return ApprovalTaskRow(*row)


def find_pending_leave_task_id_by_application_id(*, application_id: int) -> Optional[int]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM public.approval_task_queue
            WHERE application_type = 'LEAVE'
              AND application_id = %s
              AND task_status = 'PENDING'
            ORDER BY id ASC
            LIMIT 1
            """,
            (application_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return int(row[0])


def update_task_status_to_processing(*, task_id: int) -> int:
    """仅 PENDING → PROCESSING；返回受影响行数。"""
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE public.approval_task_queue
            SET task_status = 'PROCESSING'
            WHERE id = %s AND task_status = 'PENDING'
            """,
            (task_id,),
        )
        return cur.rowcount


def update_task_status_to_processing_cur(cur: Cursor, *, task_id: int) -> int:
    """同事务内：仅 PENDING → PROCESSING；返回受影响行数。"""
    cur.execute(
        """
        UPDATE public.approval_task_queue
        SET task_status = 'PROCESSING'
        WHERE id = %s AND task_status = 'PENDING'
        """,
        (task_id,),
    )
    return cur.rowcount


def finalize_leave_task(
    cur: Cursor,
    *,
    task_id: int,
    approval_result: str,
    task_status_done: str,
    approver_remark: Optional[str],
    approved_at_utc: Any,
) -> int:
    cur.execute(
        """
        UPDATE public.approval_task_queue
        SET approval_result = %s,
            task_status = %s,
            approver_remark = %s,
            approved_at = %s
        WHERE id = %s AND task_status = 'PROCESSING'
        """,
        (approval_result, task_status_done, approver_remark, approved_at_utc, task_id),
    )
    return cur.rowcount


def get_latest_leave_approval_meta_by_application_id(*, application_id: int) -> Optional[tuple[str, Any]]:
    """
    用于对外通知展示“审批人 + 审批时间”。
    返回 (approver_employee_id, approved_at_utc)；若找不到则返回 None。
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT approver_employee_id, approved_at
            FROM public.approval_task_queue
            WHERE application_type = 'LEAVE'
              AND application_id = %s
              AND approved_at IS NOT NULL
            ORDER BY approved_at DESC
            LIMIT 1
            """,
            (application_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return str(row[0]), row[1]
