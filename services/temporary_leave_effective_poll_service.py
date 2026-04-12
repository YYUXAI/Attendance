from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from infra.db import transaction
from repositories import (
    effective_temporary_leaves_repo,
    temporary_leave_applications_repo,
    temporary_qc_exemption_list_repo,
)
from repositories.shifts_repo import get_by_id as get_shift_by_id
from services.approval_service import _temporary_leave_instant_as_utc_aware

log = logging.getLogger(__name__)


def run_poll_cycle(*, limit: int = 100) -> None:
    now_utc = datetime.now(timezone.utc)
    approved_past_end = temporary_leave_applications_repo.list_apps_approved_past_end(
        now_utc=now_utc,
        limit=limit,
    )
    ready_effective = temporary_leave_applications_repo.list_apps_ready_to_effective(
        now_utc=now_utc,
        limit=limit,
    )
    ready_complete = temporary_leave_applications_repo.list_apps_ready_to_complete(
        now_utc=now_utc,
        limit=limit,
    )

    log.info(
        "tleave_effective_poll_scan now_utc=%s ready_to_effective_count=%s ready_to_complete_count=%s "
        "ready_to_expire_approved_count=%s",
        now_utc.isoformat(),
        len(ready_effective),
        len(ready_complete),
        len(approved_past_end),
    )

    for app in approved_past_end:
        try:
            _process_approved_expired(application_id=app.id, now_utc=now_utc)
        except Exception as e:
            log.exception(
                "tleave_effective_poll_error phase=approved_expired application_id=%s exc_type=%s exc=%r",
                app.id,
                type(e).__name__,
                e,
            )

    for app in ready_effective:
        try:
            _process_promote_to_effective(application_id=app.id, now_utc=now_utc)
        except Exception as e:
            log.exception(
                "tleave_effective_poll_error phase=promote_effective application_id=%s exc_type=%s exc=%r",
                app.id,
                type(e).__name__,
                e,
            )

    for app in ready_complete:
        try:
            _process_promote_to_completed(application_id=app.id, now_utc=now_utc)
        except Exception as e:
            log.exception(
                "tleave_effective_poll_error phase=promote_completed application_id=%s exc_type=%s exc=%r",
                app.id,
                type(e).__name__,
                e,
            )


def _process_approved_expired(*, application_id: int, now_utc: datetime) -> None:
    with transaction() as cur:
        cur.execute(
            """
            SELECT id
            FROM public.temporary_leave_applications
            WHERE id = %s
            FOR UPDATE
            """,
            (application_id,),
        )
        if cur.fetchone() is None:
            return
        row = temporary_leave_applications_repo.get_by_id_cur(cur, application_id=application_id)
        if not row or row.status != "APPROVED":
            return
        start_u = _temporary_leave_instant_as_utc_aware(row.start_at)
        end_u = _temporary_leave_instant_as_utc_aware(row.end_at)
        if now_utc < end_u:
            return

        log.info(
            "tleave_expired_promote_begin application_id=%s employee_id=%s shift_id=%s start_at=%s end_at=%s",
            row.id,
            row.employee_id,
            int(row.shift_id),
            start_u.isoformat(),
            end_u.isoformat(),
        )
        n = temporary_leave_applications_repo.update_expired_from_approved_by_id(
            cur,
            application_id=row.id,
            completed_at_utc=now_utc,
        )
        if n != 1:
            raise RuntimeError("approved->expired update affected 0 rows")
        log.info("tleave_expired_promote_done application_id=%s", row.id)


def _process_promote_to_effective(*, application_id: int, now_utc: datetime) -> None:
    with transaction() as cur:
        cur.execute(
            """
            SELECT id
            FROM public.temporary_leave_applications
            WHERE id = %s
            FOR UPDATE
            """,
            (application_id,),
        )
        if cur.fetchone() is None:
            return
        row = temporary_leave_applications_repo.get_by_id_cur(cur, application_id=application_id)
        if not row or row.status != "APPROVED":
            return

        start_u = _temporary_leave_instant_as_utc_aware(row.start_at)
        end_u = _temporary_leave_instant_as_utc_aware(row.end_at)
        if not (start_u <= now_utc < end_u):
            log.info(
                "tleave_effective_promote_skip application_id=%s reason=outside_window "
                "start_at_utc=%s end_at_utc=%s",
                row.id,
                start_u.isoformat(),
                end_u.isoformat(),
            )
            return

        log.info(
            "tleave_effective_promote_begin application_id=%s employee_id=%s shift_id=%s start_at=%s end_at=%s",
            row.id,
            row.employee_id,
            int(row.shift_id),
            start_u.isoformat(),
            end_u.isoformat(),
        )

        shift = get_shift_by_id(int(row.shift_id))
        if not shift or not shift.timezone:
            raise RuntimeError(f"shift {row.shift_id} missing timezone")

        existing = effective_temporary_leaves_repo.get_by_application_id_cur(cur, application_id=row.id)
        exemption_upserted = False

        if existing:
            effective_id = int(existing.id)
            temporary_qc_exemption_list_repo.upsert_from_effective_row(
                cur,
                shift_id=int(existing.shift_id),
                employee_id=existing.employee_id,
                effective_date=existing.effective_date,
                exemption_start_at=existing.leave_start_at,
                exemption_end_at=existing.leave_end_at,
                source_effective_temporary_leave_id=effective_id,
                updated_at_utc=now_utc,
            )
            exemption_upserted = True
        else:
            reason_rm = (row.leave_reason or "").strip() or None
            eff_date = start_u.astimezone(ZoneInfo(str(shift.timezone))).date()
            effective_id = effective_temporary_leaves_repo.insert_effective_row(
                cur,
                employee_id=row.employee_id,
                effective_date=eff_date,
                shift_id=int(row.shift_id),
                reason_remark=reason_rm,
                leave_start_at=start_u,
                leave_end_at=end_u,
                application_id=row.id,
            )
            temporary_qc_exemption_list_repo.upsert_from_effective_row(
                cur,
                shift_id=int(row.shift_id),
                employee_id=row.employee_id,
                effective_date=eff_date,
                exemption_start_at=start_u,
                exemption_end_at=end_u,
                source_effective_temporary_leave_id=int(effective_id),
                updated_at_utc=now_utc,
            )
            exemption_upserted = True

        n = temporary_leave_applications_repo.update_effective_from_approved(cur, application_id=row.id)
        if n != 1:
            raise RuntimeError("APPROVED->EFFECTIVE update affected 0 rows")

        log.info(
            "tleave_effective_promote_done application_id=%s effective_id=%s exemption_upserted=%s",
            row.id,
            effective_id,
            exemption_upserted,
        )


def _process_promote_to_completed(*, application_id: int, now_utc: datetime) -> None:
    with transaction() as cur:
        cur.execute(
            """
            SELECT id
            FROM public.temporary_leave_applications
            WHERE id = %s
            FOR UPDATE
            """,
            (application_id,),
        )
        if cur.fetchone() is None:
            return
        row = temporary_leave_applications_repo.get_by_id_cur(cur, application_id=application_id)
        if not row or row.status != "EFFECTIVE":
            return
        end_u = _temporary_leave_instant_as_utc_aware(row.end_at)
        if now_utc < end_u:
            return

        log.info(
            "tleave_complete_promote_begin application_id=%s employee_id=%s shift_id=%s end_at=%s",
            row.id,
            row.employee_id,
            int(row.shift_id),
            end_u.isoformat(),
        )

        eff = effective_temporary_leaves_repo.get_by_application_id_cur(cur, application_id=row.id)
        deleted_rows = 0
        if eff:
            deleted_rows = temporary_qc_exemption_list_repo.delete_by_source_effective_temporary_leave_id(
                cur,
                source_effective_temporary_leave_id=int(eff.id),
            )

        n = temporary_leave_applications_repo.update_completed_from_effective_by_id(
            cur,
            application_id=row.id,
            completed_at_utc=now_utc,
        )
        if n != 1:
            raise RuntimeError("EFFECTIVE->COMPLETED update affected 0 rows")

        log.info(
            "tleave_complete_promote_done application_id=%s exemption_deleted=%s",
            row.id,
            deleted_rows > 0,
        )
