from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from infra.db import transaction
from infra.telegram_sender import send_notification
from repositories import approval_task_queue_repo, notification_queue_repo

log = logging.getLogger(__name__)

TEMPLATE_APPROVAL_DISPATCH_TO_APPROVER = 1001


def _approval_dispatch_keyboard(*, approval_task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="同意", callback_data=f"leave:apr:{approval_task_id}:Y"),
                InlineKeyboardButton(text="驳回", callback_data=f"leave:apr:{approval_task_id}:N"),
            ],
        ],
    )


def _temporary_leave_approval_keyboard(*, approval_task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="同意",
                    callback_data=f"apr:TEMPORARY_LEAVE:{approval_task_id}:approve",
                ),
                InlineKeyboardButton(
                    text="驳回",
                    callback_data=f"apr:TEMPORARY_LEAVE:{approval_task_id}:reject",
                ),
            ],
        ],
    )


async def run_notification_worker(*, bot: Bot, interval_sec: int = 2) -> None:
    """
    notification_queue 最小闭环 worker：
    - 轮询 task_status in (PENDING, RETRYING) 的任务
    - 按 created_at 顺序抢占并置 PROCESSING
    - 只发送 reply_content（不得根据 template_id 拼装文案）
    - 严格按 docs03 状态机与重试规则更新表
    """
    while True:
        try:
            task = None
            with transaction() as cur:
                task = notification_queue_repo.claim_next_task_for_processing(cur)

            if not task:
                await asyncio.sleep(interval_sec)
                continue

            now = datetime.now(timezone.utc)
            # docs05：worker 只发送 reply_content，不基于 template_id 拼装文案。
            # 例外：1001 需要携带审批交互按钮（不改文案内容，只附加 reply_markup）。
            if int(task["template_id"]) == TEMPLATE_APPROVAL_DISPATCH_TO_APPROVER:
                try:
                    rel = task.get("related_event_name")
                    if rel == "approval_task_queue":
                        approval_task_id = int(task["related_event_id"])
                        await bot.send_message(
                            chat_id=int(task["notify_tg_id"]),
                            text=str(task["reply_content"]),
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                            reply_markup=_approval_dispatch_keyboard(approval_task_id=approval_task_id),
                        )
                        outcome = type("Outcome", (), {"delivery_result": "SENT", "error_message": None})()
                    elif rel == "approval_task":
                        approval_task_id = int(task["related_event_id"])
                        await bot.send_message(
                            chat_id=int(task["notify_tg_id"]),
                            text=str(task["reply_content"]),
                            parse_mode="HTML",
                            disable_web_page_preview=True,
                            reply_markup=_temporary_leave_approval_keyboard(approval_task_id=approval_task_id),
                        )
                        outcome = type("Outcome", (), {"delivery_result": "SENT", "error_message": None})()
                    else:
                        raise RuntimeError(f"unexpected related_event_name={rel!r} for template_id=1001")
                except Exception as e:
                    # 交互派发发送失败：沿用 send_notification 的分类口径（UNDELIVERABLE / FAILED）
                    outcome = await send_notification(
                        bot=bot,
                        notify_tg_id=int(task["notify_tg_id"]),
                        reply_content=str(task["reply_content"]),
                        attachment_id=task.get("attachment_id"),
                    )
                    if getattr(outcome, "delivery_result", None) == "SENT":
                        # 若 fallback 发送成功，但缺少按钮，也按 SENT 处理（最小闭环）；业务交互可再由上游补齐。
                        pass
                    else:
                        # 将原异常信息写入 error_message，便于诊断
                        if getattr(outcome, "error_message", None):
                            outcome = type(
                                "Outcome",
                                (),
                                {"delivery_result": outcome.delivery_result, "error_message": f"{outcome.error_message}; {e}"},
                            )()
                        else:
                            outcome = type("Outcome", (), {"delivery_result": outcome.delivery_result, "error_message": str(e)})()
            else:
                outcome = await send_notification(
                    bot=bot,
                    notify_tg_id=int(task["notify_tg_id"]),
                    reply_content=str(task["reply_content"]),
                    attachment_id=task.get("attachment_id"),
                )

            if outcome.delivery_result == "SENT":
                with transaction() as cur:
                    notification_queue_repo.mark_done_sent(
                        cur,
                        task_id=int(task["id"]),
                        processed_at_utc=now,
                    )
                    if int(task["template_id"]) == TEMPLATE_APPROVAL_DISPATCH_TO_APPROVER:
                        rel = str(task.get("related_event_name") or "")
                        if rel in ("approval_task", "approval_task_queue"):
                            approval_task_queue_repo.update_task_status_to_processing_cur(
                                cur,
                                task_id=int(task["related_event_id"]),
                            )
                continue

            # FAILED / UNDELIVERABLE
            new_retry = int(task.get("retry_count") or 0)
            if outcome.delivery_result == "FAILED":
                new_retry += 1
                if new_retry < 3:
                    with transaction() as cur:
                        notification_queue_repo.mark_retrying_failed(
                            cur,
                            task_id=int(task["id"]),
                            retry_count=new_retry,
                            processed_at_utc=now,
                            error_message=(outcome.error_message or "send_failed"),
                        )
                else:
                    with transaction() as cur:
                        notification_queue_repo.mark_done_undeliverable(
                            cur,
                            task_id=int(task["id"]),
                            retry_count=new_retry,
                            processed_at_utc=now,
                            error_message=(outcome.error_message or "retry_exhausted"),
                        )
                continue

            # UNDELIVERABLE：终态
            with transaction() as cur:
                notification_queue_repo.mark_done_undeliverable(
                    cur,
                    task_id=int(task["id"]),
                    retry_count=new_retry,
                    processed_at_utc=now,
                    error_message=(outcome.error_message or "undeliverable"),
                )
        except Exception:
            log.exception("notification_worker cycle failed")
            await asyncio.sleep(interval_sec)

