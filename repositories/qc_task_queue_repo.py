from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, List, Optional, Sequence

from psycopg2.extensions import cursor as Cursor

from infra.db import get_cursor


def acquire_round_open_lock(cur: Cursor, *, shift_id: int, work_date: date) -> None:
    """
    同一 (shift_id, work_date) 开新轮质检时串行化，避免并发重复开同一 qc_round。
    使用事务级 advisory lock（bigint），与 audit 初始化锁分 namespace。
    """
    ymd = int(work_date.strftime("%Y%m%d"))
    lock_key = 9_000_000_000_000_000 + int(shift_id) * 10_000_000_000 + int(ymd)
    cur.execute("SELECT pg_advisory_xact_lock(%s)", (lock_key,))


@dataclass(frozen=True)
class QcTaskQueueRow:
    id: int
    log_id: int
    employee_id: str
    shift_id: int
    qc_date: Any
    qc_round: int
    status: str
    task_result: str


@dataclass(frozen=True)
class QcTaskQueueRowLocked:
    id: int
    log_id: int
    employee_id: str
    shift_id: int
    qc_date: Any
    qc_round: int
    status: str
    task_result: str
    first_private_notify_sent_at: Any
    pending_confirm_file_id: Optional[str]
    created_at: Any


def lock_task_by_id_cur(cur: Cursor, *, task_id: int) -> Optional[QcTaskQueueRowLocked]:
    cur.execute(
        """
        SELECT id, log_id, employee_id, shift_id, qc_date, qc_round, status, task_result,
               first_private_notify_sent_at, pending_confirm_file_id, created_at
        FROM public.qc_task_queue
        WHERE id = %s
        FOR UPDATE
        """,
        (int(task_id),),
    )
    row = cur.fetchone()
    if not row:
        return None
    return QcTaskQueueRowLocked(*row)


def update_notified_to_waiting_submission_cur(cur: Cursor, *, task_id: int) -> int:
    cur.execute(
        """
        UPDATE public.qc_task_queue
        SET status = 'WAITING_SUBMISSION'
        WHERE id = %s
          AND status = 'NOTIFIED'
        """,
        (int(task_id),),
    )
    return int(cur.rowcount)


def update_notified_first_cancel_cur(cur: Cursor, *, task_id: int) -> int:
    cur.execute(
        """
        UPDATE public.qc_task_queue
        SET status = 'CANCELLED',
            task_result = 'FAIL'
        WHERE id = %s
          AND status = 'NOTIFIED'
        """,
        (int(task_id),),
    )
    return int(cur.rowcount)


def update_upload_submitted_cur(cur: Cursor, *, task_id: int, file_id: str) -> int:
    cur.execute(
        """
        UPDATE public.qc_task_queue
        SET status = 'SUBMITTED',
            pending_confirm_file_id = %s
        WHERE id = %s
          AND status IN ('WAITING_SUBMISSION', 'SUBMITTED')
        """,
        (str(file_id), int(task_id)),
    )
    return int(cur.rowcount)


def update_second_cancel_cur(cur: Cursor, *, task_id: int) -> int:
    cur.execute(
        """
        UPDATE public.qc_task_queue
        SET status = 'WAITING_SUBMISSION',
            pending_confirm_file_id = NULL
        WHERE id = %s
          AND status = 'SUBMITTED'
        """,
        (int(task_id),),
    )
    return int(cur.rowcount)


def update_second_confirm_completed_cur(cur: Cursor, *, task_id: int) -> int:
    cur.execute(
        """
        UPDATE public.qc_task_queue
        SET status = 'COMPLETED',
            task_result = 'PASS'
        WHERE id = %s
          AND status = 'SUBMITTED'
        """,
        (int(task_id),),
    )
    return int(cur.rowcount)


def list_drawn_employee_ids_for_shift_date_cur(cur: Cursor, *, shift_id: int, qc_date: date) -> set[str]:
    cur.execute(
        """
        SELECT DISTINCT employee_id
        FROM public.qc_task_queue
        WHERE shift_id = %s
          AND qc_date = %s
        """,
        (int(shift_id), qc_date),
    )
    rows = cur.fetchall() or []
    return {str(r[0]) for r in rows if r and r[0] is not None}


def max_qc_round_for_shift_date_cur(cur: Cursor, *, shift_id: int, qc_date: date) -> int:
    cur.execute(
        """
        SELECT COALESCE(MAX(qc_round), 0)
        FROM public.qc_task_queue
        WHERE shift_id = %s
          AND qc_date = %s
        """,
        (int(shift_id), qc_date),
    )
    row = cur.fetchone()
    if not row:
        return 0
    return int(row[0] or 0)


def list_employee_ids_with_open_tasks_cur(
    cur: Cursor,
    *,
    shift_id: int,
    qc_date: date,
    employee_ids: Sequence[str],
) -> set[str]:
    """
    未终结任务：status 不在终态集合内（docs02 CHECK）。
    """
    if not employee_ids:
        return set()
    cur.execute(
        """
        SELECT DISTINCT employee_id
        FROM public.qc_task_queue
        WHERE shift_id = %s
          AND qc_date = %s
          AND employee_id IN %s
          AND status NOT IN ('COMPLETED', 'TIMEOUT', 'FAILED', 'CANCELLED', 'SKIPPED')
        """,
        (int(shift_id), qc_date, tuple(employee_ids)),
    )
    rows = cur.fetchall() or []
    return {str(r[0]) for r in rows if r and r[0] is not None}


def bulk_insert_round_tasks_cur(
    cur: Cursor,
    *,
    log_id: int,
    shift_id: int,
    qc_date: date,
    qc_round: int,
    employee_ids: Sequence[str],
    created_at_utc: Any,
) -> int:
    n = 0
    for eid in employee_ids:
        cur.execute(
            """
            INSERT INTO public.qc_task_queue (
                log_id,
                employee_id,
                shift_id,
                qc_date,
                qc_round,
                status,
                task_result,
                first_private_notify_sent_at,
                pending_confirm_file_id,
                created_at,
                processed_at,
                retry_count,
                error_message
            )
            VALUES (%s, %s, %s, %s, %s, 'PENDING', 'NONE', NULL, NULL, %s, NULL, 0, NULL)
            ON CONFLICT (log_id, employee_id) DO NOTHING
            """,
            (int(log_id), str(eid), int(shift_id), qc_date, int(qc_round), created_at_utc),
        )
        n += int(cur.rowcount)
    return n


def find_latest_active_upload_task_id_for_employee(*, employee_id: str) -> Optional[int]:
    """
    等待上传 / 二次确认阶段：status 为 WAITING_SUBMISSION 或 SUBMITTED。
    若存在多条，取 id 最大（最近一条）。
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM public.qc_task_queue
            WHERE employee_id = %s
              AND status IN ('WAITING_SUBMISSION', 'SUBMITTED')
            ORDER BY id DESC
            LIMIT 1
            """,
            (str(employee_id),),
        )
        row = cur.fetchone()
        if not row:
            return None
        return int(row[0])


def list_pending_first_private_notify(*, limit: int) -> List[QcTaskQueueRow]:
    lim = max(1, min(int(limit), 500))
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, log_id, employee_id, shift_id, qc_date, qc_round, status, task_result
            FROM public.qc_task_queue
            WHERE status = 'PENDING'
              AND first_private_notify_sent_at IS NULL
            ORDER BY id ASC
            LIMIT %s
            """,
            (lim,),
        )
        rows = cur.fetchall() or []
    return [QcTaskQueueRow(*r) for r in rows]


def list_task_ids_due_for_timeout(*, now_utc: Any, limit: int) -> List[int]:
    """
    已发出首条私信且超过 15 分钟仍未进入终态：NOTIFIED / WAITING_SUBMISSION / SUBMITTED。
    """
    lim = max(1, min(int(limit), 500))
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id
            FROM public.qc_task_queue
            WHERE (
                first_private_notify_sent_at IS NOT NULL
                AND first_private_notify_sent_at + INTERVAL '15 minutes' <= %s
                AND status IN ('NOTIFIED', 'WAITING_SUBMISSION', 'SUBMITTED')
            ) OR (
                status = 'PENDING'
                AND first_private_notify_sent_at IS NULL
                AND created_at + INTERVAL '15 minutes' <= %s
            )
            ORDER BY id ASC
            LIMIT %s
            """,
            (now_utc, now_utc, lim),
        )
        rows = cur.fetchall() or []
    return [int(r[0]) for r in rows if r and r[0] is not None]


def mark_timeout_terminal_cur(cur: Cursor, *, task_id: int) -> int:
    cur.execute(
        """
        UPDATE public.qc_task_queue
        SET status = 'TIMEOUT',
            task_result = 'TIMEOUT'
        WHERE id = %s
          AND (
              status IN ('NOTIFIED', 'WAITING_SUBMISSION', 'SUBMITTED')
              OR (status = 'PENDING' AND first_private_notify_sent_at IS NULL)
          )
        """,
        (int(task_id),),
    )
    return int(cur.rowcount)


def count_active_upload_tasks_for_employee(*, employee_id: str) -> int:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*)
            FROM public.qc_task_queue
            WHERE employee_id = %s
              AND status IN ('WAITING_SUBMISSION', 'SUBMITTED')
            """,
            (str(employee_id),),
        )
        row = cur.fetchone()
        if not row:
            return 0
        return int(row[0] or 0)


@dataclass(frozen=True)
class QcRoundCloseoutDisplayRow:
    employee_id: str
    english_name: Optional[str]
    qc_result_id: Optional[int]
    qc_result: Optional[str]
    attachment_id: Optional[str]


def list_log_ids_eligible_for_round_closeout_cur(
    cur: Cursor,
    *,
    terminal_statuses: Sequence[str],
    limit: int,
) -> List[int]:
    """
    选出「开轮日志仍为未处理占位」且该 log_id 下全部任务 status 均在终态集合内」的 log_id。
    """
    lim = max(1, min(int(limit), 200))
    cur.execute(
        """
        SELECT qt.log_id
        FROM public.qc_task_queue qt
        INNER JOIN public.event_logs el ON el.id = qt.log_id
        WHERE el.processed_at IS NULL
          AND el.event_name = 'QC_ROUND_OPENED'
        GROUP BY qt.log_id
        HAVING COUNT(*) FILTER (WHERE NOT (qt.status = ANY(%s))) = 0
        ORDER BY MIN(qt.id) ASC
        LIMIT %s
        """,
        (list(terminal_statuses), lim),
    )
    rows = cur.fetchall() or []
    return [int(r[0]) for r in rows if r and r[0] is not None]


def list_round_closeout_display_rows_cur(cur: Cursor, *, log_id: int) -> List[QcRoundCloseoutDisplayRow]:
    """按 log_id 拉取本轮展示行（不按 employee_id 取「最新」结果，仅按轮次键关联 qc_results）。"""
    cur.execute(
        """
        SELECT qt.employee_id,
               reg.english_name,
               qr.id,
               qr.result,
               qr.attachment_id
        FROM public.qc_task_queue qt
        LEFT JOIN public.qc_results qr
          ON qr.employee_id = qt.employee_id
         AND qr.shift_id = qt.shift_id
         AND qr.qc_date = qt.qc_date
         AND qr.qc_round = qt.qc_round
        LEFT JOIN public.registrations reg ON reg.employee_id = qt.employee_id
        WHERE qt.log_id = %s
        ORDER BY qt.employee_id ASC
        """,
        (int(log_id),),
    )
    rows = cur.fetchall() or []
    out: List[QcRoundCloseoutDisplayRow] = []
    for r in rows:
        if not r:
            continue
        eid, ename, qrid, qrslt, att = r[0], r[1], r[2], r[3], r[4]
        out.append(
            QcRoundCloseoutDisplayRow(
                employee_id=str(eid),
                english_name=str(ename) if ename is not None else None,
                qc_result_id=int(qrid) if qrid is not None else None,
                qc_result=str(qrslt) if qrslt is not None else None,
                attachment_id=str(att) if att is not None else None,
            )
        )
    return out


def get_shift_round_for_log_id_cur(cur: Cursor, *, log_id: int) -> Optional[tuple[int, Any, int]]:
    """返回 (shift_id, qc_date, qc_round)；同一 log_id 下应一致，取 MIN(id) 行。"""
    cur.execute(
        """
        SELECT shift_id, qc_date, qc_round
        FROM public.qc_task_queue
        WHERE log_id = %s
        ORDER BY id ASC
        LIMIT 1
        """,
        (int(log_id),),
    )
    row = cur.fetchone()
    if not row:
        return None
    return int(row[0]), row[1], int(row[2])


def list_log_ids_eligible_for_round_closeout(*, terminal_statuses: Sequence[str], limit: int) -> List[int]:
    with get_cursor() as cur:
        return list_log_ids_eligible_for_round_closeout_cur(cur, terminal_statuses=terminal_statuses, limit=limit)


def _coerce_to_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"expected date-like qc_date, got {type(value)!r}")


def list_distinct_shift_qc_date_pairs_for_summary(*, min_qc_date: date, limit: int) -> List[tuple[int, date]]:
    """
    枚举「库内已出现过的」班次质检业务日（qc_date），作为汇总锚点；
    不得用另一套日期计算替代库内 qc_date。
    """
    lim = max(1, min(int(limit), 500))
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT shift_id, qc_date
            FROM public.qc_task_queue
            WHERE qc_date >= %s
            ORDER BY qc_date ASC, shift_id ASC
            LIMIT %s
            """,
            (min_qc_date, lim),
        )
        rows = cur.fetchall() or []
    out: List[tuple[int, date]] = []
    for r in rows:
        if not r:
            continue
        out.append((int(r[0]), _coerce_to_date(r[1])))
    return out


def list_qc_rounds_for_shift_qc_date(*, shift_id: int, qc_date: date) -> List[int]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT qc_round
            FROM public.qc_task_queue
            WHERE shift_id = %s
              AND qc_date = %s
            ORDER BY qc_round ASC
            """,
            (int(shift_id), qc_date),
        )
        rows = cur.fetchall() or []
    return [int(r[0]) for r in rows if r and r[0] is not None]


def list_employee_ids_for_shift_qc_date_from_tasks(*, shift_id: int, qc_date: date) -> List[str]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT employee_id
            FROM public.qc_task_queue
            WHERE shift_id = %s
              AND qc_date = %s
            ORDER BY employee_id ASC
            """,
            (int(shift_id), qc_date),
        )
        rows = cur.fetchall() or []
    return [str(r[0]) for r in rows if r and r[0] is not None]


def list_employee_ids_for_shift_qc_date_round(*, shift_id: int, qc_date: date, qc_round: int) -> List[str]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT employee_id
            FROM public.qc_task_queue
            WHERE shift_id = %s
              AND qc_date = %s
              AND qc_round = %s
            ORDER BY employee_id ASC
            """,
            (int(shift_id), qc_date, int(qc_round)),
        )
        rows = cur.fetchall() or []
    return [str(r[0]) for r in rows if r and r[0] is not None]


def mark_first_private_notify_sent_cur(
    cur: Cursor,
    *,
    task_id: int,
    sent_at_utc: Any,
) -> int:
    cur.execute(
        """
        UPDATE public.qc_task_queue
        SET status = 'NOTIFIED',
            first_private_notify_sent_at = %s
        WHERE id = %s
          AND status = 'PENDING'
          AND first_private_notify_sent_at IS NULL
        """,
        (sent_at_utc, int(task_id)),
    )
    return int(cur.rowcount)
