"""全图 OCR 一次 + 文本 LLM 结构化提取（ocr_text_llm 后端）。"""

from __future__ import annotations

import logging
import time
from dataclasses import replace
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import httpx

from domain.checkin_image_extraction import CheckinImageExtraction
from infra.checkin_ai_config import CheckinAiConfig
from services.checkin_image_ai_service import (
    CheckinAiExtractError,
    _detect_clock_timezone_hint,
    _fallback_extraction_from_text,
    _is_ollama_base,
    _list_ollama_model_names,
    _merge_extractions,
    _model_installed,
    _ollama_payload_to_text,
    _ollama_root,
    _parse_model_content,
    _pick_clock_by_inclusion,
    _clock_candidates_from_text,
    normalize_ocr_dot_clocks,
)
from services.checkin_clock_time_service import normalize_ocr_date_text
from services.checkin_ocr_engine import ocr_backend_available, ocr_engine_name, ocr_full_image_text
from services.checkin_ocr_executor import run_ocr_cpu
from services.checkin_service import ALLOWED_TIMEZONES
from services.checkin_user_message import MSG_TIME_MISMATCH

log = logging.getLogger(__name__)

_OCR_TEXT_LLM_PROMPT = """You extract check-in fields from OCR text of a TIME.IS screenshot (may include Slack popup).

OCR text (may contain errors — ignore garbage lines):
---
{ocr_text}
---

Message sent at UTC: {reference_utc}
Message sent local ({tz_name}): {reference_local}
Expected calendar day at send time ({tz_name}): {expected_date}

Rules:
- clock_time: ONLY the large main TIME.IS clock, format HH:MM:SS. Ignore city times, GMT+8 misreads, bot reply lines.
- clock_date: TIME.IS date line under the big clock only. Output YYYY-MM-DD or null.
  * Read date as Chinese 「几月几日」: MUST be month (1-12) + day (1-31). Example: 6月4日 = June 4, NOT "648" or "48".
  * OCR often glues 日 onto day: 「6月4日」→「6月48」(day>31→4); 「6月1日」→「6月18」(day ends with 8→1 when matches Expected day).
  * Do NOT change a valid 「6月18日」 to June 1 unless OCR glue pattern and Expected calendar day confirm June 1.
  * 佛历 25xx年M月D日: Gregorian year = Buddhist_year - 543 (佛历2569年6月4日 → 2026-06-04).
  * 公历 20xx年M月D日 → YYYY-MM-DD only when that exact pattern appears.
  * Reject impossible day > 31; fix glued digits (48→4, 41→4) when clearly 几月几日 under TIME.IS clock.
  * If OCR date matches Expected calendar day ({expected_date}), use that YYYY-MM-DD.
  * Do NOT guess date from unrelated numbers (employee id, GMT+8, etc.).
- display_name / username_hint: Slack popup only (often Y_UX_ handle), not holidays or cities
- timezone_iana: e.g. Asia/Shanghai if hinted, else null
- Do NOT invent values

Return ONE JSON object, no markdown:
{{"display_name":null,"username_hint":null,"clock_time":null,"clock_date":null,"timezone_iana":null,"confidence":0.0}}
"""


async def _call_ollama_text(*, root: str, model: str, prompt: str, config: CheckinAiConfig) -> str:
    body = {
        "model": model,
        "stream": False,
        "prompt": prompt,
        "options": {
            "temperature": 0.1,
            "num_predict": 512,
        },
    }
    timeout = httpx.Timeout(config.timeout_seconds, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(f"{root}/api/generate", json=body)
        if resp.status_code == 404:
            raise httpx.HTTPStatusError("model not found", request=resp.request, response=resp)
        resp.raise_for_status()
        payload = resp.json()
    content = _ollama_payload_to_text(payload)
    if not content or not content.strip():
        raise ValueError("empty ollama text response")
    return content.strip()


async def _call_openai_text(
    *, base_url: str, model: str, prompt: str, config: CheckinAiConfig
) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    body = {
        "model": model,
        "temperature": 0.1,
        "messages": [{"role": "user", "content": prompt}],
    }
    timeout = httpx.Timeout(config.timeout_seconds, connect=30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        payload = resp.json()
    content = payload["choices"][0]["message"]["content"]
    if isinstance(content, list):
        text_parts = [
            p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"
        ]
        content = "\n".join(text_parts)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("empty openai text response")
    return content.strip()


async def _call_text_llm(*, prompt: str, config: CheckinAiConfig) -> str:
    model = config.text_model.strip()
    if _is_ollama_base(config.base_url):
        return await _call_ollama_text(
            root=_ollama_root(config.base_url), model=model, prompt=prompt, config=config
        )
    return await _call_openai_text(
        base_url=config.base_url, model=model, prompt=prompt, config=config
    )


def _clock_from_ocr_text(
    ocr_text: str,
    *,
    reference_utc: datetime,
    tz_name: str,
    max_skew_minutes: int,
) -> tuple[Optional[str], bool]:
    """从 OCR 全文用包含法选时钟；返回 (时间, 是否曾出现超窗候选)。"""
    effective_tz = _detect_clock_timezone_hint(ocr_text) or tz_name
    cands_list = _clock_candidates_from_text(ocr_text)
    cands = {c: hs for c, hs in cands_list}
    pick, skew_rejected = _pick_clock_by_inclusion(
        cands,
        reference_utc=reference_utc,
        tz_name=effective_tz,
        max_skew_minutes=max_skew_minutes,
    )
    return pick, skew_rejected


async def extract_checkin_from_ocr_text_llm(
    *,
    prepared_bytes: bytes,
    config: CheckinAiConfig,
    expected_tg_username: str | None = None,
    expected_english_name: str | None = None,
    reference_utc: datetime | None = None,
    shift_timezone: str = "Asia/Shanghai",
) -> tuple[Optional[CheckinImageExtraction], Optional[CheckinAiExtractError]]:
    if not ocr_backend_available():
        return None, CheckinAiExtractError(
            "AI_NAME_OCR_UNAVAILABLE",
            "打卡失败：OCR 不可用，请检查 EasyOCR/Tesseract 安装。",
        )

    ref_utc = reference_utc or datetime.now(timezone.utc)
    tz_name = shift_timezone if shift_timezone in ALLOWED_TIMEZONES else "Asia/Shanghai"
    ref_local = ref_utc.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d %H:%M:%S %Z")
    expected_date = ref_utc.astimezone(ZoneInfo(tz_name)).strftime("%Y-%m-%d")

    root = _ollama_root(config.base_url)
    text_model = config.text_model.strip()
    if _is_ollama_base(config.base_url):
        try:
            available = await _list_ollama_model_names(
                root=root, timeout=min(config.timeout_seconds, 15.0)
            )
        except Exception:
            log.exception("checkin_ocr_text_llm: cannot reach ollama at %s", root)
            return None, CheckinAiExtractError(
                "AI_SERVICE_DOWN",
                f"打卡失败，无法连接本地 AI（{root}）。\n请确认 Ollama 已启动。",
            )
        if not _model_installed(text_model, available):
            sample = ", ".join(sorted(available)[:6]) or "（无）"
            return None, CheckinAiExtractError(
                "AI_MODEL_NOT_FOUND",
                (
                    f"打卡失败，文本模型「{text_model}」未安装。\n"
                    f"请运行：ollama pull {text_model}\n"
                    f"当前已安装：{sample}"
                ),
            )

    t0 = time.perf_counter()
    ocr_text = await run_ocr_cpu(ocr_full_image_text, prepared_bytes)
    log.info(
        "checkin_ocr_text_llm: full ocr engine=%s chars=%s sec=%.1f",
        ocr_engine_name(),
        len(ocr_text or ""),
        time.perf_counter() - t0,
    )
    if not (ocr_text or "").strip():
        return None, CheckinAiExtractError("AI_TIME_NOT_FOUND", MSG_TIME_MISMATCH)

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

    prompt = _OCR_TEXT_LLM_PROMPT.format(
        ocr_text=ocr_text[:8000],
        reference_utc=ref_utc.isoformat(),
        reference_local=ref_local,
        tz_name=tz_name,
        expected_date=expected_date,
    )
    try:
        t1 = time.perf_counter()
        llm_raw = await _call_text_llm(prompt=prompt, config=config)
        log.info(
            "checkin_ocr_text_llm: llm model=%s sec=%.1f raw_len=%s",
            text_model,
            time.perf_counter() - t1,
            len(llm_raw),
        )
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            return None, CheckinAiExtractError(
                "AI_MODEL_NOT_FOUND",
                f"打卡失败，文本模型「{text_model}」不可用。请执行：ollama pull {text_model}",
            )
        return None, CheckinAiExtractError(
            "AI_HTTP_ERROR",
            f"打卡失败，AI 服务返回错误（HTTP {getattr(exc.response, 'status_code', 0)}）。",
        )
    except httpx.ConnectError:
        return None, CheckinAiExtractError(
            "AI_SERVICE_DOWN",
            "打卡失败，无法连接 Ollama。请打开 Ollama 应用或运行 ollama serve。",
        )
    except Exception:
        log.exception("checkin_ocr_text_llm: llm call failed model=%s", text_model)
        return None, CheckinAiExtractError(
            "AI_EXTRACT_FAILED",
            "打卡失败，AI 文本解析异常。请稍后重试。",
        )

    extraction = _parse_model_content(llm_raw, expected_username=expected_tg_username)
    fallback = _fallback_extraction_from_text(
        ocr_text,
        expected_username=expected_tg_username,
        reference_utc=ref_utc,
        tz_name=tz_name,
    )
    extraction = _merge_extractions(extraction, fallback)

    from services.checkin_clock_time_service import extract_clock_date_for_checkin

    ocr_date = extract_clock_date_for_checkin(
        ocr_text,
        expected_date=expected_date,
        llm_clock_date=extraction.clock_date,
    )
    if ocr_date:
        if extraction.clock_date != ocr_date:
            log.info(
                "checkin_ocr_text_llm: use clock_date %s (was llm %s)",
                ocr_date,
                extraction.clock_date,
            )
        extraction = replace(extraction, clock_date=ocr_date)
    elif extraction.clock_date and extraction.clock_date != expected_date:
        log.info(
            "checkin_ocr_text_llm: drop clock_date %s (not send day %s)",
            extraction.clock_date,
            expected_date,
        )
        extraction = replace(extraction, clock_date=None)

    if not extraction.clock_time and inclusion_pick:
        log.info("checkin_ocr_text_llm: use inclusion clock from ocr text value=%s", inclusion_pick)
        extraction = replace(extraction, clock_time=inclusion_pick)

    if skew_rejected and not extraction.clock_time:
        extraction = replace(extraction, clock_skew_rejected=True)

    log.info(
        "checkin_ocr_text_llm: parsed clock=%r name=%r date=%r skew_rejected=%s",
        extraction.clock_time,
        extraction.username_hint or extraction.display_name,
        extraction.clock_date,
        extraction.clock_skew_rejected,
    )
    return extraction, None
