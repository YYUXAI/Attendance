"""远程外包打卡（工号打卡群）：桌面工号文件夹 + Google 北京时间，不要求 TG 用户名。"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from datetime import datetime

from domain.checkin_image_extraction import CheckinImageExtraction
from domain.shared.result import ServiceResult
from infra.checkin_ai_config import CheckinAiConfig
from repositories.registrations_repo import RegistrationRow
from services import checkin_clock_time_service
from services.checkin_image_ai_service import CheckinAiExtractError
from services.checkin_user_message import (
    MSG_DATE_MISMATCH,
    MSG_EMPLOYEE_ID_MISMATCH,
    MSG_TIME_MISMATCH,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RemoteDiffExtraction:
    extraction: CheckinImageExtraction
    desktop_employee_id: str | None
    has_beijing_time: bool
    has_green_person_folder: bool


def _normalize_employee_id(raw: str | None) -> str | None:
    s = re.sub(r"\D", "", (raw or "").strip())
    return s if s else None


def _parse_remote_payload(data: dict) -> RemoteDiffExtraction | None:
    from services.checkin_image_ai_service import _parse_extraction_payload

    base = _parse_extraction_payload(data)
    desktop_id = _normalize_employee_id(
        str(data.get("desktop_employee_id") or data.get("employee_id") or "")
    )
    has_beijing = bool(data.get("has_beijing_time"))
    has_folder = bool(data.get("has_green_person_folder"))
    extraction = replace(
        base,
        display_name=None,
        username_hint=desktop_id,
    )
    return RemoteDiffExtraction(
        extraction=extraction,
        desktop_employee_id=desktop_id,
        has_beijing_time=has_beijing,
        has_green_person_folder=has_folder,
    )


async def extract_remote_checkin_from_zhipu(
    *,
    image_bytes: bytes,
    config: CheckinAiConfig,
    tg_id: int | None = None,
    reference_utc: object | None = None,
    shift_timezone: str = "Asia/Shanghai",
) -> tuple[RemoteDiffExtraction | None, CheckinAiExtractError | None]:
    from services.checkin_zhipu_vision_service import extract_remote_checkin_raw_from_zhipu_vision

    data, ai_err = await extract_remote_checkin_raw_from_zhipu_vision(
        image_bytes=image_bytes,
        config=config,
        tg_id=tg_id,
        reference_utc=reference_utc,
        shift_timezone=shift_timezone,
    )
    if ai_err is not None:
        return None, ai_err
    if data is None:
        return None, CheckinAiExtractError("AI_EXTRACT_FAILED", MSG_TIME_MISMATCH)
    remote = _parse_remote_payload(data)
    if remote is None:
        return None, CheckinAiExtractError("AI_EXTRACT_FAILED", MSG_TIME_MISMATCH)
    return remote, None


def validate_remote_extraction_for_checkin(
    *,
    remote: RemoteDiffExtraction,
    reg: RegistrationRow,
    shift_timezone: str,
    now_utc: datetime,
    max_skew_minutes: int,
) -> ServiceResult | datetime:
    extraction = remote.extraction
    expected_id = _normalize_employee_id(str(reg.employee_id))
    desktop_id = remote.desktop_employee_id

    if not remote.has_beijing_time or not extraction.clock_time:
        return ServiceResult(
            ok=False,
            message=MSG_TIME_MISMATCH,
            error_code="AI_TIME_NOT_FOUND",
        )

    if not desktop_id or not remote.has_green_person_folder:
        return ServiceResult(
            ok=False,
            message=MSG_EMPLOYEE_ID_MISMATCH,
            error_code="REMOTE_EMPLOYEE_ID_NOT_FOUND",
        )

    if not expected_id or desktop_id != expected_id:
        log.info(
            "checkin_remote: employee_id mismatch desktop=%r expected=%r",
            desktop_id,
            expected_id,
        )
        return ServiceResult(
            ok=False,
            message=MSG_EMPLOYEE_ID_MISMATCH,
            error_code="REMOTE_EMPLOYEE_ID_MISMATCH",
        )

    date_status = checkin_clock_time_service.evaluate_clock_date(
        extraction=extraction,
        shift_timezone=shift_timezone,
        now_utc=now_utc,
        require_date=True,
    )
    if date_status == "missing":
        return ServiceResult(
            ok=False,
            message=MSG_DATE_MISMATCH,
            error_code="AI_DATE_NOT_FOUND",
        )
    if date_status == "mismatch":
        return ServiceResult(
            ok=False,
            message=MSG_DATE_MISMATCH,
            error_code="AI_DATE_MISMATCH",
        )

    time_status, clock_utc = checkin_clock_time_service.evaluate_clock_time(
        extraction=extraction,
        shift_timezone=shift_timezone,
        now_utc=now_utc,
        max_skew_minutes=max_skew_minutes,
    )
    if time_status == "skew":
        return ServiceResult(
            ok=False,
            message=MSG_TIME_MISMATCH,
            error_code="AI_TIME_SCREENSHOT_SKEW",
        )
    if time_status in {"missing", "invalid_format"}:
        return ServiceResult(
            ok=False,
            message=MSG_TIME_MISMATCH,
            error_code="AI_TIME_NOT_FOUND",
        )

    assert clock_utc is not None
    return clock_utc
