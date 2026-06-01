from __future__ import annotations

from datetime import datetime

from domain.checkin_image_extraction import CheckinImageExtraction
from domain.shared.result import ServiceResult
from repositories.registrations_repo import RegistrationRow
from services import checkin_clock_time_service, checkin_identity_match_service
from services.checkin_image_ai_service import has_valid_identity_fields
from services.checkin_user_message import (
    MSG_DATE_MISMATCH,
    MSG_NAME_AND_TIME_MISMATCH,
    MSG_NAME_MISMATCH,
    MSG_SCREENSHOT_TIME_ABNORMAL,
    MSG_TIME_MISMATCH,
)


def validate_extraction_for_checkin(
    *,
    extraction: CheckinImageExtraction,
    reg: RegistrationRow,
    shift_timezone: str,
    now_utc: datetime,
    max_skew_minutes: int,
    trust_sender_when_name_unreadable: bool = False,
    composite_screenshot: bool = False,
) -> ServiceResult | datetime:
    """
    校验截图识别结果（姓名与时间均以图片 OCR/AI 结果为准，不因配文一致而跳过）。
    成功返回 clock_time_utc；失败返回明确区分「用户」或「时间」的 ServiceResult。
    """
    identity_ok = has_valid_identity_fields(extraction)

    identity_matched = False
    if identity_ok:
        identity_matched = checkin_identity_match_service.match_registration_for_sender(
            sender=reg,
            display_name=extraction.display_name,
            username_hint=extraction.username_hint,
        )

    if identity_matched:
        pass
    else:
        other_person = checkin_identity_match_service.detect_other_person_identity(
            sender=reg,
            display_name=extraction.display_name,
            username_hint=extraction.username_hint,
        )
        if other_person:
            return ServiceResult(
                ok=False,
                message=MSG_NAME_MISMATCH,
                error_code="AI_USER_OTHER_PERSON",
            )

    if not identity_ok:
        if trust_sender_when_name_unreadable:
            pass
        elif composite_screenshot and not extraction.clock_time:
            return ServiceResult(
                ok=False,
                message=MSG_NAME_AND_TIME_MISMATCH,
                error_code="AI_COMPOSITE_SCREENSHOT",
            )
        elif composite_screenshot:
            return ServiceResult(
                ok=False,
                message=MSG_NAME_MISMATCH,
                error_code="AI_COMPOSITE_SCREENSHOT",
            )
        elif not extraction.clock_time:
            return ServiceResult(
                ok=False,
                message=MSG_NAME_AND_TIME_MISMATCH,
                error_code="AI_BOTH_MISSING",
            )
        else:
            return ServiceResult(
                ok=False,
                message=MSG_NAME_MISMATCH,
                error_code="AI_USER_NOT_FOUND",
            )
    elif not identity_matched:
        return ServiceResult(
            ok=False,
            message=MSG_NAME_MISMATCH,
            error_code="AI_USER_MISMATCH",
        )

    if not extraction.clock_time:
        if extraction.clock_skew_rejected:
            return ServiceResult(
                ok=False,
                message=MSG_SCREENSHOT_TIME_ABNORMAL,
                error_code="AI_TIME_SCREENSHOT_SKEW",
            )
        return ServiceResult(
            ok=False,
            message=MSG_TIME_MISMATCH,
            error_code="AI_TIME_NOT_FOUND",
        )

    date_status = checkin_clock_time_service.evaluate_clock_date(
        extraction=extraction,
        shift_timezone=shift_timezone,
        now_utc=now_utc,
        require_date=composite_screenshot,
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
            message=MSG_SCREENSHOT_TIME_ABNORMAL,
            error_code="AI_TIME_SCREENSHOT_SKEW",
        )

    if time_status == "missing":
        return ServiceResult(
            ok=False,
            message=MSG_TIME_MISMATCH,
            error_code="AI_TIME_NOT_FOUND",
        )

    if time_status == "invalid_format":
        return ServiceResult(
            ok=False,
            message=MSG_TIME_MISMATCH,
            error_code="AI_TIME_INVALID_FORMAT",
        )

    assert clock_utc is not None
    return clock_utc
