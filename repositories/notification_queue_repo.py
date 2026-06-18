from __future__ import annotations

from datetime import date
from typing import Any

from psycopg2.extensions import cursor as Cursor

from infra.db import get_cursor
from infra.audit_notice_key import RELATED_EVENT_NAME_AUDIT_NOTICE, encode_shift_work_date_key
from infra.qc_shift_summary_notice_key import RELATED_EVENT_NAME_QC_SHIFT_SUMMARY

# docs05：质检模块 2004（不得复用为其它语义）
TEMPLATE_QC_ROUND_START_GROUP_NOTICE = 2004
# docs05：质检模块 2005（班次结束后整班质检汇总群公告）
TEMPLATE_QC_SHIFT_SUMMARY_GROUP_NOTICE = 2005


def insert_qc_round_start_pending(
    cur: Cursor,
    *,
    log_id: int,
    notify_tg_id: int,
    reply_content: str,
    created_at_utc: Any,
) -> None:
    """质检轮次开始群公告入队；仅包装 template_id=2004，不改变 insert_pending_notification 语义。"""
    insert_pending_notification(
        cur,
        log_id=log_id,
        notify_tg_id=notify_tg_id,
        template_id=TEMPLATE_QC_ROUND_START_GROUP_NOTICE,
        reply_content=reply_content,
        attachment_id=None,
        created_at_utc=created_at_utc,
    )


def exists_audit_notice_by_business_key(
    *,
    shift_id: int,
    work_date: date,
    notify_tg_id: int,
    template_id: int,
) -> bool:
    """
    审计通知缺失检查（按业务语义维度防重）：
    - 班次（shift_id）
    - 工作日（work_date，上班日）
    - 接收对象（notify_tg_id）
    - template_id

    注意：不依赖 log_id（log_id 不是业务对象 ID）。
    """
    key = encode_shift_work_date_key(shift_id=shift_id, work_date=work_date)
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM public.notification_queue nq
                JOIN public.event_logs el ON el.id = nq.log_id
                WHERE nq.template_id = %s
                  AND nq.notify_tg_id = %s
                  AND el.related_event_name = %s
                  AND el.related_event_id = %s
            )
            """,
            (template_id, notify_tg_id, RELATED_EVENT_NAME_AUDIT_NOTICE, key),
        )
        row = cur.fetchone()
    return bool(row and row[0])


def exists_audit_notice_for_group_on_work_date(
    *,
    notify_tg_id: int,
    work_date: date,
    template_id: int,
) -> bool:
    """
    同一 Telegram 群、同一上班日是否已有该 template 的审计通知（不限 shift_id）。
    用于多班次共用 attendance_group_id 时避免重复群公告。
    """
    ymd = int(work_date.strftime("%Y%m%d"))
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM public.notification_queue nq
                JOIN public.event_logs el ON el.id = nq.log_id
                WHERE nq.template_id = %s
                  AND nq.notify_tg_id = %s
                  AND el.related_event_name = %s
                  AND (el.related_event_id %% 100000000) = %s
            )
            """,
            (template_id, int(notify_tg_id), RELATED_EVENT_NAME_AUDIT_NOTICE, ymd),
        )
        row = cur.fetchone()
    return bool(row and row[0])


def insert_audit_notice_if_missing(
    cur: Cursor,
    *,
    shift_id: int,
    work_date: date,
    notify_tg_id: int,
    template_id: int,
    reply_content: str,
    created_at_utc: Any,
) -> bool:
    """
    审计通知缺失补建（并发安全，按业务语义防重）：
    - 用 advisory lock 串行化同一业务键（shift_id+work_date+notify_tg_id+template_id）
    - 在同一事务内再次 EXISTS 检查，确实缺失才插入
    - 写入 event_logs（NOTIFICATION_TRIGGERED / audit_notice / key / CREATED）并返回 log_id
    - 写入 notification_queue（PENDING / NONE / retry_count=0）

    注意：此处是“缺失补建”，不是“发送失败重试”。
    """
    key = encode_shift_work_date_key(shift_id=shift_id, work_date=work_date)
    # 事务级锁：避免并发重复补建（notification_queue 唯一键包含 log_id，无法靠 ON CONFLICT 防重）
    # 使用 PG 双 int 形式避免 bigint 编码碰撞：
    # (k1, k2) = (shift+day key, receiver+template key)
    k1 = int(key) & 0x7FFFFFFF
    k2 = ((int(template_id) & 0xFFFF) << 16) ^ (int(notify_tg_id) & 0xFFFF)
    cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (k1, k2))

    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM public.notification_queue nq
            JOIN public.event_logs el ON el.id = nq.log_id
            WHERE nq.template_id = %s
              AND nq.notify_tg_id = %s
              AND el.related_event_name = %s
              AND el.related_event_id = %s
        )
        """,
        (template_id, notify_tg_id, RELATED_EVENT_NAME_AUDIT_NOTICE, key),
    )
    row = cur.fetchone()
    if row and row[0]:
        return False

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
        VALUES ('NOTIFICATION_TRIGGERED', %s, 'CREATED', %s, %s, NULL, 0, NULL)
        RETURNING id
        """,
        (RELATED_EVENT_NAME_AUDIT_NOTICE, key, created_at_utc),
    )
    log_row = cur.fetchone()
    if not log_row:
        raise RuntimeError("event_logs insert returned no id")
    log_id = int(log_row[0])

    insert_pending_notification(
        cur,
        log_id=log_id,
        notify_tg_id=notify_tg_id,
        template_id=template_id,
        reply_content=reply_content,
        attachment_id=None,
        created_at_utc=created_at_utc,
    )
    return True


def insert_qc_shift_summary_if_missing(
    cur: Cursor,
    *,
    shift_id: int,
    work_date: date,
    notify_tg_id: int,
    template_id: int,
    reply_content: str,
    created_at_utc: Any,
) -> bool:
    """
    班次质检汇总（2005）缺失补建（并发安全，按业务语义防重）：
    - advisory lock 串行化 (shift_id+work_date+notify_tg_id+template_id)
    - 事务内 EXISTS：已存在 notification_queue + event_logs 业务键则不再插入
    - 写入 event_logs（NOTIFICATION_TRIGGERED / qc_shift_summary / key / CREATED）
    - 写入 notification_queue

    注意：这是「任务缺失补建」，发送失败重试由 notification_worker 负责，禁止再插新行。
    """
    key = encode_shift_work_date_key(shift_id=shift_id, work_date=work_date)
    k1 = int(key) & 0x7FFFFFFF
    k2 = ((int(template_id) & 0xFFFF) << 16) ^ (int(notify_tg_id) & 0xFFFF)
    cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (k1, k2))

    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM public.notification_queue nq
            JOIN public.event_logs el ON el.id = nq.log_id
            WHERE nq.template_id = %s
              AND nq.notify_tg_id = %s
              AND el.related_event_name = %s
              AND el.related_event_id = %s
        )
        """,
        (template_id, notify_tg_id, RELATED_EVENT_NAME_QC_SHIFT_SUMMARY, key),
    )
    row = cur.fetchone()
    if row and row[0]:
        return False

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
        VALUES ('NOTIFICATION_TRIGGERED', %s, 'CREATED', %s, %s, NULL, 0, NULL)
        RETURNING id
        """,
        (RELATED_EVENT_NAME_QC_SHIFT_SUMMARY, key, created_at_utc),
    )
    log_row = cur.fetchone()
    if not log_row:
        raise RuntimeError("event_logs insert returned no id")
    log_id = int(log_row[0])

    insert_pending_notification(
        cur,
        log_id=log_id,
        notify_tg_id=notify_tg_id,
        template_id=template_id,
        reply_content=reply_content,
        attachment_id=None,
        created_at_utc=created_at_utc,
    )
    return True


def insert_pending_notification(
    cur: Cursor,
    *,
    log_id: int,
    notify_tg_id: int,
    template_id: int,
    reply_content: str,
    attachment_id: str | None,
    created_at_utc: Any,
) -> None:
    """
    通知任务入队（异步）。

    docs05 强约束：
    - 仅用于进入 notification_queue 的异步通知任务
    - 禁止 template_id = NULL
    - worker 只发送 reply_content，不允许基于 template_id 拼装文案

    docs02 / docs03：
    - log_id 必填（来源 event_logs.id）
    - 初始：task_status='PENDING'、delivery_result='NONE'、retry_count=0
    """
    cur.execute(
        """
        INSERT INTO public.notification_queue (
            log_id,
            notify_tg_id,
            template_id,
            reply_content,
            attachment_id,
            delivery_result,
            created_at,
            processed_at,
            retry_count,
            error_message,
            task_status
        )
        VALUES (%s, %s, %s, %s, %s, 'NONE', %s, NULL, 0, NULL, 'PENDING')
        """,
        (log_id, notify_tg_id, template_id, reply_content, attachment_id, created_at_utc),
    )


def claim_next_task_for_processing(cur: Cursor) -> dict[str, Any] | None:
    """
    worker 抢占下一条待处理任务（按 created_at 顺序）。

    口径：
    - 仅抢占 task_status in (PENDING, RETRYING)
    - 通过 FOR UPDATE SKIP LOCKED 防止并发重复处理
    - 抢占后置为 PROCESSING
    """
    cur.execute(
        """
        SELECT nq.id, nq.log_id, nq.notify_tg_id, nq.template_id, nq.reply_content, nq.attachment_id,
               nq.delivery_result, nq.created_at, nq.processed_at, nq.retry_count, nq.error_message, nq.task_status,
               el.related_event_name, el.related_event_id
        FROM public.notification_queue nq
        JOIN public.event_logs el ON el.id = nq.log_id
        WHERE nq.task_status IN ('PENDING', 'RETRYING')
        ORDER BY nq.created_at ASC
        FOR UPDATE SKIP LOCKED
        LIMIT 1
        """
    )
    row = cur.fetchone()
    if not row:
        return None
    (
        task_id,
        log_id,
        notify_tg_id,
        template_id,
        reply_content,
        attachment_id,
        delivery_result,
        created_at,
        processed_at,
        retry_count,
        error_message,
        task_status,
        related_event_name,
        related_event_id,
    ) = row
    cur.execute(
        """
        UPDATE public.notification_queue
        SET task_status = 'PROCESSING'
        WHERE id = %s AND task_status IN ('PENDING', 'RETRYING')
        """,
        (task_id,),
    )
    if cur.rowcount == 0:
        return None
    return {
        "id": int(task_id),
        "log_id": int(log_id),
        "notify_tg_id": int(notify_tg_id),
        "template_id": int(template_id),
        "reply_content": str(reply_content),
        "attachment_id": (str(attachment_id) if attachment_id is not None else None),
        "delivery_result": (str(delivery_result) if delivery_result is not None else None),
        "created_at": created_at,
        "processed_at": processed_at,
        "retry_count": int(retry_count or 0),
        "error_message": (str(error_message) if error_message is not None else None),
        "task_status": str(task_status),
        "related_event_name": str(related_event_name),
        "related_event_id": int(related_event_id),
    }


def mark_done_sent(
    cur: Cursor,
    *,
    task_id: int,
    processed_at_utc: Any,
) -> None:
    cur.execute(
        """
        UPDATE public.notification_queue
        SET task_status = 'DONE',
            delivery_result = 'SENT',
            processed_at = %s,
            error_message = NULL
        WHERE id = %s AND task_status = 'PROCESSING'
        """,
        (processed_at_utc, task_id),
    )


def mark_retrying_failed(
    cur: Cursor,
    *,
    task_id: int,
    retry_count: int,
    processed_at_utc: Any,
    error_message: str,
) -> None:
    cur.execute(
        """
        UPDATE public.notification_queue
        SET task_status = 'RETRYING',
            delivery_result = 'FAILED',
            retry_count = %s,
            processed_at = %s,
            error_message = %s
        WHERE id = %s AND task_status = 'PROCESSING'
        """,
        (retry_count, processed_at_utc, error_message, task_id),
    )


def mark_done_undeliverable(
    cur: Cursor,
    *,
    task_id: int,
    retry_count: int,
    processed_at_utc: Any,
    error_message: str,
) -> None:
    cur.execute(
        """
        UPDATE public.notification_queue
        SET task_status = 'DONE',
            delivery_result = 'UNDELIVERABLE',
            retry_count = %s,
            processed_at = %s,
            error_message = %s
        WHERE id = %s AND task_status = 'PROCESSING'
        """,
        (retry_count, processed_at_utc, error_message, task_id),
    )
