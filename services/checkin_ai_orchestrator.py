from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from domain.checkin_image_extraction import CheckinImageExtraction
from domain.clock_matter import validate_caption_for_remote_diff, validate_caption_identity_for_sender
from domain.shared.result import ServiceResult
from infra.checkin_ai_config import (
    CheckinAiConfig,
    base_zhipu_config_for_quality_inspection,
    load_checkin_ai_config,
    resolve_checkin_ai_config_for_chat,
)
from repositories.registrations_repo import RegistrationRow, get_by_tg_id
from services import checkin_extraction_validate_service, checkin_identity_match_service, checkin_image_ai_service
from services.checkin_recognition_log import log_checkin_recognition
from services.checkin_user_message import user_message_for_checkin_error

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckinAiResolveResult:
    clock_time_utc: datetime
    used_ai_time: bool
    verified_image_user: bool
    extraction: Optional[CheckinImageExtraction]


async def resolve_clock_time_with_ai_from_bytes(
    *,
    image_bytes: bytes,
    tg_id: int,
    shift_timezone: str,
    config: Optional[CheckinAiConfig] = None,
    message_sent_utc: Optional[datetime] = None,
    caption: str | None = None,
    chat_id: int | None = None,
    chat_title: str | None = None,
    registration: RegistrationRow | None = None,
    quality_inspection: bool = False,
) -> ServiceResult | CheckinAiResolveResult:
    loaded = config or load_checkin_ai_config()
    if quality_inspection:
        cfg = base_zhipu_config_for_quality_inspection(loaded)
    else:
        cfg = resolve_checkin_ai_config_for_chat(
            loaded,
            chat_id=chat_id,
            chat_title=chat_title,
        )
    now_utc = datetime.now(timezone.utc)
    ref_utc = message_sent_utc or now_utc
    if ref_utc.tzinfo is None:
        ref_utc = ref_utc.replace(tzinfo=timezone.utc)

    if not cfg.enabled:
        return CheckinAiResolveResult(
            clock_time_utc=now_utc,
            used_ai_time=False,
            verified_image_user=False,
            extraction=None,
        )

    reg = registration or get_by_tg_id(tg_id)
    if not reg:
        return ServiceResult(ok=False, message="打卡失败，您尚未注册", error_code="NOT_REGISTERED")

    from infra.checkin_employee_id_only_config import requires_employee_id_only_checkin
    from infra.checkin_remote_diff_config import requires_remote_diff_checkin
    from infra.kqbbq_checkin_config import is_kqbbq_chat
    from infra.leave_return_keyboard_only_config import is_qdyyz_chat

    is_remote_group = requires_remote_diff_checkin(chat_id=chat_id, chat_title=chat_title)
    employee_id_only = requires_employee_id_only_checkin(
        chat_id=chat_id, chat_title=chat_title
    )
    # QDYYZ：不校验截图姓名，只校验北京时间的时刻与日期
    skip_name_verify = employee_id_only or is_qdyyz_chat(
        chat_id=chat_id, chat_title=chat_title
    )
    require_clock_date = is_qdyyz_chat(
        chat_id=chat_id, chat_title=chat_title
    ) or is_kqbbq_chat(chat_id=chat_id, chat_title=chat_title)
    if is_remote_group or employee_id_only:
        caption_err = validate_caption_for_remote_diff(
            caption=caption,
            employee_id=str(reg.employee_id),
        )
    else:
        caption_err = validate_caption_identity_for_sender(
            caption=caption,
            english_name=reg.english_name,
            employee_id=str(reg.employee_id),
        )
    if caption_err:
        return ServiceResult(
            ok=False,
            message=user_message_for_checkin_error(caption_err),
            error_code=caption_err,
        )

    if not image_bytes:
        return ServiceResult(
            ok=False,
            message="打卡失败，图片为空",
            error_code="AI_DOWNLOAD_FAILED",
        )

    from infra.checkin_pc_only_config import requires_pc_screenshot
    from services.checkin_mobile_client_service import is_mobile_client_screenshot
    from services.checkin_remote_diff_service import (
        extract_remote_checkin_from_zhipu,
        validate_remote_extraction_for_checkin,
    )

    if is_remote_group:
        log.info(
            "checkin_ai: remote_diff mode chat_id=%s title=%r tg_id=%s",
            chat_id,
            chat_title,
            tg_id,
        )
    elif employee_id_only:
        log.info(
            "checkin_ai: employee_id_only chat_id=%s title=%r tg_id=%s",
            chat_id,
            chat_title,
            tg_id,
        )
    elif skip_name_verify:
        log.info(
            "checkin_ai: time_date_only chat_id=%s title=%r tg_id=%s",
            chat_id,
            chat_title,
            tg_id,
        )
    elif requires_pc_screenshot(chat_id=chat_id, chat_title=chat_title):
        is_mobile, mobile_reason = await is_mobile_client_screenshot(
            image_bytes=image_bytes,
            config=cfg,
            chat_id=chat_id,
            chat_title=chat_title,
        )
        if is_mobile:
            log.info(
                "checkin_ai: mobile client rejected chat_id=%s tg_id=%s reason=%s",
                chat_id,
                tg_id,
                mobile_reason,
            )
            return ServiceResult(
                ok=False,
                message=user_message_for_checkin_error("AI_MOBILE_CLIENT"),
                error_code="AI_MOBILE_CLIENT",
            )

    log.info(
        "checkin_ai: image bytes sha256=%s bytes=%s",
        hashlib.sha256(image_bytes).hexdigest()[:16],
        len(image_bytes),
    )

    if is_remote_group:
        if not cfg.zhipu:
            return ServiceResult(
                ok=False,
                message=user_message_for_checkin_error("AI_CONFIG_MISSING"),
                error_code="AI_CONFIG_MISSING",
            )
        remote, ai_err = await extract_remote_checkin_from_zhipu(
            image_bytes=image_bytes,
            config=cfg,
            tg_id=tg_id,
            reference_utc=ref_utc,
            shift_timezone=shift_timezone,
        )
        extraction = remote.extraction if remote is not None else None
        composite_screenshot = False
        if ai_err is not None:
            log_checkin_recognition(
                stage="remote_extract_failed",
                tg_id=tg_id,
                extraction=extraction,
                expected_username=reg.tg_username,
                expected_english_name=reg.english_name,
                employee_id=str(reg.employee_id),
                composite_screenshot=composite_screenshot,
                error_code=ai_err.error_code,
                shift_timezone=shift_timezone,
            )
            return ServiceResult(
                ok=False,
                message=user_message_for_checkin_error(ai_err.error_code),
                error_code=ai_err.error_code,
            )
        if remote is None:
            return ServiceResult(
                ok=False,
                message=user_message_for_checkin_error("AI_EXTRACT_FAILED"),
                error_code="AI_EXTRACT_FAILED",
            )
        log_checkin_recognition(
            stage="remote_extracted",
            tg_id=tg_id,
            extraction=extraction,
            expected_username=reg.tg_username,
            expected_english_name=reg.english_name,
            employee_id=str(reg.employee_id),
            composite_screenshot=composite_screenshot,
            shift_timezone=shift_timezone,
        )
        validated = validate_remote_extraction_for_checkin(
            remote=remote,
            reg=reg,
            shift_timezone=shift_timezone,
            now_utc=ref_utc,
            max_skew_minutes=cfg.max_clock_skew_minutes,
        )
        if isinstance(validated, ServiceResult):
            log_checkin_recognition(
                stage="remote_validate_failed",
                tg_id=tg_id,
                extraction=extraction,
                expected_username=reg.tg_username,
                expected_english_name=reg.english_name,
                employee_id=str(reg.employee_id),
                composite_screenshot=composite_screenshot,
                error_code=validated.error_code,
                shift_timezone=shift_timezone,
            )
            return validated
        record_utc = ref_utc if ref_utc.tzinfo else ref_utc.replace(tzinfo=timezone.utc)
        log_checkin_recognition(
            stage="remote_validated_ok",
            tg_id=tg_id,
            extraction=extraction,
            expected_username=reg.tg_username,
            expected_english_name=reg.english_name,
            employee_id=str(reg.employee_id),
            composite_screenshot=composite_screenshot,
            clock_time_utc=record_utc,
            shift_timezone=shift_timezone,
        )
        return CheckinAiResolveResult(
            clock_time_utc=record_utc,
            used_ai_time=True,
            verified_image_user=True,
            extraction=extraction,
        )

    prepared_probe = checkin_image_ai_service._prepare_image_bytes(image_bytes)
    composite_screenshot = checkin_image_ai_service.is_composite_checkin_image(
        raw_bytes=image_bytes,
        prepared_bytes=prepared_probe,
    )

    extraction, ai_err = await checkin_image_ai_service.extract_checkin_from_image(
        image_bytes=image_bytes,
        config=cfg,
        expected_tg_username=reg.tg_username,
        expected_english_name=reg.english_name,
        reference_utc=ref_utc,
        shift_timezone=shift_timezone,
        tg_id=tg_id,
        skip_name_verify=skip_name_verify,
        chat_id=chat_id,
        chat_title=chat_title,
        quality_inspection=quality_inspection,
    )
    if ai_err is not None:
        log_checkin_recognition(
            stage="extract_failed",
            tg_id=tg_id,
            extraction=extraction,
            expected_username=reg.tg_username,
            expected_english_name=reg.english_name,
            employee_id=str(reg.employee_id),
            composite_screenshot=composite_screenshot,
            error_code=ai_err.error_code,
            shift_timezone=shift_timezone,
        )
        return ServiceResult(
            ok=False,
            message=user_message_for_checkin_error(ai_err.error_code),
            error_code=ai_err.error_code,
        )
    if extraction is None:
        log_checkin_recognition(
            stage="extract_empty",
            tg_id=tg_id,
            expected_username=reg.tg_username,
            expected_english_name=reg.english_name,
            employee_id=str(reg.employee_id),
            composite_screenshot=composite_screenshot,
            error_code="AI_EXTRACT_FAILED",
            shift_timezone=shift_timezone,
        )
        return ServiceResult(
            ok=False,
            message=user_message_for_checkin_error("AI_EXTRACT_FAILED"),
            error_code="AI_EXTRACT_FAILED",
        )

    log_checkin_recognition(
        stage="extracted",
        tg_id=tg_id,
        extraction=extraction,
        expected_username=reg.tg_username,
        expected_english_name=reg.english_name,
        employee_id=str(reg.employee_id),
        composite_screenshot=composite_screenshot,
        shift_timezone=shift_timezone,
    )

    trust_sender = (
        cfg.trust_sender_when_name_unreadable or skip_name_verify
    ) and not composite_screenshot
    if composite_screenshot and (cfg.trust_sender_when_name_unreadable or skip_name_verify):
        log.info("checkin_ai: composite screenshot, trust_sender disabled for tg_id=%s", tg_id)

    validated = checkin_extraction_validate_service.validate_extraction_for_checkin(
        extraction=extraction,
        reg=reg,
        shift_timezone=shift_timezone,
        now_utc=ref_utc,
        max_skew_minutes=cfg.max_clock_skew_minutes,
        trust_sender_when_name_unreadable=trust_sender,
        composite_screenshot=composite_screenshot,
        skip_identity_verify=skip_name_verify,
        require_date=require_clock_date or composite_screenshot,
    )
    if isinstance(validated, ServiceResult):
        log_checkin_recognition(
            stage="validate_failed",
            tg_id=tg_id,
            extraction=extraction,
            expected_username=reg.tg_username,
            expected_english_name=reg.english_name,
            employee_id=str(reg.employee_id),
            composite_screenshot=composite_screenshot,
            error_code=validated.error_code,
            shift_timezone=shift_timezone,
        )
        return validated

    identity_verified = (
        checkin_image_ai_service.has_valid_identity_fields(extraction)
        and checkin_identity_match_service.match_registration_for_sender(
            sender=reg,
            display_name=extraction.display_name,
            username_hint=extraction.username_hint,
        )
    )
    # 截图时间仅用于姓名/日期/偏差校验；入库打卡时刻 = 发消息时间
    record_utc = ref_utc if ref_utc.tzinfo else ref_utc.replace(tzinfo=timezone.utc)
    log_checkin_recognition(
        stage="validated_ok",
        tg_id=tg_id,
        extraction=extraction,
        expected_username=reg.tg_username,
        expected_english_name=reg.english_name,
        employee_id=str(reg.employee_id),
        composite_screenshot=composite_screenshot,
        clock_time_utc=record_utc,
        shift_timezone=shift_timezone,
    )
    return CheckinAiResolveResult(
        clock_time_utc=record_utc,
        used_ai_time=True,
        verified_image_user=identity_verified,
        extraction=extraction,
    )
