"""Z.ai（智谱国际版）GLM 视觉模型识别打卡截图（全图一次，无 OCR）。"""
from __future__ import annotations

import base64
import json
import logging
import re
import time
from dataclasses import replace
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

from domain.checkin_image_extraction import CheckinImageExtraction
from infra.checkin_ai_config import CheckinAiConfig
from repositories.registrations_repo import list_registered_usernames
from services.checkin_clock_time_service import (
    clock_time_grounded_in_raw,
    extract_clock_date_from_text,
)
from services.checkin_image_ai_service import (
    CheckinAiExtractError,
    _parse_extraction_payload,
    _prepare_image_bytes,
    _strip_json_payload,
    has_valid_identity_fields,
)
from services.checkin_recognition_log import log_checkin_ai_text
from services.checkin_user_message import MSG_DATE_MISMATCH, MSG_NAME_MISMATCH, MSG_TIME_MISMATCH

log = logging.getLogger(__name__)

ZHIPU_DEFAULT_BASE_URL = "https://api.z.ai/api/paas/v4"
ZHIPU_DEFAULT_MODEL = "glm-4.6v"

_ZHIPU_EXTRACT_PROMPT = """你是考勤截图 OCR。只抄写图片里肉眼可见的文字，禁止推断、补全、猜测。

图片可能包含：
1. TIME.IS 中央大钟（完整 HH:MM:SS）
2. TIME.IS 日期行（如 2026年6月14日）
3. 右下角 Slack/IM 资料浮窗（头像旁的显示名）

输出一个 JSON 对象，不要 markdown，不要解释。

字段（看不到必须写 null，不要用发图时间或常识补全）：
- display_name: 浮窗显示名（string 或 null）
- username_hint: 浮窗登录名/名片段，不含 @（string 或 null）
- clock_time: 中央大钟，必须与图上显示完全一致（string 或 null）
- clock_date: 仅当图上有日期时，转为 YYYY-MM-DD（string 或 null）
- timezone_iana: 仅当图上有明确时区文字时填写（string 或 null）
- confidence: 0 到 1

硬性规则：
- 忽略 Telegram 聊天、Bot 回复、配文、@zpxinbot、工号、英文名、事项
- 只有大钟的一部分数字、或看不清秒/分 → clock_time 填 null
- 图上看不到 Slack 浮窗姓名 → display_name 与 username_hint 都填 null
- 图上看不到日期行 → clock_date 填 null
- 禁止编造任何字段

候选用户名（来自已注册数据库，优先在这些名字里识别）：
__CANDIDATE_USERNAMES__
"""

_ZHIPU_EXTRACT_KEYWORD_PROMPT = """你是考勤截图关键字段 OCR。只抄写图片可见文字，禁止猜测。

本轮只关注 3 个关键字段（按优先级）：
1) identity_text：Slack/IM 头像旁用户名（如 Y_UX_xxx）
2) clock_time：TIME.IS 主时钟（HH:MM:SS 或 HH:MM）
3) clock_date：TIME.IS 日期行（如 2026年6月16日）

输出 JSON（不要 markdown）：
- display_name: string|null
- username_hint: string|null
- clock_time: string|null
- clock_date: YYYY-MM-DD|null
- timezone_iana: string|null
- confidence: 0~1
- identity_text: 原样抄写的姓名证据（string|null）
- time_text: 原样抄写的时间证据（string|null）
- date_text: 原样抄写的日期证据（string|null）

硬性规则：
- 仅依据图片；忽略 Telegram 配文、@zpxinbot、工号、事项
- 读不清就填 null，不得补全
- identity_text / time_text / date_text 必须是图片里可见原文

候选用户名（来自已注册数据库，优先在这些名字里识别）：
__CANDIDATE_USERNAMES__
"""

_VISIBLE_DATE_IN_RAW_RE = re.compile(r"20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日")
_VISIBLE_BUDDHIST_DATE_IN_RAW_RE = re.compile(r"25\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日")
_ISO_DATE_IN_RAW_RE = re.compile(r"\b20\d{2}-\d{1,2}-\d{1,2}\b")
_USERNAME_CACHE_TTL_SECONDS = 120
_USERNAME_CACHE: tuple[float, list[str]] = (0.0, [])


def _norm_ground(s: str) -> str:
    return re.sub(r"[^a-z0-9:_\-]", "", (s or "").strip().lower())


def _field_literal_in_raw(value: str, raw: str) -> bool:
    """字段值须在模型原文中出现，防止凭空补全。"""
    if not value or not raw:
        return False
    v = value.strip()
    if v in raw:
        return True
    vn = _norm_ground(v)
    rn = _norm_ground(raw)
    return bool(vn) and vn in rn


def _parse_zhipu_json_only(raw: str) -> CheckinImageExtraction | None:
    payload = _strip_json_payload(raw)
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        # 容错：模型常输出末尾多余逗号，先做一次轻量修复再解析
        repaired = re.sub(r",\s*([}\]])", r"\1", payload)
        try:
            parsed = json.loads(repaired)
        except json.JSONDecodeError:
            return None
    if not isinstance(parsed, dict):
        return None
    return _parse_extraction_payload(parsed)


def _norm_user_token(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").strip().lower())


def _best_registered_username_match(*, text: str, candidates: list[str]) -> str | None:
    blob = _norm_user_token(text)
    if not blob:
        return None
    best: tuple[float, str] | None = None
    for cand in candidates:
        c = _norm_user_token(cand)
        if len(c) < 4:
            continue
        if c in blob or blob in c:
            return cand
        sim = SequenceMatcher(None, c, blob).ratio()
        if best is None or sim > best[0]:
            best = (sim, cand)
    if best and best[0] >= 0.80:
        return best[1]
    return None


def _identity_text_from_raw(raw: str) -> str | None:
    payload = _strip_json_payload(raw)
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        repaired = re.sub(r",\s*([}\]])", r"\1", payload)
        try:
            parsed = json.loads(repaired)
        except json.JSONDecodeError:
            return None
    if not isinstance(parsed, dict):
        return None
    val = parsed.get("identity_text")
    if not isinstance(val, str):
        return None
    s = val.strip()
    return s if s else None


def _promote_identity_text_from_raw(
    extraction: CheckinImageExtraction,
    *,
    raw: str,
) -> CheckinImageExtraction:
    """keyword retry 常把姓名写在 identity_text，提升到 display_name / username_hint。"""
    if has_valid_identity_fields(extraction):
        return extraction
    identity = _identity_text_from_raw(raw)
    if not identity or not _field_literal_in_raw(identity, raw):
        return extraction
    log.info("checkin_zhipu: promoted identity_text=%r", identity)
    return replace(
        extraction,
        display_name=extraction.display_name or identity,
        username_hint=extraction.username_hint or identity,
    )


def _inject_registered_username_hint(
    extraction: CheckinImageExtraction,
    *,
    raw: str,
    expected_tg_username: str | None,
    candidates: list[str],
) -> CheckinImageExtraction:
    """当模型未稳定填姓名字段时，用候选用户名做包含/相似回填。"""
    pool = list(candidates)
    if expected_tg_username:
        exp = expected_tg_username.strip().lstrip("@").lower()
        if exp and exp not in pool:
            pool.insert(0, exp)
    identity = _identity_text_from_raw(raw) or ""
    source_text = " ".join(
        [
            raw or "",
            identity,
            extraction.display_name or "",
            extraction.username_hint or "",
        ]
    )
    hit = _best_registered_username_match(text=source_text, candidates=pool)
    if not hit:
        return extraction
    if extraction.username_hint and _norm_user_token(extraction.username_hint) == _norm_user_token(hit):
        return extraction
    log.info("checkin_zhipu: username candidate matched=%s", hit)
    return replace(
        extraction,
        username_hint=extraction.username_hint or hit,
        display_name=extraction.display_name or hit,
    )


def _load_registered_usernames_cached(*, expected_tg_username: str | None) -> list[str]:
    now = time.time()
    ts, data = _USERNAME_CACHE
    if now - ts > _USERNAME_CACHE_TTL_SECONDS or not data:
        try:
            data = list_registered_usernames(limit=500)
        except Exception:
            log.warning("checkin_zhipu: load registered usernames failed", exc_info=True)
            data = []
        globals()["_USERNAME_CACHE"] = (now, data)
    out = list(data)
    if expected_tg_username:
        exp = expected_tg_username.strip().lstrip("@").lower()
        if exp and exp not in out:
            out.insert(0, exp)
    return out


def _build_prompt_with_candidates(template: str, candidates: list[str]) -> str:
    if not candidates:
        return template.replace("__CANDIDATE_USERNAMES__", "（空）")
    sample = ", ".join(candidates[:200])
    return template.replace("__CANDIDATE_USERNAMES__", sample)


def _need_keyword_retry(extraction: CheckinImageExtraction) -> bool:
    """关键字段缺失时触发第二轮关键字读取。"""
    if not extraction.clock_time:
        return True
    if not has_valid_identity_fields(extraction):
        return True
    if not extraction.clock_date:
        return True
    return False


def _expected_date_for_parse(*, reference_utc: object | None, shift_timezone: str) -> str:
    tz_name = shift_timezone if shift_timezone else "Asia/Shanghai"
    try:
        tz = ZoneInfo(tz_name)
    except Exception:
        tz = ZoneInfo("Asia/Shanghai")
    if isinstance(reference_utc, datetime):
        ref = reference_utc if reference_utc.tzinfo else reference_utc.replace(tzinfo=timezone.utc)
    else:
        ref = datetime.now(timezone.utc)
    return ref.astimezone(tz).date().isoformat()


def _patch_missing_clock_date(
    *,
    extraction: CheckinImageExtraction,
    raw: str,
    expected_date: str,
) -> CheckinImageExtraction:
    if extraction.clock_date:
        return extraction
    parsed = extract_clock_date_from_text(raw, expected_date=expected_date)
    if not parsed:
        return extraction
    return replace(extraction, clock_date=parsed)


def _clock_time_suspect_padding(clock_time: str, raw: str) -> bool:
    """拒绝把不完整时钟补成 HH:00:00。"""
    ct = clock_time.strip()
    m = re.match(r"(\d{1,2}):00:00$", ct)
    if not m:
        return False
    hour = m.group(1)
    hour_pat = hour.lstrip("0") or "0"
    if re.search(rf"{re.escape(hour_pat)}\s*:\s*(?!00)\d{{2}}", raw):
        return False
    if re.search(rf"{re.escape(hour_pat)}\s*:\s*\d{{2}}\s*:\s*(?!00)\d{{2}}", raw):
        return False
    return True


def _validate_image_only_extraction(
    extraction: CheckinImageExtraction,
    *,
    raw: str,
) -> CheckinAiExtractError | None:
    """仅接受模型原文中能对应上的识别结果。"""
    if not extraction.clock_time:
        return CheckinAiExtractError("AI_TIME_NOT_FOUND", MSG_TIME_MISMATCH)
    if _clock_time_suspect_padding(extraction.clock_time, raw):
        return CheckinAiExtractError("AI_NOT_GROUNDED", MSG_TIME_MISMATCH)
    if not clock_time_grounded_in_raw(extraction.clock_time, raw):
        return CheckinAiExtractError("AI_NOT_GROUNDED", MSG_TIME_MISMATCH)

    if not has_valid_identity_fields(extraction):
        return CheckinAiExtractError("AI_NAME_NOT_FOUND", MSG_NAME_MISMATCH)

    for val in (extraction.display_name, extraction.username_hint):
        if val and not _field_literal_in_raw(val, raw):
            return CheckinAiExtractError("AI_NOT_GROUNDED", MSG_NAME_MISMATCH)

    if not extraction.clock_date:
        return CheckinAiExtractError("AI_DATE_NOT_FOUND", MSG_DATE_MISMATCH)
    has_visible_date = bool(
        _VISIBLE_DATE_IN_RAW_RE.search(raw)
        or _VISIBLE_BUDDHIST_DATE_IN_RAW_RE.search(raw)
        or _ISO_DATE_IN_RAW_RE.search(raw)
    )
    parsed_from_raw = extract_clock_date_from_text(raw, expected_date=extraction.clock_date)
    if not has_visible_date or not parsed_from_raw:
        return CheckinAiExtractError("AI_DATE_NOT_FOUND", MSG_DATE_MISMATCH)
    if parsed_from_raw != extraction.clock_date:
        return CheckinAiExtractError("AI_NOT_GROUNDED", MSG_TIME_MISMATCH)

    if extraction.timezone_iana and not _field_literal_in_raw(extraction.timezone_iana, raw):
        return CheckinAiExtractError("AI_NOT_GROUNDED", MSG_TIME_MISMATCH)

    return None


async def _call_zhipu_vision(
    *,
    base_url: str,
    model: str,
    api_key: str,
    image_b64: str,
    prompt: str,
    timeout_seconds: float,
) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Accept-Language": "en-US,en",
    }
    body: dict[str, Any] = {
        "model": model,
        "temperature": 0,
        "max_tokens": 512,
        # API 侧强制要求返回 JSON，避免模型输出自然语言/markdown。
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                    },
                ],
            }
        ],
    }
    # 关闭思考链，避免污染 JSON OCR 结果（4.5V / 4.6V 均支持 thinking 开关）
    if any(tag in model.lower() for tag in ("4.5", "4.6")):
        body["thinking"] = {"type": "disabled"}
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        payload = resp.json()
    msg = payload["choices"][0]["message"]
    content = msg.get("content") or ""
    # 勿把 reasoning_content（思考过程）当 OCR 结果解析。
    if not str(content).strip() and "4.6" not in model.lower():
        content = msg.get("reasoning_content") or ""
    if isinstance(content, list):
        text_parts = [
            p.get("text", "")
            for p in content
            if isinstance(p, dict) and p.get("type") == "text"
        ]
        content = "\n".join(text_parts)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("empty zhipu response")
    return content


async def extract_checkin_from_zhipu_vision(
    *,
    image_bytes: bytes,
    config: CheckinAiConfig,
    expected_tg_username: str | None = None,
    expected_english_name: str | None = None,
    reference_utc: object | None = None,
    shift_timezone: str = "Asia/Shanghai",
    tg_id: int | None = None,
) -> tuple[Optional[CheckinImageExtraction], Optional[CheckinAiExtractError]]:
    del expected_english_name

    if not image_bytes:
        return None, CheckinAiExtractError("AI_EMPTY_IMAGE", "打卡失败，图片为空")
    if not (config.api_key or "").strip():
        return None, CheckinAiExtractError(
            "AI_CONFIG_MISSING",
            "打卡失败：未配置 Z.ai API Key（CHECKIN_AI_API_KEY）。",
        )

    prepared = _prepare_image_bytes(image_bytes)
    image_b64 = base64.standard_b64encode(prepared).decode("ascii")

    base_url = (config.base_url or ZHIPU_DEFAULT_BASE_URL).rstrip("/")
    model = (config.model or ZHIPU_DEFAULT_MODEL).strip()
    candidates = _load_registered_usernames_cached(expected_tg_username=expected_tg_username)
    prompt = _build_prompt_with_candidates(_ZHIPU_EXTRACT_PROMPT, candidates)

    log.info("checkin_zhipu: extract start model=%s size_kb=%s strict=image_only", model, len(prepared) // 1024)
    t0 = time.perf_counter()
    try:
        raw = await _call_zhipu_vision(
            base_url=base_url,
            model=model,
            api_key=config.api_key.strip(),
            image_b64=image_b64,
            prompt=prompt,
            timeout_seconds=config.timeout_seconds,
        )
        log.info(
            "checkin_zhipu: vision ok model=%s sec=%.1f raw_len=%s",
            model,
            time.perf_counter() - t0,
            len(raw),
        )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        err_body = ""
        try:
            if exc.response is not None:
                err_body = exc.response.text or ""
        except Exception:
            pass
        log.exception("checkin_zhipu: http %s model=%s body=%s", status, model, err_body[:200])
        if status in {401, 403}:
            return None, CheckinAiExtractError(
                "AI_AUTH_FAILED",
                "打卡失败：Z.ai API Key 无效或已过期，请检查 CHECKIN_AI_API_KEY。",
            )
        if "Insufficient balance" in err_body or '"code":"1113"' in err_body:
            return None, CheckinAiExtractError(
                "AI_BALANCE_EXHAUSTED",
                "打卡失败：Z.ai 账户余额不足，请充值后重试。",
            )
        if status == 429:
            return None, CheckinAiExtractError(
                "AI_RATE_LIMIT",
                "打卡失败：Z.ai API 调用频率超限，请稍后重试。",
            )
        return None, CheckinAiExtractError(
            "AI_HTTP_ERROR",
            f"打卡失败，Z.ai API 返回错误（HTTP {status}）。",
        )
    except httpx.TimeoutException:
        log.exception("checkin_zhipu: timeout model=%s", model)
        return None, CheckinAiExtractError(
            "AI_TIMEOUT",
            f"打卡失败，Z.ai 识别超时（{int(config.timeout_seconds)} 秒）。请稍后重试。",
        )
    except httpx.ConnectError:
        log.exception("checkin_zhipu: connect failed")
        return None, CheckinAiExtractError(
            "AI_SERVICE_DOWN",
            "打卡失败：无法连接 Z.ai API，请检查网络。",
        )
    except Exception:
        log.exception("checkin_zhipu: vision failed model=%s", model)
        return None, CheckinAiExtractError(
            "AI_EXTRACT_FAILED",
            "打卡失败，Z.ai 识别异常。请换一张更清晰的截图重试。",
        )

    extraction = _parse_zhipu_json_only(raw)
    if extraction is None:
        log.warning("checkin_zhipu: invalid json raw=%s", raw[:500])
        log_checkin_ai_text(phase="pass1_invalid_json", tg_id=tg_id, raw=raw)
        return None, CheckinAiExtractError(
            # 用户侧只保留：姓名/时间/日期不一致三类失败提示
            "AI_NAME_NOT_FOUND",
            MSG_NAME_MISMATCH,
        )
    log_checkin_ai_text(phase="pass1", tg_id=tg_id, raw=raw, extraction=extraction)

    # 关键字段缺失时，再做一次“关键字优先”识别，提升姓名/日期读全概率
    if _need_keyword_retry(extraction):
        try:
            raw_retry = await _call_zhipu_vision(
                base_url=base_url,
                model=model,
                api_key=config.api_key.strip(),
                image_b64=image_b64,
                prompt=_build_prompt_with_candidates(_ZHIPU_EXTRACT_KEYWORD_PROMPT, candidates),
                timeout_seconds=config.timeout_seconds,
            )
            extraction_retry = _parse_zhipu_json_only(raw_retry)
            if extraction_retry is not None:
                log_checkin_ai_text(
                    phase="pass2_keyword",
                    tg_id=tg_id,
                    raw=raw_retry,
                    extraction=extraction_retry,
                )
                log.info(
                    "checkin_zhipu: keyword retry promoted name=%r date=%r time=%r",
                    extraction_retry.display_name or extraction_retry.username_hint,
                    extraction_retry.clock_date,
                    extraction_retry.clock_time,
                )
                extraction = extraction_retry
                raw = raw_retry
        except Exception:
            log.warning("checkin_zhipu: keyword retry failed", exc_info=True)

    # 二次保障：模型未输出 clock_date 时，从原文里提取佛历/公历日期
    expected_date = _expected_date_for_parse(reference_utc=reference_utc, shift_timezone=shift_timezone)
    extraction = _patch_missing_clock_date(extraction=extraction, raw=raw, expected_date=expected_date)
    extraction = _promote_identity_text_from_raw(extraction, raw=raw)
    extraction = _inject_registered_username_hint(
        extraction,
        raw=raw,
        expected_tg_username=expected_tg_username,
        candidates=candidates,
    )

    ground_err = _validate_image_only_extraction(extraction, raw=raw)
    log_checkin_ai_text(phase="final", tg_id=tg_id, raw=raw, extraction=extraction)
    if ground_err is not None:
        log.warning(
            "checkin_zhipu: rejected not_grounded clock=%r name=%r date=%r",
            extraction.clock_time,
            extraction.display_name or extraction.username_hint,
            extraction.clock_date,
        )
        return extraction, ground_err

    log.info(
        "checkin_zhipu: parsed clock=%r name=%r date=%r",
        extraction.clock_time,
        extraction.display_name or extraction.username_hint,
        extraction.clock_date,
    )
    return extraction, None
