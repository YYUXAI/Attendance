from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from typing import Optional

from aiogram import Bot

from domain.checkin_image_extraction import CheckinImageExtraction
from domain.shared.result import ServiceResult
from infra.checkin_ai_config import CheckinAiConfig, load_checkin_ai_config
from repositories.registrations_repo import get_by_tg_id
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


async def download_telegram_file_bytes(*, bot: Bot, file_id: str) -> Optional[bytes]:
    try:
        tg_file = await bot.get_file(file_id)
        if not tg_file.file_path:
            return None
        buf = BytesIO()
        await bot.download_file(tg_file.file_path, destination=buf)
        data = buf.getvalue()
        return data if data else None
    except Exception:
        log.exception("checkin_ai: failed to download file_id=%s", file_id)
        return None


async def resolve_clock_time_with_ai(
    *,
    bot: Bot,
    file_id: str,
    tg_id: int,
    shift_timezone: str,
    config: Optional[CheckinAiConfig] = None,
    message_sent_utc: Optional[datetime] = None,
    caption: str | None = None,
) -> ServiceResult | CheckinAiResolveResult:
    image_bytes = await download_telegram_file_bytes(bot=bot, file_id=file_id)
    if not image_bytes:
        return ServiceResult(
            ok=False,
            message="打卡失败，无法下载截图，请重试",
            error_code="AI_DOWNLOAD_FAILED",
        )
    log.info(
        "checkin_ai: image downloaded file_id=%s sha256=%s bytes=%s",
        file_id,
        hashlib.sha256(image_bytes).hexdigest()[:16],
        len(image_bytes),
    )
    return await resolve_clock_time_with_ai_from_bytes(
        image_bytes=image_bytes,
        tg_id=tg_id,
        shift_timezone=shift_timezone,
        config=config,
        message_sent_utc=message_sent_utc,
        caption=caption,
    )


async def resolve_clock_time_with_ai_from_bytes(
    *,
    image_bytes: bytes,
    tg_id: int,
    shift_timezone: str,
    config: Optional[CheckinAiConfig] = None,
    message_sent_utc: Optional[datetime] = None,
    caption: str | None = None,
) -> ServiceResult | CheckinAiResolveResult:
    cfg = config or load_checkin_ai_config()
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

    reg = get_by_tg_id(tg_id)
    if not reg:
        return ServiceResult(ok=False, message="打卡失败，您尚未注册", error_code="NOT_REGISTERED")

    if not image_bytes:
        return ServiceResult(
            ok=False,
            message="打卡失败，图片为空",
            error_code="AI_DOWNLOAD_FAILED",
        )

    log.info(
        "checkin_ai: image bytes sha256=%s bytes=%s",
        hashlib.sha256(image_bytes).hexdigest()[:16],
        len(image_bytes),
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

    trust_sender = cfg.trust_sender_when_name_unreadable and not composite_screenshot
    if composite_screenshot and cfg.trust_sender_when_name_unreadable:
        log.info("checkin_ai: composite screenshot, trust_sender disabled for tg_id=%s", tg_id)

    validated = checkin_extraction_validate_service.validate_extraction_for_checkin(
        extraction=extraction,
        reg=reg,
        shift_timezone=shift_timezone,
        now_utc=ref_utc,
        max_skew_minutes=cfg.max_clock_skew_minutes,
        trust_sender_when_name_unreadable=trust_sender,
        composite_screenshot=composite_screenshot,
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
    log_checkin_recognition(
        stage="validated_ok",
        tg_id=tg_id,
        extraction=extraction,
        expected_username=reg.tg_username,
        expected_english_name=reg.english_name,
        employee_id=str(reg.employee_id),
        composite_screenshot=composite_screenshot,
        clock_time_utc=validated,
        shift_timezone=shift_timezone,
    )
    return CheckinAiResolveResult(
        clock_time_utc=validated,
        used_ai_time=True,
        verified_image_user=identity_verified,
        extraction=extraction,
    )
