from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, List, Optional, Sequence

from psycopg2.extensions import cursor as Cursor

from infra.db import get_cursor


@dataclass(frozen=True)
class AuditTaskRow:
    id: int
    log_id: int
    audit_started_at: Any
    employee_id: str
    target_date: Any
    audit_stage: str
    audit_result: str
    created_at: Any
    processed_at: Any
    retry_count: int
    error_message: Optional[str]
    task_status: str


def acquire_init_lock(
    cur: Cursor,
    *,
    shift_id: int,
    work_date,
    audit_stage: str,
) -> None:
    """
    初始化建任务并发兜底（不改表结构前提下的最小修正）：
    - 同一 shift + 同一 work_date + 同一 stage 的初始化批次，使用 PG 事务级 advisory lock 串行化

    背景：
    - audit_task_queue 唯一键包含 log_id，无法用 ON CONFLICT 防止“不同 log_id 的重复整批插入”
    - 因此必须用业务维度锁，防止并发同时通过 exists 检查
    """
    ymd = int(work_date.strftime("%Y%m%d")) if hasattr(work_date, "strftime") else int(work_date)
    stage_code = 1 if audit_stage == "CHECKIN" else 2 if audit_stage == "CHECKOUT" else 9
    lock_key = int(shift_id) * 1000000000 + int(ymd) * 10 + stage_code
    cur.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))


def exists_any_task_for_stage(
    cur: Cursor,
    *,
    employee_ids: Sequence[str],
    target_date,
    audit_stage: str,
) -> bool:
    if not employee_ids:
        return False
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM public.audit_task_queue
            WHERE target_date = %s
              AND audit_stage = %s
              AND employee_id IN %s
        )
        """,
        (target_date, audit_stage, tuple(employee_ids)),
    )
    row = cur.fetchone()
    return bool(row and row[0])


def list_existing_employee_ids_for_stage(
    cur: Cursor,
    *,
    employee_ids: Sequence[str],
    target_date,
    audit_stage: str,
) -> List[str]:
    """
    返回在指定 (target_date, audit_stage) 下，已存在审计任务的 employee_id 子集。
    仅用于 service 层做“缺失补建”差集，不在此处做业务决策。
    """
    if not employee_ids:
        return []
    cur.execute(
        """
        SELECT employee_id
        FROM public.audit_task_queue
        WHERE target_date = %s
          AND audit_stage = %s
          AND employee_id IN %s
        """,
        (target_date, audit_stage, tuple(employee_ids)),
    )
    rows = cur.fetchall()
    return [str(r[0]) for r in rows if r and r[0]]


def bulk_insert_init_tasks(
    cur: Cursor,
    *,
    log_id: int,
    audit_started_at_utc: Any,
    employee_ids: Sequence[str],
    target_date,
    audit_stage: str,
    created_at_utc: Any,
) -> int:
    """
    批量插入初始化审计任务：
    - audit_result='NONE'
    - task_status='PENDING'
    - retry_count=0
    - processed_at/error_message=NULL

    注意：本函数不做“是否该初始化”的决策；由 service 调用前先检查是否已存在任务。
    """
    if not employee_ids:
        return 0
    params: list[tuple[Any, ...]] = []
    for eid in employee_ids:
        params.append((log_id, audit_started_at_utc, eid, target_date, audit_stage, created_at_utc))

    cur.executemany(
        """
        INSERT INTO public.audit_task_queue (
            log_id,
            audit_started_at,
            employee_id,
            target_date,
            audit_stage,
            audit_result,
            created_at,
            processed_at,
            retry_count,
            error_message,
            task_status
        )
        VALUES (%s, %s, %s, %s, %s, 'NONE', %s, NULL, 0, NULL, 'PENDING')
        """,
        params,
    )
    return cur.rowcount


def list_runnable_tasks(*, limit: int = 200) -> List[AuditTaskRow]:
    """
    拉取可执行任务（worker 用）：
    - task_status in (PENDING, FAILED)
    - 按 created_at 升序
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, log_id, audit_started_at, employee_id, target_date, audit_stage,
                   audit_result, created_at, processed_at, retry_count, error_message, task_status
            FROM public.audit_task_queue
            WHERE task_status IN ('PENDING', 'FAILED')
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    return [AuditTaskRow(*r) for r in rows]


def claim_task_processing(*, task_id: int) -> bool:
    """抢占任务：PENDING/FAILED -> PROCESSING。"""
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE public.audit_task_queue
            SET task_status = 'PROCESSING'
            WHERE id = %s AND task_status IN ('PENDING', 'FAILED')
            """,
            (task_id,),
        )
        return cur.rowcount > 0


def update_after_run(
    cur: Cursor,
    *,
    task_id: int,
    audit_result: str,
    processed_at_utc: Any,
    task_status: str,
    error_message: Optional[str],
) -> None:
    cur.execute(
        """
        UPDATE public.audit_task_queue
        SET audit_result = %s,
            processed_at = %s,
            task_status = %s,
            error_message = %s
        WHERE id = %s AND task_status = 'PROCESSING'
        """,
        (audit_result, processed_at_utc, task_status, error_message, task_id),
    )


def mark_system_failed(
    cur: Cursor,
    *,
    task_id: int,
    processed_at_utc: Any,
    retry_count: int,
    error_message: str,
) -> None:
    cur.execute(
        """
        UPDATE public.audit_task_queue
        SET task_status = 'FAILED',
            processed_at = %s,
            retry_count = %s,
            error_message = %s
        WHERE id = %s AND task_status = 'PROCESSING'
        """,
        (processed_at_utc, retry_count, error_message, task_id),
    )


def increment_retry_count(*, task_id: int) -> int:
    """worker 侧辅助：retry_count + 1，返回新值。"""
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE public.audit_task_queue
            SET retry_count = COALESCE(retry_count, 0) + 1
            WHERE id = %s
            RETURNING retry_count
            """,
            (task_id,),
        )
        row = cur.fetchone()
    if not row:
        return 0
    return int(row[0] or 0)

