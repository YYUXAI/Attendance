from __future__ import annotations



import asyncio

import logging

from datetime import datetime, timezone



from aiogram import Bot



from infra.db import transaction

from infra.disabled_features import is_disabled_notification_template

from infra.telegram_sender import send_notification

from repositories import notification_queue_repo



log = logging.getLogger(__name__)





async def run_notification_worker(*, bot: Bot, interval_sec: int = 2) -> None:

    """

    notification_queue 最小闭环 worker：

    - 轮询 task_status in (PENDING, RETRYING) 的任务

    - 按 created_at 顺序抢占并置 PROCESSING

    - 只发送 reply_content（不得根据 template_id 拼装文案）

    - 严格按 docs03 状态机与重试规则更新表



    已下线：报备休息 / 私聊离岗审批 / 审批 / QC（template_id 1000-1999、2000-2999）直接消队，不发送。

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

            template_id = int(task["template_id"])

            if is_disabled_notification_template(template_id):

                log.info(

                    "disabled_feature skip notification template_id=%s notification_id=%s related=%s:%s",

                    template_id,

                    task["id"],

                    task.get("related_event_name"),

                    task.get("related_event_id"),

                )

                with transaction() as cur:

                    notification_queue_repo.mark_done_sent(

                        cur,

                        task_id=int(task["id"]),

                        processed_at_utc=now,

                    )

                continue



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



