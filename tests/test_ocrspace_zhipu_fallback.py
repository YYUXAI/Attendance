"""OCR.space 基建失败回退智谱：flash + Google 北京时间 prompt。"""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from infra.checkin_ai_config import CheckinAiConfig
from services.checkin_extraction_validate_service import validate_extraction_for_checkin
from services.checkin_image_ai_service import extract_checkin_from_image
from services.checkin_zhipu_vision_service import extract_checkin_from_zhipu_ocrspace_fallback


def _flash_config() -> CheckinAiConfig:
    return CheckinAiConfig(
        enabled=True,
        base_url="https://open.bigmodel.cn/api/paas/v4",
        api_key="test-key",
        model="glm-4v-flash",
        mode="required",
        max_clock_skew_minutes=30,
        timeout_seconds=30.0,
        trust_sender_when_name_unreadable=False,
        name_verify_mode="vision",
        extract_backend="zhipu",
        clock_fallback_send_time=False,
        text_model="glm-4v-flash",
    )


@pytest.mark.asyncio
async def test_ocrspace_fallback_resolves_pm_clock() -> None:
    ref = datetime(2026, 8, 29, 13, 19, 30, tzinfo=timezone.utc)
    raw = (
        '{"clock_time":"9:20","clock_period":"下午","clock_date":"08-29",'
        '"has_beijing_time":true,"confidence":0.9}'
    )

    with patch(
        "services.checkin_zhipu_vision_service._call_zhipu_vision",
        new_callable=AsyncMock,
        return_value=raw,
    ):
        ext, err = await extract_checkin_from_zhipu_ocrspace_fallback(
            image_bytes=b"fake-image-bytes",
            config=_flash_config(),
            reference_utc=ref,
            shift_timezone="Asia/Shanghai",
        )

    assert err is None
    assert ext is not None
    assert ext.clock_time == "21:20:00"
    assert ext.clock_date == "08-29"

    reg = SimpleNamespace(
        english_name="Subtoyok",
        employee_id="70620",
        telegram_user_id=6398009481,
        telegram_username="Y_YY_subtoyok",
    )
    out = validate_extraction_for_checkin(
        extraction=ext,
        reg=reg,
        shift_timezone="Asia/Shanghai",
        now_utc=ref,
        max_skew_minutes=30,
        skip_identity_verify=True,
        require_date=True,
    )
    assert isinstance(out, datetime)


@pytest.mark.asyncio
async def test_ocrspace_infra_fail_uses_flash_google_beijing_fallback() -> None:
    from services.checkin_image_ai_service import CheckinAiExtractError

    ref = datetime(2026, 8, 29, 13, 19, 30, tzinfo=timezone.utc)
    cfg = _flash_config()
    captured: dict[str, str] = {}

    async def fake_ocrspace(**kwargs: object) -> tuple[None, CheckinAiExtractError]:
        return None, CheckinAiExtractError("AI_CONFIG_MISSING", "missing key")

    async def fake_fallback(**kwargs: object) -> tuple[object, None]:
        config = kwargs["config"]
        captured["model"] = config.model
        from domain.checkin_image_extraction import CheckinImageExtraction

        return (
            CheckinImageExtraction(clock_time="21:20:00", clock_date="08-29"),
            None,
        )

    with (
        patch(
            "infra.checkin_ocrspace_config.is_ocrspace_extract_chat",
            return_value=True,
        ),
        patch(
            "services.checkin_ocrspace_service.extract_checkin_from_ocrspace",
            new_callable=AsyncMock,
            side_effect=fake_ocrspace,
        ),
        patch(
            "services.checkin_zhipu_vision_service.extract_checkin_from_zhipu_ocrspace_fallback",
            new_callable=AsyncMock,
            side_effect=fake_fallback,
        ),
    ):
        ext, err = await extract_checkin_from_image(
            image_bytes=b"x",
            config=cfg,
            reference_utc=ref,
            shift_timezone="Asia/Shanghai",
            chat_id=-1004373351741,
            chat_title="QDYYZ 打卡报备群",
            skip_name_verify=True,
        )

    assert err is None
    assert ext is not None
    assert ext.clock_time == "21:20:00"
    assert captured["model"] == "glm-4v-flash"
