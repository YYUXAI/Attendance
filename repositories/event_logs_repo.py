from __future__ import annotations

from typing import Any

from psycopg2.extensions import cursor as Cursor


def insert_notification_triggered(
    cur: Cursor,
    *,
    related_event_name: str,
    related_event_id: int,
    created_at_utc: Any,
    event_name: str = "NOTIFICATION_TRIGGERED",
    result: str = "CREATED",
) -> int:
    """
    docs00 口径：event_logs 不是幂等边界，允许同一业务事件多条记录。

    仅用于当前最小闭环：通知触发入队时创建一条 event_logs，并返回 log_id 供 notification_queue 引用。

    注意：event_name / related_event_name / result 不允许在此处扩展枚举；由上游按口径传入或使用默认值。
    """
    cur.execute(
        """
        INSERT INTO public.event_logs (
            event_name,
            related_event_name,
            result,
            related_event_id,
            created_at,
            processed_at,
            retry_count,
            error_message
        )
        VALUES (%s, %s, %s, %s, %s, NULL, 0, NULL)
        RETURNING id
        """,
        (event_name, related_event_name, result, related_event_id, created_at_utc),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError("event_logs insert returned no id")
    return int(row[0])


def insert_event(
    cur: Cursor,
    *,
    event_name: str,
    related_event_name: str,
    related_event_id: int,
    result: str,
    created_at_utc: Any,
) -> int:
    """
    通用事件日志写入（不作为幂等边界）。

    注意：event_name / related_event_name 的业务枚举由上层模块约束；
    本函数只负责落库并返回 id。
    """
    cur.execute(
        """
        INSERT INTO public.event_logs (
            event_name,
            related_event_name,
            result,
            related_event_id,
            created_at,
            processed_at,
            retry_count,
            error_message
        )
        VALUES (%s, %s, %s, %s, %s, NULL, 0, NULL)
        RETURNING id
        """,
        (event_name, related_event_name, result, related_event_id, created_at_utc),
    )
    row = cur.fetchone()
    if not row:
        raise RuntimeError("event_logs insert returned no id")
    return int(row[0])


def claim_qc_round_closeout_processed_at_cur(
    cur: Cursor,
    *,
    log_id: int,
    at_utc: Any,
    terminal_statuses: tuple[str, ...],
) -> bool:
    """
    质检轮次完结公告：在确认同一 log_id 下全部任务已进入终态后，
    原子将 QC_ROUND_OPENED 对应 event_logs.processed_at 从 NULL 置为非 NULL。
    返回是否成功占位（幂等：已占位则不再更新）。
    """
    cur.execute(
        """
        UPDATE public.event_logs el
        SET processed_at = %s,
            error_message = NULL
        WHERE el.id = %s
          AND el.processed_at IS NULL
          AND el.event_name = 'QC_ROUND_OPENED'
          AND EXISTS (SELECT 1 FROM public.qc_task_queue qt WHERE qt.log_id = el.id)
          AND NOT EXISTS (
              SELECT 1
              FROM public.qc_task_queue qt2
              WHERE qt2.log_id = el.id
                AND NOT (qt2.status = ANY(%s))
          )
        RETURNING el.id
        """,
        (at_utc, int(log_id), list(terminal_statuses)),
    )
    row = cur.fetchone()
    return bool(row and row[0] is not None)


def rollback_qc_round_closeout_processed_at_cur(
    cur: Cursor,
    *,
    log_id: int,
    error_message: str | None,
) -> int:
    """发送失败时回滚完结公告幂等占位，并写入 error_message 便于排查。"""
    cur.execute(
        """
        UPDATE public.event_logs
        SET processed_at = NULL,
            error_message = %s
        WHERE id = %s
          AND event_name = 'QC_ROUND_OPENED'
        """,
        (error_message, int(log_id)),
    )
    return int(cur.rowcount)

