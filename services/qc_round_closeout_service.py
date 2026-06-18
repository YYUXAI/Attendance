from __future__ import annotations

import html
import logging
from datetime import datetime, timezone

from aiogram import Bot

from infra.db import transaction
from infra.telegram_sender import send_notification
from keyboards.qc_closeout_inline import build_pass_attachment_view_keyboard
from repositories import event_logs_repo, qc_task_queue_repo, shifts_repo
from services import qc_notice_display

log = logging.getLogger(__name__)

# 与 docs02 / qc_task_queue_repo.list_employee_ids_with_open_tasks_cur 互补集合严格对齐
QC_TASK_TERMINAL_STATUSES: tuple[str, ...] = (
    "COMPLETED",
    "TIMEOUT",
    "FAILED",
    "CANCELLED",
    "SKIPPED",
)


def _display_label(*, english_name: str | None, employee_id: str) -> str:
    name = (english_name or "").strip()
    if name:
        return html.escape(name)
    return html.escape(str(employee_id))


def _plain_display_name(*, english_name: str | None, employee_id: str) -> str:
    n = (english_name or "").strip()
    return n if n else str(employee_id)


def _closeout_body_and_keyboard_items(
    *,
    shift: shifts_repo.ShiftRow,
    qc_round: int,
    rows: list[qc_task_queue_repo.QcRoundCloseoutDisplayRow],
) -> tuple[str, list[tuple[int, str]]]:
    dept = qc_notice_display.department_display_for_shift_id(shift_id=int(shift.id))
    shift_range = qc_notice_display.format_shift_time_range_hhmm(shift=shift)
    tz = html.escape(str(shift.timezone))
    rnd = html.escape(str(int(qc_round)))

    completed: list[qc_task_queue_repo.QcRoundCloseoutDisplayRow] = []
    incomplete: list[qc_task_queue_repo.QcRoundCloseoutDisplayRow] = []
    for r in rows:
        ok_pass = (
            (r.qc_result or "").strip() == "PASS"
            and (r.attachment_id or "").strip()
            and r.qc_result_id is not None
        )
        if ok_pass:
            completed.append(r)
        else:
            incomplete.append(r)

    lines: list[str] = [
        "质检完结公告",
        "",
        f"部门：{html.escape(dept)}",
        f"班次：{shift_range}",
        f"时区：{tz}",
        "",
        f"今日第{rnd}轮质检结果如下——",
        "",
        "以下人员完成质检：",
        "（点击人名可查看对应截图）",
    ]
    kb_items: list[tuple[int, str]] = []
    for r in completed:
        lines.append(_display_label(english_name=r.english_name, employee_id=r.employee_id))
        rid = r.qc_result_id
        if rid is not None:
            kb_items.append(
                (
                    int(rid),
                    _plain_display_name(english_name=r.english_name, employee_id=r.employee_id),
                )
            )

    lines.append("")
    lines.append("以下人员未完成质检：")
    for r in incomplete:
        lines.append(_display_label(english_name=r.english_name, employee_id=r.employee_id))

    return "\n".join(lines).rstrip() + "\n", kb_items


async def try_send_round_closeout_for_log(*, bot: Bot, log_id: int) -> None:
    now = datetime.now(timezone.utc)
    pending_rollback: int | None = None

    try:
        with transaction() as cur:
            claimed = event_logs_repo.claim_qc_round_closeout_processed_at_cur(
                cur,
                log_id=int(log_id),
                at_utc=now,
                terminal_statuses=QC_TASK_TERMINAL_STATUSES,
            )
            if not claimed:
                return
            meta = qc_task_queue_repo.get_shift_round_for_log_id_cur(cur, log_id=int(log_id))
            display_rows = qc_task_queue_repo.list_round_closeout_display_rows_cur(cur, log_id=int(log_id))

        pending_rollback = int(log_id)

        if not meta:
            with transaction() as cur:
                event_logs_repo.rollback_qc_round_closeout_processed_at_cur(
                    cur,
                    log_id=int(log_id),
                    error_message="round_closeout_missing_shift_round_after_claim",
                )
            pending_rollback = None
            log.error("qc_round_closeout rollback reason=no_meta log_id=%s", int(log_id))
            return

        shift_id, qc_date, qc_round = meta
        shift = shifts_repo.get_by_id(int(shift_id))
        gid = shift.attendance_group_id if shift is not None else None
        if shift is None or gid is None or int(gid) == 0:
            err = "round_closeout_missing_attendance_group_id"
            with transaction() as cur:
                event_logs_repo.rollback_qc_round_closeout_processed_at_cur(
                    cur,
                    log_id=int(log_id),
                    error_message=err,
                )
            pending_rollback = None
            log.error(
                "qc_round_closeout rollback reason=no_attendance_group log_id=%s shift_id=%s",
                int(log_id),
                int(shift_id),
            )
            return

        body, kb_items = _closeout_body_and_keyboard_items(
            shift=shift,
            qc_round=int(qc_round),
            rows=display_rows,
        )
        kb = build_pass_attachment_view_keyboard(items=kb_items)
        outcome = await send_notification(
            bot=bot,
            notify_tg_id=int(gid),
            reply_content=body,
            attachment_id=None,
            reply_markup=kb,
        )

        if outcome.delivery_result != "SENT":
            err = (outcome.error_message or outcome.delivery_result or "UNKNOWN")[:2000]
            with transaction() as cur:
                event_logs_repo.rollback_qc_round_closeout_processed_at_cur(
                    cur,
                    log_id=int(log_id),
                    error_message=err,
                )
            pending_rollback = None
            log.error(
                "qc_round_closeout rollback reason=send_failed log_id=%s delivery=%s err=%s",
                int(log_id),
                outcome.delivery_result,
                outcome.error_message,
            )
            return

        pending_rollback = None
        log.info("qc_round_closeout sent log_id=%s shift_id=%s", int(log_id), int(shift_id))
    except Exception as e:
        if pending_rollback is not None:
            try:
                with transaction() as cur:
                    event_logs_repo.rollback_qc_round_closeout_processed_at_cur(
                        cur,
                        log_id=int(pending_rollback),
                        error_message=f"round_closeout_unhandled:{type(e).__name__}:{e!s}"[:2000],
                    )
            except Exception:
                log.exception(
                    "qc_round_closeout rollback_failed log_id=%s",
                    int(pending_rollback),
                )
        log.exception(
            "qc_round_closeout try_send failed log_id=%s exc_type=%s",
            int(log_id),
            type(e).__name__,
        )


async def run_round_closeout_cycle(*, bot: Bot, limit: int = 20) -> None:
    candidates = qc_task_queue_repo.list_log_ids_eligible_for_round_closeout(
        terminal_statuses=QC_TASK_TERMINAL_STATUSES,
        limit=int(limit),
    )
    if not candidates:
        return
    for lid in candidates:
        await try_send_round_closeout_for_log(bot=bot, log_id=int(lid))
