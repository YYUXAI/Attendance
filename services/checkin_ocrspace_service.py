"""ocrspase 实验：OCR.space 全图 + 分块补漏，再用身份规则匹配姓名（仅实验群）。"""
from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

from domain.checkin_image_extraction import CheckinImageExtraction
from infra.checkin_ai_config import CheckinAiConfig
from infra.checkin_ocrspace_config import (
    next_ocrspace_api_key,
    ocrspace_api_key_count,
    ocrspace_api_keys,
    ocrspace_api_url,
    ocrspace_engine,
    ocrspace_language,
)
from services.checkin_clock_time_service import (
    extract_clock_date_for_checkin,
    normalize_ocr_date_text,
)
from services.checkin_image_ai_service import (
    CheckinAiExtractError,
    _clock_candidates_from_text,
    _fallback_extraction_from_text,
    _prepare_image_bytes,
    normalize_ocr_dot_clocks,
)
from services.checkin_ocr_text_llm_service import _clock_from_ocr_text
from services.checkin_service import ALLOWED_TIMEZONES
from services.checkin_user_message import MSG_TIME_MISMATCH
from services.checkin_identity_match_service import _identity_matches_blob

log = logging.getLogger(__name__)

# 基础设施类失败：可回退智谱（内容识别失败不回退）
_OCRSPACE_INFRA_ERROR_CODES = frozenset(
    {
        "AI_HTTP_ERROR",
        "AI_TIMEOUT",
        "AI_OCRSPACE_OVERLOAD",
        "AI_CONFIG_MISSING",
    }
)


def is_ocrspace_infra_failure(err: CheckinAiExtractError | None) -> bool:
    """429 / 超时 / E101 过载 / 连不上等，视为 OCR.space 不可用。"""
    if err is None:
        return False
    if err.error_code in _OCRSPACE_INFRA_ERROR_CODES:
        return True
    if err.error_code == "AI_EXTRACT_FAILED":
        blob = f"{err.message or ''}".upper()
        if any(x in blob for x in ("E101", "TIMEOUT", "429", "过于频繁", "OVERLOAD")):
            return True
    return False



_UI_NAME_BLACKLIST = frozenset(
    {
        "group",
        "select",
        "settings",
        "contacts",
        "profile",
        "channel",
        "china",
        "beijing",
        "telegram",
        "wallet",
        "calls",
        "saved",
        "messages",
        "status",
        "emoji",
        "night",
        "mode",
        "guru",
        "welcome",
        "hire",
        "expert",
        "time",
        "image",
        "null",
        "the",
        "new",
        "chat",
        "start",
        "messaging",
    }
)


def _normalize_ocr_colon_lookalikes(text: str) -> str:
    """TIME.IS 大方块冒号常被 OCR.space 认成 ÷/➗，先归一成冒号再抽时钟。"""
    if not text:
        return text
    return text.replace("÷", ":").replace("➗", ":")


def _norm_alnum(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())


def _contains_norm(haystack: str, needle: str, *, min_len: int = 3) -> bool:
    """与正式身份匹配一致：含 OCR i/l 不区分（Nigelito ↔ Nlgelito）。"""
    return _identity_matches_blob(
        needle=needle,
        blob_alnum=_norm_alnum(haystack),
        min_len=min_len,
    )


def _pil_to_jpeg_bytes(img, *, quality: int = 90) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _iter_tile_jpeg_bytes(
    prepared_bytes: bytes,
    *,
    grid: int = 2,
    overlap: float = 0.15,
    upscale: float = 1.6,
) -> list[bytes]:
    """把图切成 grid×grid 重叠块；小块再放大，减轻小字漏读。"""
    from PIL import Image

    img = Image.open(io.BytesIO(prepared_bytes)).convert("RGB")
    w, h = img.size
    if w < 80 or h < 80:
        return []
    tiles: list[bytes] = []
    for gy in range(grid):
        for gx in range(grid):
            x0 = int(gx * w / grid)
            y0 = int(gy * h / grid)
            x1 = int((gx + 1) * w / grid)
            y1 = int((gy + 1) * h / grid)
            ox = int((x1 - x0) * overlap)
            oy = int((y1 - y0) * overlap)
            left = max(0, x0 - ox)
            top = max(0, y0 - oy)
            right = min(w, x1 + ox)
            bottom = min(h, y1 + oy)
            crop = img.crop((left, top, right, bottom))
            cw, ch = crop.size
            if upscale > 1.0 and max(cw, ch) < 900:
                crop = crop.resize(
                    (max(1, int(cw * upscale)), max(1, int(ch * upscale))),
                    Image.Resampling.LANCZOS,
                )
            tiles.append(_pil_to_jpeg_bytes(crop))
    return tiles


async def _ocrspace_parse_image_text(
    *,
    prepared_bytes: bytes,
    timeout_seconds: float,
    client: httpx.AsyncClient | None = None,
    label: str = "full",
) -> tuple[str | None, CheckinAiExtractError | None]:
    keys = ocrspace_api_keys()
    if not keys:
        return None, CheckinAiExtractError(
            "AI_CONFIG_MISSING",
            "打卡失败：未配置 OCRSPACE_API_KEY / OCRSPACE_API_KEYS。",
        )
    api_key = next_ocrspace_api_key()
    b64 = base64.standard_b64encode(prepared_bytes).decode("ascii")
    payload = {
        "base64Image": f"data:image/jpeg;base64,{b64}",
        "language": ocrspace_language(),
        "isOverlayRequired": "false",
        "OCREngine": ocrspace_engine(),
        "scale": "true",
        "detectOrientation": "true",
    }
    headers = {"apikey": api_key}
    url = ocrspace_api_url()
    t0 = time.perf_counter()
    owns_client = client is None
    data = None
    last_status = 0
    try:
        if owns_client:
            client = httpx.AsyncClient(timeout=timeout_seconds)
        assert client is not None
        for attempt in range(1, 8):
            headers = {"apikey": api_key}
            resp = await client.post(url, data=payload, headers=headers)
            last_status = resp.status_code
            if resp.status_code == 429:
                api_key = next_ocrspace_api_key()
                wait = min(20.0, 2.0 * attempt)
                log.warning(
                    "ocrspace: 429 rate-limit label=%s attempt=%s switch_key sleep=%.1fs keys=%s",
                    label,
                    attempt,
                    wait,
                    ocrspace_api_key_count(),
                )
                await asyncio.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            break
        else:
            return None, CheckinAiExtractError(
                "AI_HTTP_ERROR",
                "打卡失败：OCR.space 请求过于频繁（HTTP 429），请稍后重试。",
            )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else last_status
        log.exception("ocrspace: http %s label=%s", status, label)
        return None, CheckinAiExtractError(
            "AI_HTTP_ERROR",
            f"打卡失败：OCR.space 返回 HTTP {status}。",
        )
    except httpx.TimeoutException:
        log.exception("ocrspace: timeout label=%s limit=%ss", label, timeout_seconds)
        return None, CheckinAiExtractError(
            "AI_TIMEOUT",
            f"打卡失败：OCR.space 超时（{int(timeout_seconds)} 秒）。",
        )
    except Exception:
        log.exception("ocrspace: request failed label=%s", label)
        return None, CheckinAiExtractError(
            "AI_EXTRACT_FAILED",
            "打卡失败：OCR.space 调用异常，请稍后重试。",
        )
    finally:
        if owns_client and client is not None:
            await client.aclose()

    if data is None:
        return None, CheckinAiExtractError(
            "AI_HTTP_ERROR",
            f"打卡失败：OCR.space 返回 HTTP {last_status or 429}。",
        )
    exit_code = data.get("OCRExitCode")
    errored = bool(data.get("IsErroredOnProcessing"))
    err_msg = data.get("ErrorMessage") or data.get("ErrorDetails") or ""
    if isinstance(err_msg, list):
        err_msg = "; ".join(str(x) for x in err_msg if x)
    parsed = data.get("ParsedResults") or []
    texts: list[str] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        t = (item.get("ParsedText") or "").strip()
        if t:
            texts.append(t)
    joined = "\n".join(texts).strip()
    log.info(
        "ocrspace: done label=%s exit=%s errored=%s chars=%s sec=%.1f err=%r preview=%r",
        label,
        exit_code,
        errored,
        len(joined),
        time.perf_counter() - t0,
        (err_msg or "")[:160],
        joined[:200],
    )
    if errored and not joined:
        blob = f"{err_msg or ''}".upper()
        code = (
            "AI_OCRSPACE_OVERLOAD"
            if ("E101" in blob or "TIMEOUT" in blob or "OVERLOAD" in blob)
            else "AI_EXTRACT_FAILED"
        )
        return None, CheckinAiExtractError(
            code,
            f"打卡失败：OCR.space 处理失败。{err_msg or ''}".strip(),
        )
    return joined or None, None


def _identity_hit_in_text(
    ocr_text: str,
    *,
    expected_english_name: str | None,
    expected_tg_username: str | None,
) -> tuple[str, str] | None:
    """全文（去符号）包含注册英文名/句柄则命中。"""
    ename = (expected_english_name or "").strip()
    uname = (expected_tg_username or "").strip().lstrip("@")
    if ename and _contains_norm(ocr_text, ename, min_len=3):
        return ename, ename
    if uname and _contains_norm(ocr_text, uname, min_len=4):
        return uname, uname
    # 句柄主体：Y_UX_Foo -> Foo
    m = re.match(r"^(Y_(?:UX|TC)_)(.+)$", uname, flags=re.IGNORECASE) if uname else None
    if m:
        core = m.group(2).strip()
        if core and _contains_norm(ocr_text, core, min_len=3):
            return f"{m.group(1)}{core}", uname
    return None


def _apply_identity_rules(
    extraction: CheckinImageExtraction,
    *,
    ocr_text: str,
    expected_english_name: str | None,
    expected_tg_username: str | None,
) -> CheckinImageExtraction:
    hit = _identity_hit_in_text(
        ocr_text,
        expected_english_name=expected_english_name,
        expected_tg_username=expected_tg_username,
    )
    if hit is not None:
        display, hint = hit
        log.info(
            "ocrspace: identity hit display=%r hint=%r en=%r user=%r",
            display,
            hint,
            expected_english_name,
            expected_tg_username,
        )
        return replace(extraction, display_name=display, username_hint=hint)

    # 回退字段若是 UI 词，清掉，避免 Group/Select 误匹配
    disp = (extraction.display_name or "").strip()
    hint = (extraction.username_hint or "").strip()
    if _norm_alnum(disp) in _UI_NAME_BLACKLIST or _norm_alnum(hint) in _UI_NAME_BLACKLIST:
        log.info("ocrspace: drop blacklisted identity disp=%r hint=%r", disp, hint)
        extraction = replace(extraction, display_name=None, username_hint=None)
    return extraction


def _needs_tile_ocr(
    ocr_text: str,
    extraction: CheckinImageExtraction,
    *,
    expected_english_name: str | None,
    expected_tg_username: str | None,
) -> bool:
    if _identity_hit_in_text(
        ocr_text,
        expected_english_name=expected_english_name,
        expected_tg_username=expected_tg_username,
    ):
        return False
    # 已有可用身份且不像 UI 词，可不再分块
    disp = (extraction.display_name or "").strip()
    hint = (extraction.username_hint or "").strip()
    if disp or hint:
        if _norm_alnum(disp) not in _UI_NAME_BLACKLIST and _norm_alnum(hint) not in _UI_NAME_BLACKLIST:
            # 仍可能是错名；若对不上注册名则继续分块补漏
            if expected_english_name and _contains_norm(disp + " " + hint, expected_english_name):
                return False
            if expected_tg_username and _contains_norm(disp + " " + hint, expected_tg_username):
                return False
    return True


async def extract_checkin_from_ocrspace(
    *,
    image_bytes: bytes,
    config: CheckinAiConfig,
    expected_tg_username: str | None = None,
    expected_english_name: str | None = None,
    reference_utc: datetime | None = None,
    shift_timezone: str = "Asia/Shanghai",
) -> tuple[Optional[CheckinImageExtraction], Optional[CheckinAiExtractError]]:
    if not image_bytes:
        return None, CheckinAiExtractError("AI_EMPTY_IMAGE", "打卡失败，图片为空")

    prepared = _prepare_image_bytes(image_bytes)
    timeout = max(float(config.timeout_seconds), 60.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        ocr_text, api_err = await _ocrspace_parse_image_text(
            prepared_bytes=prepared,
            timeout_seconds=timeout,
            client=client,
            label="full",
        )
        if api_err is not None and not ocr_text:
            return None, api_err
        ocr_text = ocr_text or ""

        # 先按全图做一轮抽取，决定要不要分块补姓名
        ref_utc = reference_utc or datetime.now(timezone.utc)
        if ref_utc.tzinfo is None:
            ref_utc = ref_utc.replace(tzinfo=timezone.utc)
        tz_name = shift_timezone if shift_timezone in ALLOWED_TIMEZONES else "Asia/Shanghai"
        expected_date = ref_utc.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d")

        probe_text = normalize_ocr_date_text(
            normalize_ocr_dot_clocks(_normalize_ocr_colon_lookalikes(ocr_text)),
            expected_date=expected_date,
        )
        probe_ext = _fallback_extraction_from_text(
            probe_text,
            expected_username=expected_tg_username,
            reference_utc=ref_utc,
            tz_name=tz_name,
        )
        probe_ext = _apply_identity_rules(
            probe_ext,
            ocr_text=probe_text,
            expected_english_name=expected_english_name,
            expected_tg_username=expected_tg_username,
        )

        if _needs_tile_ocr(
            probe_text,
            probe_ext,
            expected_english_name=expected_english_name,
            expected_tg_username=expected_tg_username,
        ):
            tile_parts: list[str] = []
            for idx, tile in enumerate(_iter_tile_jpeg_bytes(prepared)):
                tile_text, tile_err = await _ocrspace_parse_image_text(
                    prepared_bytes=tile,
                    timeout_seconds=timeout,
                    client=client,
                    label=f"tile{idx}",
                )
                if tile_text:
                    tile_parts.append(tile_text)
                elif tile_err is not None:
                    log.info(
                        "ocrspace: tile%d skipped err=%s",
                        idx,
                        tile_err.error_code,
                    )
            if tile_parts:
                ocr_text = "\n".join([ocr_text, *tile_parts]).strip()
                log.info(
                    "ocrspace: merged tiles parts=%s total_chars=%s",
                    len(tile_parts),
                    len(ocr_text),
                )

    if not (ocr_text or "").strip():
        return None, CheckinAiExtractError("AI_TIME_NOT_FOUND", MSG_TIME_MISMATCH)

    ocr_text = _normalize_ocr_colon_lookalikes(ocr_text)

    ref_utc = reference_utc or datetime.now(timezone.utc)
    if ref_utc.tzinfo is None:
        ref_utc = ref_utc.replace(tzinfo=timezone.utc)
    tz_name = shift_timezone if shift_timezone in ALLOWED_TIMEZONES else "Asia/Shanghai"
    expected_date = ref_utc.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d")

    ocr_text = normalize_ocr_date_text(
        normalize_ocr_dot_clocks(ocr_text),
        expected_date=expected_date,
    )

    inclusion_pick, skew_rejected = _clock_from_ocr_text(
        ocr_text,
        reference_utc=ref_utc,
        tz_name=tz_name,
        max_skew_minutes=config.max_clock_skew_minutes,
    )

    extraction = _fallback_extraction_from_text(
        ocr_text,
        expected_username=expected_tg_username,
        reference_utc=ref_utc,
        tz_name=tz_name,
    )
    extraction = _apply_identity_rules(
        extraction,
        ocr_text=ocr_text,
        expected_english_name=expected_english_name,
        expected_tg_username=expected_tg_username,
    )

    ocr_date = extract_clock_date_for_checkin(
        ocr_text,
        expected_date=expected_date,
        llm_clock_date=extraction.clock_date,
    )
    if ocr_date and extraction.clock_date != ocr_date:
        log.info("ocrspace: use clock_date %s (was %s)", ocr_date, extraction.clock_date)
        extraction = replace(extraction, clock_date=ocr_date)

    if not extraction.clock_time and inclusion_pick:
        log.info("ocrspace: use inclusion clock %s", inclusion_pick)
        extraction = replace(extraction, clock_time=inclusion_pick)

    if skew_rejected and not extraction.clock_time:
        extraction = replace(extraction, clock_skew_rejected=True)

    if extraction.clock_time:
        cands = {c for c, _ in _clock_candidates_from_text(ocr_text)}
        if cands and extraction.clock_time not in cands and inclusion_pick:
            extraction = replace(extraction, clock_time=inclusion_pick)

    # 保留合并后 OCR 原文（含分块），供实验群回复对照
    extraction = replace(extraction, ocr_debug_text=(ocr_text or "")[:12000] or None)

    log.info(
        "ocrspace: parsed clock=%r name=%r date=%r skew_rejected=%s",
        extraction.clock_time,
        extraction.username_hint or extraction.display_name,
        extraction.clock_date,
        extraction.clock_skew_rejected,
    )
    if not extraction.clock_time and not (
        extraction.display_name or extraction.username_hint
    ):
        return None, CheckinAiExtractError(
            "AI_PARSE_FAILED",
            (
                "打卡失败：OCR.space 未能识别姓名与时间。\n"
                "请截含 TIME.IS 大钟 + Slack 浮窗的清晰图后重试。"
            ),
        )
    return extraction, None
