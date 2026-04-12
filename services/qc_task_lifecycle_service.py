from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Optional, Tuple

from infra.db import transaction
from repositories import qc_results_repo, qc_task_queue_repo, registrations_repo

log = logging.getLogger(__name__)

LOG_QC_REGISTRATION_CONFIG_INCOMPLETE = "qc_registration_config_incomplete"
MSG_QC_BLOCKED_CONTACT_ADMIN = "暂无法完成该操作，请联系管理员协助处理。"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _as_qc_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise TypeError(f"qc_date unexpected type: {type(value)!r}")


def _verify_actor(*, employee_id: str, tg_user_id: int) -> Tuple[bool, str, Optional[registrations_repo.RegistrationRow]]:
    reg = registrations_repo.get_by_employee_id(str(employee_id))
    if not reg or reg.tg_id is None or int(reg.tg_id) != int(tg_user_id):
        return False, "无权操作该质检任务。", None
    return True, "", reg


def handle_first_confirm(*, task_id: int, tg_user_id: int) -> Tuple[bool, str]:
    with transaction() as cur:
        row = qc_task_queue_repo.lock_task_by_id_cur(cur, task_id=int(task_id))
        if not row:
            return False, "任务不存在或已失效。"
        ok, msg, _reg = _verify_actor(employee_id=row.employee_id, tg_user_id=tg_user_id)
        if not ok:
            return False, msg
        if row.status != "NOTIFIED":
            return False, "当前状态不允许此操作。"
        n = qc_task_queue_repo.update_notified_to_waiting_submission_cur(cur, task_id=int(task_id))
        if n != 1:
            return False, "状态已变更，请稍后再试。"
    return True, ""


def handle_first_cancel(*, task_id: int, tg_user_id: int) -> Tuple[bool, str]:
    now = _now_utc()
    with transaction() as cur:
        row = qc_task_queue_repo.lock_task_by_id_cur(cur, task_id=int(task_id))
        if not row:
            return False, "任务不存在或已失效。"
        ok, msg, reg = _verify_actor(employee_id=row.employee_id, tg_user_id=tg_user_id)
        if not ok:
            return False, msg
        if reg is None or reg.organization_id is None:
            log.warning(
                "%s phase=qc_first_cancel missing=organization_binding employee_id=%s task_id=%s",
                LOG_QC_REGISTRATION_CONFIG_INCOMPLETE,
                row.employee_id,
                int(task_id),
            )
            return False, MSG_QC_BLOCKED_CONTACT_ADMIN
        if row.status != "NOTIFIED":
            return False, "当前状态不允许此操作。"
        n = qc_task_queue_repo.update_notified_first_cancel_cur(cur, task_id=int(task_id))
        if n != 1:
            return False, "状态已变更，请稍后再试。"
        qc_results_repo.upsert_terminal_result_cur(
            cur,
            employee_id=str(row.employee_id),
            shift_id=int(row.shift_id),
            organization_id=int(reg.organization_id),
            qc_date=_as_qc_date(row.qc_date),
            qc_round=int(row.qc_round),
            result="FAIL",
            attachment_id=None,
            at_utc=now,
        )
    return True, ""


@dataclass(frozen=True)
class QcUploadOutcome:
    ok: bool
    message: str = ""
    echo_file_id: Optional[str] = None
    task_id: Optional[int] = None


def handle_attachment_upload_for_tg_user(*, tg_user_id: int, file_id: str) -> QcUploadOutcome:
    reg = registrations_repo.get_by_tg_id(int(tg_user_id))
    if not reg or not reg.employee_id:
        return QcUploadOutcome(ok=False, message="未找到注册信息。")
    cnt = qc_task_queue_repo.count_active_upload_tasks_for_employee(employee_id=str(reg.employee_id))
    if cnt > 1:
        log.warning(
            "qc_upload_task_ambiguous employee_id=%s active_upload_task_count=%s",
            reg.employee_id,
            cnt,
        )
    tid = qc_task_queue_repo.find_latest_active_upload_task_id_for_employee(employee_id=str(reg.employee_id))
    if tid is None:
        return QcUploadOutcome(ok=False, message="当前没有待上传的质检任务。")
    return handle_attachment_upload(task_id=int(tid), tg_user_id=int(tg_user_id), file_id=file_id)


def handle_attachment_upload(*, task_id: int, tg_user_id: int, file_id: str) -> QcUploadOutcome:
    fid = str(file_id).strip()
    if not fid:
        return QcUploadOutcome(ok=False, message="未获取到有效文件，请重试。")
    with transaction() as cur:
        row = qc_task_queue_repo.lock_task_by_id_cur(cur, task_id=int(task_id))
        if not row:
            return QcUploadOutcome(ok=False, message="任务不存在或已失效。")
        ok, msg, _reg = _verify_actor(employee_id=row.employee_id, tg_user_id=tg_user_id)
        if not ok:
            return QcUploadOutcome(ok=False, message=msg)
        if row.status not in ("WAITING_SUBMISSION", "SUBMITTED"):
            return QcUploadOutcome(ok=False, message="当前状态不允许上传材料。")
        n = qc_task_queue_repo.update_upload_submitted_cur(cur, task_id=int(task_id), file_id=fid)
        if n != 1:
            return QcUploadOutcome(ok=False, message="状态已变更，请稍后再试。")
    return QcUploadOutcome(ok=True, message="", echo_file_id=fid, task_id=int(task_id))


def handle_second_cancel(*, task_id: int, tg_user_id: int) -> Tuple[bool, str]:
    with transaction() as cur:
        row = qc_task_queue_repo.lock_task_by_id_cur(cur, task_id=int(task_id))
        if not row:
            return False, "任务不存在或已失效。"
        ok, msg, _reg = _verify_actor(employee_id=row.employee_id, tg_user_id=tg_user_id)
        if not ok:
            return False, msg
        if row.status != "SUBMITTED":
            return False, "当前状态不允许此操作。"
        n = qc_task_queue_repo.update_second_cancel_cur(cur, task_id=int(task_id))
        if n != 1:
            return False, "状态已变更，请稍后再试。"
    return True, ""


def handle_second_confirm(*, task_id: int, tg_user_id: int) -> Tuple[bool, str]:
    now = _now_utc()
    with transaction() as cur:
        row = qc_task_queue_repo.lock_task_by_id_cur(cur, task_id=int(task_id))
        if not row:
            return False, "任务不存在或已失效。"
        ok, msg, reg = _verify_actor(employee_id=row.employee_id, tg_user_id=tg_user_id)
        if not ok:
            return False, msg
        if reg is None or reg.organization_id is None:
            log.warning(
                "%s phase=qc_second_confirm missing=organization_binding employee_id=%s task_id=%s",
                LOG_QC_REGISTRATION_CONFIG_INCOMPLETE,
                row.employee_id,
                int(task_id),
            )
            return False, MSG_QC_BLOCKED_CONTACT_ADMIN
        if row.status != "SUBMITTED":
            return False, "当前状态不允许此操作。"
        pending = (row.pending_confirm_file_id or "").strip()
        if not pending:
            return False, "尚未收到可确认的材料，请先上传。"
        n = qc_task_queue_repo.update_second_confirm_completed_cur(cur, task_id=int(task_id))
        if n != 1:
            return False, "状态已变更，请稍后再试。"
        qc_results_repo.upsert_terminal_result_cur(
            cur,
            employee_id=str(row.employee_id),
            shift_id=int(row.shift_id),
            organization_id=int(reg.organization_id),
            qc_date=_as_qc_date(row.qc_date),
            qc_round=int(row.qc_round),
            result="PASS",
            attachment_id=pending,
            at_utc=now,
        )
    return True, ""
