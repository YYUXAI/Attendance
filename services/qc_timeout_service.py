from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from infra.db import transaction
from repositories import qc_results_repo, qc_task_queue_repo, registrations_repo

log = logging.getLogger(__name__)

LOG_QC_REGISTRATION_CONFIG_INCOMPLETE = "qc_registration_config_incomplete"


def _as_qc_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"qc_date unexpected type: {type(value)!r}")


def _instant_as_utc_aware(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"expected datetime, got {type(value)!r}")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _process_one_timeout(*, task_id: int, now_utc: datetime) -> None:
    with transaction() as cur:
        row = qc_task_queue_repo.lock_task_by_id_cur(cur, task_id=int(task_id))
        if not row:
            return
        if row.status == "PENDING" and row.first_private_notify_sent_at is None:
            created = _instant_as_utc_aware(row.created_at)
            if created + timedelta(minutes=15) > now_utc:
                return
        else:
            if row.first_private_notify_sent_at is None:
                return
            if row.status not in ("NOTIFIED", "WAITING_SUBMISSION", "SUBMITTED"):
                return
            sent = _instant_as_utc_aware(row.first_private_notify_sent_at)
            if sent + timedelta(minutes=15) > now_utc:
                return
        n = qc_task_queue_repo.mark_timeout_terminal_cur(cur, task_id=int(task_id))
        if n != 1:
            return
        reg = registrations_repo.get_by_employee_id_cur(cur, employee_id=str(row.employee_id))
        if reg is not None and reg.organization_id is not None:
            qc_results_repo.upsert_terminal_result_cur(
                cur,
                employee_id=str(row.employee_id),
                shift_id=int(row.shift_id),
                organization_id=int(reg.organization_id),
                qc_date=_as_qc_date(row.qc_date),
                qc_round=int(row.qc_round),
                result="TIMEOUT",
                attachment_id=None,
                at_utc=now_utc,
            )
        else:
            log.error(
                "%s phase=qc_timeout skip_qc_results missing=organization_binding employee_id=%s task_id=%s shift_id=%s qc_round=%s",
                LOG_QC_REGISTRATION_CONFIG_INCOMPLETE,
                row.employee_id,
                int(task_id),
                int(row.shift_id),
                int(row.qc_round),
            )


def run_timeout_cycle(*, limit: int = 100) -> None:
    now_utc = datetime.now(timezone.utc)
    ids = qc_task_queue_repo.list_task_ids_due_for_timeout(now_utc=now_utc, limit=limit)
    if not ids:
        return
    log.info("qc_timeout_scan now_utc=%s due_task_count=%s", now_utc.isoformat(), len(ids))
    for tid in ids:
        try:
            _process_one_timeout(task_id=int(tid), now_utc=now_utc)
        except Exception as e:
            log.exception(
                "qc_timeout_poll_error task_id=%s exc_type=%s exc=%r",
                int(tid),
                type(e).__name__,
                e,
            )
