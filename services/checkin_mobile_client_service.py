"""识别打卡截图是否为手机端 Telegram 客户端（仅 PC 校验群启用）。

考勤机器人测试群等：OCR 或智谱识别「设置头像」「更改头像」判为手机端。
"""
from __future__ import annotations

import asyncio
import logging

from infra.checkin_ai_config import CheckinAiConfig
from infra.checkin_pc_only_config import requires_pc_screenshot

log = logging.getLogger(__name__)

_MOBILE_AVATAR_MARKERS = (
    "设置头像",
    "更改头像",
)


def _ocr_text(image_bytes: bytes) -> str:
    try:
        from services.checkin_ocr_engine import ocr_backend_available, ocr_full_image_text

        if not ocr_backend_available():
            return ""
        return ocr_full_image_text(image_bytes) or ""
    except Exception:
        log.warning("checkin_mobile: ocr skipped", exc_info=True)
        return ""


def _has_mobile_avatar_menu(ocr_text: str) -> bool:
    raw = ocr_text or ""
    return any(m in raw for m in _MOBILE_AVATAR_MARKERS)


async def is_mobile_client_screenshot(
    *,
    image_bytes: bytes,
    config: CheckinAiConfig | None = None,
    chat_id: int | None = None,
    chat_title: str | None = None,
) -> tuple[bool, str]:
    """
    判断是否手机端截图。
    仅在声明 pc-only-screenshot capability 的群内校验；
    识别到「设置头像」或「更改头像」时返回 (True, reason)。
    """
    if not image_bytes:
        return False, ""
    if not requires_pc_screenshot(chat_id=chat_id, chat_title=chat_title):
        return False, ""

    ocr_text = await asyncio.to_thread(_ocr_text, image_bytes)
    if _has_mobile_avatar_menu(ocr_text):
        log.info("checkin_mobile: ocr hit avatar menu chat_id=%s", chat_id)
        return True, "mobile_telegram_avatar_menu_ocr"

    cfg = config
    if cfg is None:
        from infra.checkin_ai_config import load_checkin_ai_config

        cfg = load_checkin_ai_config()

    if cfg.zhipu and (cfg.api_key or "").strip():
        try:
            from services.checkin_zhipu_vision_service import detect_avatar_menu_via_zhipu

            if await detect_avatar_menu_via_zhipu(image_bytes=image_bytes, config=cfg):
                log.info("checkin_mobile: zhipu hit avatar menu chat_id=%s", chat_id)
                return True, "mobile_telegram_avatar_menu_zhipu"
        except Exception:
            log.warning("checkin_mobile: zhipu avatar menu detect failed", exc_info=True)

    return False, ""
