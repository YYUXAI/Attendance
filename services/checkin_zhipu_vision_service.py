"""智谱 GLM 视觉模型识别打卡截图（全图一次，无 OCR）。"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import time
from dataclasses import replace
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import httpx

from domain.checkin_image_extraction import CheckinImageExtraction
from infra.checkin_ai_config import CheckinAiConfig
from services.checkin_clock_time_service import (
    clock_time_grounded_in_raw,
)
from services import checkin_identity_match_service
from services.checkin_image_ai_service import (
    CheckinAiExtractError,
    _parse_extraction_payload,
    _prepare_image_bytes,
    _strip_json_payload,
    has_valid_identity_fields,
)
from services.checkin_recognition_log import log_checkin_ai_text
from services.checkin_user_message import (
    MSG_DATE_MISMATCH,
    MSG_EMPLOYEE_ID_MISMATCH,
    MSG_NAME_MISMATCH,
    MSG_TIME_MISMATCH,
)

log = logging.getLogger(__name__)

_ZHIPU_RETRYABLE_HTTP_STATUSES = frozenset({500, 502, 503, 504})
_ZHIPU_API_MAX_ATTEMPTS = 2
_ZHIPU_RETRY_DELAY_SECONDS = 2.0

ZHIPU_DEFAULT_BASE_URL = "https://open.bigmodel.cn/api/paas/v4"
ZHIPU_DEFAULT_MODEL = "glm-4v-flash"
REMOTE_DIFF_ICON_REFERENCE_PATH_ENV = "CHECKIN_REMOTE_DIFF_ICON_REFERENCE_PATH"
REMOTE_DIFF_ICON_REFERENCE_DEFAULT_PATH = "/home/nayxua/Attendance/assets/remote_diff_reference_icon.png"
REMOTE_DIFF_ICON_REFERENCE_2_PATH_ENV = "CHECKIN_REMOTE_DIFF_ICON_REFERENCE_2_PATH"
REMOTE_DIFF_ICON_REFERENCE_2_DEFAULT_PATH = "/home/nayxua/Attendance/assets/remote_diff_reference_icon_2.png"
REMOTE_DIFF_DESKTOP_FALLBACK_ENV = "CHECKIN_REMOTE_DIFF_DESKTOP_FALLBACK"
REMOTE_DIFF_ICON_ZOOM_WIDTH_RATIO_ENV = "CHECKIN_REMOTE_DIFF_ICON_ZOOM_WIDTH_RATIO"
REMOTE_DIFF_ICON_ZOOM_HEIGHT_RATIO_ENV = "CHECKIN_REMOTE_DIFF_ICON_ZOOM_HEIGHT_RATIO"
REMOTE_DIFF_ICON_ZOOM_MIN_SIDE_ENV = "CHECKIN_REMOTE_DIFF_ICON_ZOOM_MIN_SIDE"
REMOTE_DIFF_MAX_IMAGE_SIDE = 1024
_REMOTE_DIFF_ICON_ZOOM_WIDTH_RATIO_DEFAULT = 0.30
_REMOTE_DIFF_ICON_ZOOM_HEIGHT_RATIO_DEFAULT = 0.40
_REMOTE_DIFF_ICON_ZOOM_MIN_SIDE_DEFAULT = 1280

# 正式群默认：不要求 visible_texts
_ZHIPU_EXTRACT_PROMPT = """你是考勤截图 OCR。只抄写图片里肉眼可见的文字，禁止推断、补全、猜测。

图片可能包含：
1. TIME.IS 中央大钟（完整 HH:MM:SS）
2. TIME.IS 日期行（如 6月14日）
3. 右下角 Slack/IM 资料浮窗（头像旁的显示名）

输出一个 JSON 对象，不要 markdown，不要解释。

字段（看不到必须写 null，不要用发图时间或常识补全）：
- display_name: 浮窗显示名（string 或 null）
- username_hint: 浮窗登录名/名片段，不含 @（string 或 null）
- clock_time: 中央大钟，必须与图上显示完全一致（string 或 null）
- clock_date: 仅当图上有日期时输出 MM-DD（string 或 null）
  只需要准确识别月和日（例如图上是 6月22日，则输出 06-22）
- timezone_iana: 仅当图上有明确时区文字时填写（string 或 null）
- confidence: 0 到 1

硬性规则：
- 忽略 Telegram 聊天列表他人、群标题、Bot 回复、配文、@zpxinbot、工号、事项
- 姓名只取 Slack/IM 资料浮窗或本人资料区可见文字；禁止把群名、聊天列表他人当姓名
- 若图上能看到下方「当前发送者登记身份」中的任一名字，优先抄写该名字到 display_name/username_hint
- 只有大钟的一部分数字、或看不清秒/分 → clock_time 填 null
- 图上看不到本人姓名 → display_name 与 username_hint 都填 null
- 图上看不到日期行 → clock_date 填 null
- 禁止编造任何字段

当前发送者登记身份（仅此人；图上可见时优先抄写，不可凭空填写）：
__CANDIDATE_USERNAMES__
"""

_ZHIPU_EXTRACT_KEYWORD_PROMPT = """你是考勤截图关键字段 OCR。只抄写图片可见文字，禁止猜测。

本轮只关注 3 个关键字段（按优先级）：
1) identity_text：Slack/IM 头像旁或本人资料区用户名（如 Y_UX_xxx）
2) clock_time：TIME.IS 主时钟（HH:MM:SS 或 HH:MM）
3) clock_date：TIME.IS 日期行（如 6月16日）；只需识别月和日

输出 JSON（不要 markdown）：
- display_name: string|null
- username_hint: string|null
- clock_time: string|null
- clock_date: MM-DD|null
- timezone_iana: string|null
- confidence: 0~1
- identity_text: 原样抄写的姓名证据（string|null）
- time_text: 原样抄写的时间证据（string|null）
- date_text: 原样抄写的日期证据（string|null）

硬性规则：
- 仅依据图片；忽略 Telegram 配文、群标题、聊天列表他人、@zpxinbot、工号、事项
- 若图上能看到下方「当前发送者登记身份」中的任一名字，优先抄写该名字
- 读不清就填 null，不得补全
- identity_text / time_text / date_text 必须是图片里可见原文

当前发送者登记身份（仅此人；图上可见时优先抄写，不可凭空填写）：
__CANDIDATE_USERNAMES__
"""

# 测试群灰度：抄全 visible_texts，本地选姓名
_ZHIPU_EXTRACT_PROMPT_VISIBLE_TEXTS = """你是考勤截图 OCR。只抄写图片里肉眼可见的文字，禁止推断、补全、猜测。

图片可能包含：
1. TIME.IS 中央大钟（完整 HH:MM:SS）
2. TIME.IS 日期行（如 6月14日）
3. Telegram/IM 侧栏或资料浮窗（头像旁显示名）
4. 系统通知、菜单、网页其它文字

输出一个 JSON 对象，不要 markdown，不要解释。

字段（看不到必须写 null，不要用发图时间或常识补全）：
- visible_texts: 图上可见的短文本列表（array of string）。尽量抄全侧栏资料名、通知、菜单、大钟旁日期等；每条保持原文，不要合并；最多 40 条；禁止编造
- display_name: 资料区显示名（string 或 null）；不要填系统通知/菜单
- username_hint: 资料区登录名/名片段，不含 @（string 或 null）
- clock_time: 中央大钟，必须与图上显示完全一致（string 或 null）
- clock_date: 仅当图上有日期时输出 MM-DD（string 或 null）
  只需要准确识别月和日（例如图上是 6月22日，则输出 06-22）
- timezone_iana: 仅当图上有明确时区文字时填写（string 或 null）
- confidence: 0 到 1

硬性规则：
- visible_texts 必须是图片可见原文；系统通知、菜单也要抄进 visible_texts，但不要当作 display_name
- 姓名只取 Slack/IM 资料浮窗或本人资料区可见文字；禁止把群名、聊天列表他人、系统通知当姓名
- 只有大钟的一部分数字、或看不清秒/分 → clock_time 填 null
- 图上看不到本人姓名 → display_name 与 username_hint 都填 null；禁止把下方登记身份抄进 JSON
- 图上看不到日期行 → clock_date 填 null
- 禁止编造任何字段；登记身份仅用于「在图上对照是否出现」，不可凭空填写

当前发送者登记身份（仅对照用；图上未见则姓名字段必须 null）：
__CANDIDATE_USERNAMES__
"""

_ZHIPU_EXTRACT_KEYWORD_PROMPT_VISIBLE_TEXTS = """你是考勤截图关键字段 OCR。只抄写图片可见文字，禁止猜测。

本轮优先关注：
1) visible_texts：图上可见短文本列表（含资料名、通知、菜单），最多 40 条，原样抄写
2) identity_text：Slack/IM 头像旁或本人资料区用户名（如 Y_UX_xxx）
3) clock_time：TIME.IS 主时钟（HH:MM:SS 或 HH:MM）
4) clock_date：TIME.IS 日期行（如 6月16日）；只需识别月和日

输出 JSON（不要 markdown）：
- visible_texts: string[]（可见原文，可含通知/菜单；禁止编造）
- display_name: string|null（不要填系统通知/菜单）
- username_hint: string|null
- clock_time: string|null
- clock_date: MM-DD|null
- timezone_iana: string|null
- confidence: 0~1
- identity_text: 原样抄写的姓名证据（string|null）
- time_text: 原样抄写的时间证据（string|null）
- date_text: 原样抄写的日期证据（string|null）

硬性规则：
- 仅依据图片；忽略 Telegram 配文、@zpxinbot、工号、事项
- 图上未见本人姓名 → display_name / username_hint / identity_text 必须 null；禁止把下方登记身份抄进 JSON
- 读不清就填 null，不得补全
- identity_text / time_text / date_text / visible_texts 必须是图片里可见原文

当前发送者登记身份（仅对照用；图上未见则姓名相关字段必须 null）：
__CANDIDATE_USERNAMES__
"""

_VISIBLE_DATE_IN_RAW_RE = re.compile(r"20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日")
_VISIBLE_BUDDHIST_DATE_IN_RAW_RE = re.compile(r"25\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日")
_ISO_DATE_IN_RAW_RE = re.compile(r"\b20\d{2}-\d{1,2}-\d{1,2}\b")
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


def _identity_core_token(value: str) -> str:
    """去掉 Y_UX / Y_TC 前缀后的英文名本体；点号与下划线等价。"""
    token = _norm_user_token(value)
    for prefix in ("yux", "ytc"):
        if token.startswith(prefix) and len(token) > len(prefix) + 2:
            return token[len(prefix) :]
    return token


def _identity_field_grounded_in_raw(value: str, raw: str) -> bool:
    """
    姓名字段接地：全文命中，或原文中已有同名本体（如 Karina）。
    避免 Y.UX_Karina ↔ 系统改写的 Y_UX_Karina 因标点差异被误杀。
    """
    if _field_literal_in_raw(value, raw):
        return True
    core = _identity_core_token(value)
    if len(core) < 3:
        return False
    return core in _norm_user_token(raw)


def _parse_zhipu_json_dict(raw: str) -> dict | None:
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
    return parsed


def _parse_zhipu_json_only(raw: str) -> CheckinImageExtraction | None:
    parsed = _parse_zhipu_json_dict(raw)
    if parsed is None:
        return None
    return _parse_extraction_payload(parsed)


def _apply_visible_texts_to_extraction(
    extraction: CheckinImageExtraction,
    *,
    raw: str,
    expected_tg_username: str | None,
    expected_english_name: str | None,
) -> CheckinImageExtraction:
    """AI 返回 visible_texts 后，由本地挑选姓名；列表无本人则清空（禁幻觉）。"""
    if not (expected_tg_username or expected_english_name):
        return extraction
    visible = checkin_identity_match_service.parse_visible_texts_from_raw(raw)
    disp, hint, action = checkin_identity_match_service.apply_visible_texts_identity(
        display_name=extraction.display_name,
        username_hint=extraction.username_hint,
        visible_texts=visible,
        tg_username=expected_tg_username,
        english_name=expected_english_name,
    )
    log.info(
        "checkin_zhipu: visible_texts identity action=%s texts=%s ai_name=%r -> display=%r hint=%r",
        action,
        visible[:12],
        extraction.display_name or extraction.username_hint,
        disp,
        hint,
    )
    return replace(extraction, display_name=disp, username_hint=hint)


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


def _sender_identity_candidates(
    *,
    expected_tg_username: str | None,
    expected_english_name: str | None,
) -> list[str]:
    """提示词与回填仅使用当前发送者登记身份，不再塞全库用户名。"""
    out: list[str] = []
    seen: set[str] = set()
    for raw in (expected_tg_username, expected_english_name):
        token = (raw or "").strip().lstrip("@")
        if not token:
            continue
        key = _norm_user_token(token)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(token)
    return out


def _inject_registered_username_hint(
    extraction: CheckinImageExtraction,
    *,
    raw: str,
    expected_tg_username: str | None,
    candidates: list[str],
) -> CheckinImageExtraction:
    """当模型未稳定填姓名字段时，仅用发送者登记身份做包含/相似回填。"""
    pool = list(candidates)
    if expected_tg_username:
        exp = expected_tg_username.strip().lstrip("@")
        if exp and _norm_user_token(exp) not in {_norm_user_token(x) for x in pool}:
            pool.insert(0, exp)
    if not pool:
        return extraction
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
    log.info("checkin_zhipu: sender identity candidate matched=%s", hit)
    return replace(
        extraction,
        username_hint=extraction.username_hint or hit,
        display_name=extraction.display_name or hit,
    )


def _build_prompt_with_candidates(template: str, candidates: list[str]) -> str:
    if not candidates:
        return template.replace("__CANDIDATE_USERNAMES__", "（未提供发送者登记名）")
    return template.replace("__CANDIDATE_USERNAMES__", ", ".join(candidates))


def _need_keyword_retry(
    extraction: CheckinImageExtraction,
    *,
    expected_date: str = "",
    expected_tg_username: str | None = None,
    expected_english_name: str | None = None,
    retry_on_sender_mismatch: bool = False,
) -> bool:
    """关键字段缺失、日期不对；测试群还可在姓名不像本人时重试。"""
    if not extraction.clock_time:
        return True
    if not has_valid_identity_fields(extraction):
        return True
    if not extraction.clock_date:
        return True
    if expected_date:
        from services.checkin_clock_time_service import date_matches_expected_month_day

        if not date_matches_expected_month_day(
            clock_date=extraction.clock_date,
            expected_date=expected_date,
        ):
            return True
    if retry_on_sender_mismatch and (expected_tg_username or expected_english_name):
        if not checkin_identity_match_service.match_expected_sender(
            display_name=extraction.display_name,
            username_hint=extraction.username_hint,
            tg_username=expected_tg_username,
            english_name=expected_english_name,
        ):
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
    from services.checkin_clock_time_service import (
        normalize_clock_date_month_day,
        reconcile_clock_date,
    )

    merged = reconcile_clock_date(
        clock_date=extraction.clock_date,
        raw_text=raw,
        expected_date=expected_date,
    )
    if merged:
        merged = normalize_clock_date_month_day(merged) or merged
        return replace(extraction, clock_date=merged)
    return extraction


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
    skip_name_verify: bool = False,
) -> CheckinAiExtractError | None:
    """仅接受模型原文中能对应上的识别结果。"""
    if not extraction.clock_time:
        return CheckinAiExtractError("AI_TIME_NOT_FOUND", MSG_TIME_MISMATCH)
    if _clock_time_suspect_padding(extraction.clock_time, raw):
        return CheckinAiExtractError("AI_NOT_GROUNDED", MSG_TIME_MISMATCH)
    if not clock_time_grounded_in_raw(extraction.clock_time, raw):
        return CheckinAiExtractError("AI_NOT_GROUNDED", MSG_TIME_MISMATCH)

    if not skip_name_verify:
        if not has_valid_identity_fields(extraction):
            return CheckinAiExtractError("AI_NAME_NOT_FOUND", MSG_NAME_MISMATCH)

        for val in (extraction.display_name, extraction.username_hint):
            if val and not _identity_field_grounded_in_raw(val, raw):
                return CheckinAiExtractError("AI_NOT_GROUNDED", MSG_NAME_MISMATCH)

    if not extraction.clock_date:
        return CheckinAiExtractError("AI_DATE_NOT_FOUND", MSG_DATE_MISMATCH)
    from services.checkin_clock_time_service import normalize_clock_date_month_day

    norm_extracted = normalize_clock_date_month_day(extraction.clock_date)
    if norm_extracted is None:
        return CheckinAiExtractError("AI_DATE_NOT_FOUND", MSG_DATE_MISMATCH)

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
    reference_images_b64: list[str] | None = None,
    max_tokens: int = 512,
) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Accept-Language": "en-US,en",
    }
    content_blocks: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if reference_images_b64:
        content_blocks.append(
            {
                "type": "text",
                "text": (
                    "【合格参考图标】以下均为合格工号文件夹样式；"
                    "匹配时忽略图标后方/周围的背景颜色（桌面壁纸、底色等），"
                    "只比较黄色文件夹+单个绿色上衣小人造型。"
                    "与任一参考图视觉一致即视为同一类图标："
                ),
            }
        )
        for idx, ref_b64 in enumerate(reference_images_b64, start=1):
            content_blocks.append({"type": "text", "text": f"参考图标 {idx}："})
            content_blocks.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{ref_b64}"},
                }
            )
        content_blocks.append({"type": "text", "text": "待识别截图如下："})
    content_blocks.append(
        {
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
        }
    )

    body: dict[str, Any] = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        # API 侧强制要求返回 JSON，避免模型输出自然语言/markdown。
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "user",
                "content": content_blocks,
            }
        ],
    }
    # 关闭思考链，避免污染 JSON OCR 结果（4.5V / 4.6V 均支持 thinking 开关）
    if any(tag in model.lower() for tag in ("4.5", "4.6")):
        body["thinking"] = {"type": "disabled"}

    last_exc: BaseException | None = None
    for attempt in range(1, _ZHIPU_API_MAX_ATTEMPTS + 1):
        try:
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
            if attempt > 1:
                log.info(
                    "checkin_zhipu: vision ok on retry attempt=%s/%s model=%s",
                    attempt,
                    _ZHIPU_API_MAX_ATTEMPTS,
                    model,
                )
            return content
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if attempt < _ZHIPU_API_MAX_ATTEMPTS and status in _ZHIPU_RETRYABLE_HTTP_STATUSES:
                log.warning(
                    "checkin_zhipu: http %s attempt %s/%s, retry in %.0fs model=%s",
                    status,
                    attempt,
                    _ZHIPU_API_MAX_ATTEMPTS,
                    _ZHIPU_RETRY_DELAY_SECONDS,
                    model,
                )
                last_exc = exc
                await asyncio.sleep(_ZHIPU_RETRY_DELAY_SECONDS)
                continue
            raise
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            if attempt < _ZHIPU_API_MAX_ATTEMPTS:
                log.warning(
                    "checkin_zhipu: %s attempt %s/%s, retry in %.0fs model=%s",
                    type(exc).__name__,
                    attempt,
                    _ZHIPU_API_MAX_ATTEMPTS,
                    _ZHIPU_RETRY_DELAY_SECONDS,
                    model,
                )
                last_exc = exc
                await asyncio.sleep(_ZHIPU_RETRY_DELAY_SECONDS)
                continue
            raise
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("zhipu vision retry exhausted")


_ZHIPU_REMOTE_DIFF_PROMPT = """你是考勤截图识别器。只按图片可见内容输出，禁止猜测。

参考图标是唯一的合格标准：截图中的图标必须与任一参考图标属于同一类工号文件夹，才允许 has_green_person_folder=true。

匹配时请忽略图标背景颜色：不要因桌面壁纸、图标后方底色、裁切边缘颜色而否决；只比较文件夹与绿色小人造型。

参考图标特征（必须同时满足才算匹配）：
- 黄色文件夹
- 文件夹前/overlap 处有且仅有 1 个绿色上衣小人（单人，不是两人）
- 整体造型与任一参考图标一致（允许缩小、模糊，但图标类型必须一致）

按顺序执行：
1) 在桌面区域查找是否存在与参考图标匹配的工号文件夹；逐个排除不合格图标。
2) 仅对匹配参考图标的那一个图标，读取其下方标签工号（纯数字）。
3) 读取浏览器「北京时间」主时钟与日期（月日）。

严禁判为合格（has_green_person_folder 必须为 false）：
- 普通黄色文件夹（无绿色小人）
- Windows「用户」文件夹（蓝衣+绿衣两个小人）
- 共享/网络文件夹（两个白色或灰色小人）
- 任何有两个小人/人形的文件夹图标
- 任何与参考图标造型不一致的文件夹（即使也有小人）
- 看不清楚、无法确认与参考图标一致时

只有明确匹配参考图标时：
- has_green_person_folder=true
- green_person_evidence 须写明“与参考图标一致：黄色文件夹+单个绿色小人”
否则：
- has_green_person_folder=false
- desktop_employee_id=null
- green_person_evidence=""

仅输出 JSON（不要 markdown、不要解释）：
{
  "clock_time": "HH:MM 或 HH:MM:SS 或 null",
  "clock_date": "MM-DD 或 null",
  "desktop_employee_id": "纯数字字符串或 null",
  "has_beijing_time": true/false,
  "has_green_person_folder": true/false,
  "green_person_evidence": "字符串",
  "confidence": 0.0
}
"""


_ZHIPU_REMOTE_DIFF_TIME_PROMPT = """只读取 Google 搜索「北京时间」结果页最上方、最大号的主时钟与日期（月日）。
严禁读取下方 Time.is、timeanddate、百科摘要等次要链接里的小字时间。
若页面为12小时制（含上午/下午/晚上），必须转换为24小时制输出，或填写 clock_period。
仅按图片可见内容输出，禁止猜测。
仅输出 JSON（不要 markdown、不要解释）：
{
  "clock_time": "24小时制 HH:MM 或 HH:MM:SS（如下午7:12必须写19:12），或 null",
  "clock_period": "上午|下午|晚上|凌晨|null（页面可见时填写）",
  "clock_date": "MM-DD 或 null",
  "has_beijing_time": true/false,
  "confidence": 0.0
}
"""


def _load_remote_diff_icon_references_b64() -> list[str]:
    paths = [
        (os.getenv(REMOTE_DIFF_ICON_REFERENCE_PATH_ENV) or "").strip() or REMOTE_DIFF_ICON_REFERENCE_DEFAULT_PATH,
        (os.getenv(REMOTE_DIFF_ICON_REFERENCE_2_PATH_ENV) or "").strip() or REMOTE_DIFF_ICON_REFERENCE_2_DEFAULT_PATH,
    ]
    out: list[str] = []
    for path in paths:
        try:
            raw = Path(path).read_bytes()
        except Exception:
            log.warning("checkin_zhipu: remote_diff icon reference missing path=%s", path)
            continue
        if not raw:
            continue
        out.append(base64.standard_b64encode(raw).decode("ascii"))
    return out


def _remote_diff_desktop_fallback_enabled() -> bool:
    raw = (os.getenv(REMOTE_DIFF_DESKTOP_FALLBACK_ENV) or "false").strip().lower()
    return raw in {"1", "true", "yes", "on"}


_NULLISH_REMOTE_FIELDS = frozenset({"null", "none", "n/a", "na", "unknown", "undefined"})


def _remote_nullable_str(value: object) -> str | None:
    """智谱有时把 JSON null 写成字符串 \"null\"，需当作空值。"""
    if value is None:
        return None
    s = str(value).strip().strip('"').strip("'")
    if not s or s.lower() in _NULLISH_REMOTE_FIELDS:
        return None
    return s


def _remote_has_clock_time(data: dict[str, Any]) -> bool:
    return _remote_nullable_str(data.get("clock_time")) is not None


def _remote_clock_skew_minutes(
    *,
    clock_time: str | None,
    reference_utc: datetime | None,
    shift_timezone: str,
) -> float | None:
    if not clock_time or reference_utc is None:
        return None
    from services.checkin_clock_time_service import ALLOWED_TIMEZONES, _parse_clock_time

    t = _parse_clock_time(clock_time)
    if t is None:
        return None
    try:
        tz = ZoneInfo(shift_timezone if shift_timezone in ALLOWED_TIMEZONES else "Asia/Shanghai")
    except Exception:
        tz = ZoneInfo("Asia/Shanghai")
    ref = reference_utc if reference_utc.tzinfo else reference_utc.replace(tzinfo=timezone.utc)
    ref_local = ref.astimezone(tz)
    local_dt = datetime.combine(ref_local.date(), t, tzinfo=tz)
    return abs((local_dt.astimezone(timezone.utc) - ref).total_seconds()) / 60.0


def _normalize_remote_diff_data(data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    for key in ("clock_time", "clock_date", "clock_period", "am_pm", "desktop_employee_id"):
        if key in out:
            cleaned = _remote_nullable_str(out.get(key))
            if cleaned is None:
                out.pop(key, None)
            else:
                out[key] = cleaned
    return out


def _parse_remote_diff_json(raw: str) -> dict[str, Any] | None:
    # remote_diff 场景强制要求模型直接返回合法 JSON，不做 markdown/片段容错。
    payload = (raw or "").strip()
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


_ZHIPU_REMOTE_DIFF_DESKTOP_PROMPT = """只识别电脑桌面区域的工号文件夹图标及其下方数字工号。

截图已裁切并放大桌面左上角：工号文件夹通常在画面最上方，下方标签为纯数字工号。

【唯一合格标准】必须与任一参考图标一致：黄色文件夹 + 有且仅有 1 个绿色上衣小人（单人）。
匹配时忽略图标背景颜色（桌面壁纸、底色等），只比较文件夹与绿色小人造型。
只有明确匹配参考图标的图标，才允许 has_green_person_folder=true。

严禁判为合格：
- 普通黄色文件夹（无绿色小人）
- Windows「用户」文件夹（蓝衣+绿衣两人）
- 共享/网络文件夹（两个白色或灰色小人）
- 任何两个小人/人形的文件夹
- 与参考图标造型不一致的任何文件夹
- 无法确认与参考图标一致时

匹配参考图标时才读取 desktop_employee_id；否则 desktop_employee_id=null。

输出 JSON（不要 markdown、不要解释）：
{
  "desktop_employee_id": "纯数字字符串或 null",
  "has_green_person_folder": true/false,
  "green_person_evidence": "字符串",
  "confidence": 0.0
}
"""


def _remote_diff_icon_zoom_ratio(*, env_name: str, default: float) -> float:
    raw = (os.getenv(env_name) or "").strip()
    if not raw:
        return default
    try:
        val = float(raw)
    except ValueError:
        return default
    return min(max(val, 0.15), 0.85)


def _remote_diff_icon_zoom_min_side() -> int:
    raw = (os.getenv(REMOTE_DIFF_ICON_ZOOM_MIN_SIDE_ENV) or "").strip()
    if not raw:
        return _REMOTE_DIFF_ICON_ZOOM_MIN_SIDE_DEFAULT
    try:
        val = int(raw)
    except ValueError:
        return _REMOTE_DIFF_ICON_ZOOM_MIN_SIDE_DEFAULT
    return min(max(val, 512), 2048)


def _crop_remote_desktop_panel(image_bytes: bytes) -> bytes:
    """左右分屏时裁切左侧桌面并放大，便于识别小图标。"""
    import io

    from services.checkin_image_ai_service import _image_to_jpeg_bytes, _upscale_bytes_for_vision

    try:
        from PIL import Image
    except ImportError:
        return image_bytes

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    if w < 2 or h < 2:
        return image_bytes
    left_w = max(1, int(w * 0.58))
    crop = img.crop((0, 0, left_w, h))
    return _upscale_bytes_for_vision(_image_to_jpeg_bytes(crop), min_side=896)


def _crop_remote_desktop_icon_zoom(image_bytes: bytes) -> bytes:
    """裁切桌面左上角工号图标区域并大幅放大，便于智谱对比参考图标。"""
    import io

    from services.checkin_image_ai_service import _image_to_jpeg_bytes, _upscale_bytes_for_vision

    try:
        from PIL import Image
    except ImportError:
        return image_bytes

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    if w < 2 or h < 2:
        return image_bytes
    width_ratio = _remote_diff_icon_zoom_ratio(
        env_name=REMOTE_DIFF_ICON_ZOOM_WIDTH_RATIO_ENV,
        default=_REMOTE_DIFF_ICON_ZOOM_WIDTH_RATIO_DEFAULT,
    )
    height_ratio = _remote_diff_icon_zoom_ratio(
        env_name=REMOTE_DIFF_ICON_ZOOM_HEIGHT_RATIO_ENV,
        default=_REMOTE_DIFF_ICON_ZOOM_HEIGHT_RATIO_DEFAULT,
    )
    crop_w = max(1, int(w * width_ratio))
    crop_h = max(1, int(h * height_ratio))
    crop = img.crop((0, 0, crop_w, crop_h))
    min_side = _remote_diff_icon_zoom_min_side()
    return _upscale_bytes_for_vision(_image_to_jpeg_bytes(crop), min_side=min_side)


def _crop_remote_browser_panel(image_bytes: bytes) -> bytes:
    """左右分屏时裁切右侧浏览器区域，专读北京时间。"""
    import io

    from services.checkin_image_ai_service import _image_to_jpeg_bytes, _upscale_bytes_for_vision

    try:
        from PIL import Image
    except ImportError:
        return image_bytes

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    if w < 2 or h < 2:
        return image_bytes
    left_w = max(1, int(w * 0.50))
    crop = img.crop((left_w, 0, w, h))
    return _upscale_bytes_for_vision(_image_to_jpeg_bytes(crop), min_side=640)


def _remote_diff_needs_desktop_fallback(data: dict[str, Any]) -> bool:
    desktop_id = re.sub(r"\D", "", str(data.get("desktop_employee_id") or ""))
    if not desktop_id:
        return True
    return not bool(data.get("has_green_person_folder"))


def _merge_remote_desktop_patch(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    desktop_id = re.sub(r"\D", "", str(patch.get("desktop_employee_id") or ""))
    if desktop_id:
        out["desktop_employee_id"] = desktop_id
    if bool(patch.get("has_green_person_folder")):
        out["has_green_person_folder"] = True
    evidence = str(patch.get("green_person_evidence") or "").strip()
    if evidence:
        out["green_person_evidence"] = evidence
    return out


def _merge_remote_time_patch(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    if "clock_time" in patch:
        clock_time = _remote_nullable_str(patch.get("clock_time"))
        if clock_time:
            out["clock_time"] = clock_time
        else:
            out.pop("clock_time", None)
    if "clock_period" in patch or "am_pm" in patch:
        clock_period = _remote_nullable_str(patch.get("clock_period") or patch.get("am_pm"))
        if clock_period:
            out["clock_period"] = clock_period
        else:
            out.pop("clock_period", None)
    if "clock_date" in patch:
        clock_date = _remote_nullable_str(patch.get("clock_date"))
        if clock_date:
            out["clock_date"] = clock_date
        else:
            out.pop("clock_date", None)
    if bool(patch.get("has_beijing_time")):
        out["has_beijing_time"] = True
    return out


async def _remote_diff_desktop_fallback(
    *,
    base_url: str,
    model: str,
    api_key: str,
    prepared: bytes,
    timeout_seconds: float,
    tg_id: int | None,
    reference_images_b64: list[str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    call_timeout = min(timeout_seconds, 60.0)

    async def _call_panel(panel_bytes: bytes, *, phase: str) -> tuple[dict[str, Any] | None, str | None]:
        panel_b64 = base64.standard_b64encode(panel_bytes).decode("ascii")
        try:
            raw = await _call_zhipu_vision(
                base_url=base_url,
                model=model,
                api_key=api_key,
                image_b64=panel_b64,
                prompt=_ZHIPU_REMOTE_DIFF_DESKTOP_PROMPT,
                timeout_seconds=call_timeout,
                reference_images_b64=reference_images_b64,
                max_tokens=256,
            )
        except Exception:
            log.warning("checkin_zhipu: remote_diff desktop %s failed", phase, exc_info=True)
            return None, None
        patch = _parse_remote_diff_json(raw)
        if patch is None:
            log.warning(
                "checkin_zhipu: remote_diff desktop %s invalid json raw=%s",
                phase,
                (raw or "")[:300],
            )
            return None, raw
        log_checkin_ai_text(phase=f"remote_diff_desktop_{phase}", tg_id=tg_id, raw=raw)
        log.info(
            "checkin_zhipu: remote_diff desktop %s desktop_id=%r folder=%s",
            phase,
            patch.get("desktop_employee_id"),
            patch.get("has_green_person_folder"),
        )
        return patch, raw

    zoom_bytes = _crop_remote_desktop_icon_zoom(prepared)
    patch, raw = await _call_panel(zoom_bytes, phase="icon_zoom")
    if patch is not None and not _remote_diff_needs_desktop_fallback(patch):
        return patch, raw

    panel_bytes = _crop_remote_desktop_panel(prepared)
    patch2, raw2 = await _call_panel(panel_bytes, phase="panel_retry")
    if patch2 is not None:
        if patch is None or _remote_diff_needs_desktop_fallback(patch):
            return patch2, raw2
        merged = _merge_remote_desktop_patch(patch, patch2)
        if not _remote_diff_needs_desktop_fallback(merged):
            return merged, raw2 or raw
        return patch2, raw2
    return patch, raw


async def _remote_diff_parallel_extract(
    *,
    base_url: str,
    model: str,
    api_key: str,
    prepared: bytes,
    timeout_seconds: float,
    tg_id: int | None,
    reference_images_b64: list[str] | None,
) -> tuple[dict[str, Any] | None, str | None, float]:
    """并行：左上角放大读工号图标，整图读北京时间（避免右半裁切切掉主时钟/日期）。"""
    icon_bytes = await asyncio.to_thread(_crop_remote_desktop_icon_zoom, prepared)
    icon_b64 = base64.standard_b64encode(icon_bytes).decode("ascii")
    full_b64 = base64.standard_b64encode(prepared).decode("ascii")
    call_timeout = min(timeout_seconds, 60.0)

    t0 = time.perf_counter()
    icon_result, time_result = await asyncio.gather(
        _call_zhipu_vision(
            base_url=base_url,
            model=model,
            api_key=api_key,
            image_b64=icon_b64,
            prompt=_ZHIPU_REMOTE_DIFF_DESKTOP_PROMPT,
            timeout_seconds=call_timeout,
            reference_images_b64=reference_images_b64,
            max_tokens=256,
        ),
        _call_zhipu_vision(
            base_url=base_url,
            model=model,
            api_key=api_key,
            image_b64=full_b64,
            prompt=_ZHIPU_REMOTE_DIFF_TIME_PROMPT,
            timeout_seconds=call_timeout,
            reference_images_b64=None,
            max_tokens=128,
        ),
        return_exceptions=True,
    )
    elapsed = time.perf_counter() - t0

    icon_raw: str | None = None
    time_raw: str | None = None
    if isinstance(icon_result, BaseException):
        log.warning("checkin_zhipu: remote_diff parallel icon failed", exc_info=icon_result)
    else:
        icon_raw = icon_result
    if isinstance(time_result, BaseException):
        log.warning("checkin_zhipu: remote_diff parallel time failed", exc_info=time_result)
    else:
        time_raw = time_result

    if not icon_raw and not time_raw:
        return None, None, elapsed

    data: dict[str, Any] = {
        "clock_time": None,
        "clock_date": None,
        "desktop_employee_id": None,
        "has_beijing_time": False,
        "has_green_person_folder": False,
        "green_person_evidence": "",
        "confidence": 0.0,
    }
    raw_parts: list[str] = []

    if icon_raw:
        icon_patch = _parse_remote_diff_json(icon_raw)
        if icon_patch is None:
            log.warning(
                "checkin_zhipu: remote_diff parallel icon invalid json raw=%s",
                icon_raw[:300],
            )
        else:
            data = _merge_remote_desktop_patch(data, icon_patch)
            log_checkin_ai_text(phase="remote_diff_parallel_icon_zoom", tg_id=tg_id, raw=icon_raw)
            raw_parts.append(icon_raw)

    if _remote_diff_needs_desktop_fallback(data):
        log.info("checkin_zhipu: remote_diff icon zoom miss, retry left panel")
        panel_bytes = _crop_remote_desktop_panel(prepared)
        panel_b64 = base64.standard_b64encode(panel_bytes).decode("ascii")
        panel_t0 = time.perf_counter()
        try:
            panel_raw = await _call_zhipu_vision(
                base_url=base_url,
                model=model,
                api_key=api_key,
                image_b64=panel_b64,
                prompt=_ZHIPU_REMOTE_DIFF_DESKTOP_PROMPT,
                timeout_seconds=call_timeout,
                reference_images_b64=reference_images_b64,
                max_tokens=256,
            )
            panel_patch = _parse_remote_diff_json(panel_raw)
            if panel_patch is not None:
                data = _merge_remote_desktop_patch(data, panel_patch)
                log_checkin_ai_text(phase="remote_diff_parallel_icon_panel", tg_id=tg_id, raw=panel_raw)
                raw_parts.append(panel_raw)
            elapsed += time.perf_counter() - panel_t0
        except Exception:
            log.warning("checkin_zhipu: remote_diff parallel panel retry failed", exc_info=True)

    if time_raw:
        time_patch = _parse_remote_diff_json(time_raw)
        if time_patch is None:
            log.warning(
                "checkin_zhipu: remote_diff parallel time invalid json raw=%s",
                time_raw[:300],
            )
        else:
            data = _merge_remote_time_patch(data, time_patch)
            log_checkin_ai_text(phase="remote_diff_parallel_time_full", tg_id=tg_id, raw=time_raw)
            raw_parts.append(time_raw)

    combined_raw = "\n".join(raw_parts) if raw_parts else None
    log.info(
        "checkin_zhipu: remote_diff parallel ok sec=%.1f desktop_id=%r folder=%s beijing=%s clock=%r",
        elapsed,
        data.get("desktop_employee_id"),
        data.get("has_green_person_folder"),
        data.get("has_beijing_time"),
        data.get("clock_time"),
    )
    return data, combined_raw, elapsed


async def _remote_diff_time_fallback_full(
    *,
    base_url: str,
    model: str,
    api_key: str,
    image_b64: str,
    timeout_seconds: float,
    tg_id: int | None,
) -> dict[str, Any] | None:
    """浏览器裁切未读到时间时，用整图补一次（无参考图，较快）。"""
    try:
        raw = await _call_zhipu_vision(
            base_url=base_url,
            model=model,
            api_key=api_key,
            image_b64=image_b64,
            prompt=_ZHIPU_REMOTE_DIFF_TIME_PROMPT,
            timeout_seconds=min(timeout_seconds, 45.0),
            reference_images_b64=None,
            max_tokens=128,
        )
    except Exception:
        log.warning("checkin_zhipu: remote_diff time full fallback failed", exc_info=True)
        return None
    patch = _parse_remote_diff_json(raw)
    if patch is None:
        return None
    log_checkin_ai_text(phase="remote_diff_time_full_fallback", tg_id=tg_id, raw=raw)
    return patch


async def extract_remote_checkin_raw_from_zhipu_vision(
    *,
    image_bytes: bytes,
    config: CheckinAiConfig,
    tg_id: int | None = None,
    reference_utc: object | None = None,
    shift_timezone: str = "Asia/Shanghai",
) -> tuple[dict[str, Any] | None, CheckinAiExtractError | None]:
    if not image_bytes:
        return None, CheckinAiExtractError("AI_EMPTY_IMAGE", "打卡失败，图片为空")
    if not (config.api_key or "").strip():
        return None, CheckinAiExtractError(
            "AI_CONFIG_MISSING",
            "打卡失败：未配置智谱 API Key（CHECKIN_AI_API_KEY）。",
        )

    # remote_diff 链路用更小的输入边长，降低视觉推理耗时。
    prepared = _prepare_image_bytes(image_bytes, max_side=REMOTE_DIFF_MAX_IMAGE_SIDE)
    image_b64 = base64.standard_b64encode(prepared).decode("ascii")
    base_url = (config.base_url or ZHIPU_DEFAULT_BASE_URL).rstrip("/")
    model = (config.model or ZHIPU_DEFAULT_MODEL).strip()
    ref_images = _load_remote_diff_icon_references_b64()

    log.info(
        "checkin_zhipu: remote_diff extract start model=%s size_kb=%s ref_icon_count=%s parallel=%s",
        model,
        len(prepared) // 1024,
        len(ref_images),
        _remote_diff_desktop_fallback_enabled(),
    )
    t0 = time.perf_counter()

    if _remote_diff_desktop_fallback_enabled():
        data, raw, _elapsed = await _remote_diff_parallel_extract(
            base_url=base_url,
            model=model,
            api_key=config.api_key.strip(),
            prepared=prepared,
            timeout_seconds=config.timeout_seconds,
            tg_id=tg_id,
            reference_images_b64=ref_images or None,
        )
        if data is None:
            log.error("checkin_zhipu: remote_diff parallel failed model=%s", model)
            return None, CheckinAiExtractError(
                "AI_EXTRACT_FAILED",
                "打卡失败，智谱识别异常。请换一张更清晰的截图重试。",
            )
        if raw:
            log_checkin_ai_text(phase="remote_diff", tg_id=tg_id, raw=raw)
        if not data.get("has_beijing_time") or not _remote_has_clock_time(data):
            log.info("checkin_zhipu: remote_diff time miss after full-image parallel, retry")
            time_patch = await _remote_diff_time_fallback_full(
                base_url=base_url,
                model=model,
                api_key=config.api_key.strip(),
                image_b64=image_b64,
                timeout_seconds=config.timeout_seconds,
                tg_id=tg_id,
            )
            if time_patch:
                data = _merge_remote_time_patch(data, time_patch)
        log.info(
            "checkin_zhipu: remote_diff vision ok model=%s sec=%.1f raw_len=%s",
            model,
            time.perf_counter() - t0,
            len(raw or ""),
        )
    else:
        try:
            raw = await _call_zhipu_vision(
                base_url=base_url,
                model=model,
                api_key=config.api_key.strip(),
                image_b64=image_b64,
                prompt=_ZHIPU_REMOTE_DIFF_PROMPT,
                timeout_seconds=config.timeout_seconds,
                reference_images_b64=ref_images or None,
                max_tokens=256,
            )
            log.info(
                "checkin_zhipu: remote_diff vision ok model=%s sec=%.1f raw_len=%s",
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
            log.exception("checkin_zhipu: remote_diff http %s model=%s body=%s", status, model, err_body[:200])
            if status in {401, 403}:
                return None, CheckinAiExtractError("AI_AUTH_FAILED", "打卡失败：智谱 API Key 无效或已过期，请检查 CHECKIN_AI_API_KEY。")
            if "Insufficient balance" in err_body or '"code":"1113"' in err_body:
                return None, CheckinAiExtractError("AI_BALANCE_EXHAUSTED", "打卡失败：智谱账户余额不足，请充值后重试。")
            if status == 429:
                return None, CheckinAiExtractError("AI_RATE_LIMIT", "打卡失败：智谱 API 调用频率超限，请稍后重试。")
            return None, CheckinAiExtractError("AI_HTTP_ERROR", f"打卡失败，智谱 API 返回错误（HTTP {status}）。")
        except httpx.TimeoutException:
            log.exception("checkin_zhipu: remote_diff timeout model=%s", model)
            return None, CheckinAiExtractError(
                "AI_TIMEOUT",
                f"打卡失败，智谱识别超时（{int(config.timeout_seconds)} 秒）。请稍后重试。",
            )
        except httpx.ConnectError:
            log.exception("checkin_zhipu: remote_diff connect failed")
            return None, CheckinAiExtractError("AI_SERVICE_DOWN", "打卡失败：无法连接智谱 API，请检查网络。")
        except Exception:
            log.exception("checkin_zhipu: remote_diff vision failed model=%s", model)
            return None, CheckinAiExtractError("AI_EXTRACT_FAILED", "打卡失败，智谱识别异常。请换一张更清晰的截图重试。")

        data = _parse_remote_diff_json(raw)
        if data is None:
            log.warning("checkin_zhipu: remote_diff invalid json raw=%s", raw[:500])
            log_checkin_ai_text(phase="remote_diff_invalid_json", tg_id=tg_id, raw=raw)
            return None, CheckinAiExtractError("AI_EXTRACT_FAILED", MSG_TIME_MISMATCH)

        log_checkin_ai_text(phase="remote_diff", tg_id=tg_id, raw=raw)

        if _remote_diff_needs_desktop_fallback(data):
            log.info("checkin_zhipu: remote_diff full image icon miss, desktop icon zoom retry")
            patch, raw_fb = await _remote_diff_desktop_fallback(
                base_url=base_url,
                model=model,
                api_key=config.api_key.strip(),
                prepared=prepared,
                timeout_seconds=config.timeout_seconds,
                tg_id=tg_id,
                reference_images_b64=ref_images or None,
            )
            if patch is not None:
                data = _merge_remote_desktop_patch(data, patch)
                if raw_fb:
                    log_checkin_ai_text(phase="remote_diff_desktop_retry", tg_id=tg_id, raw=raw_fb)

    expected_date = _expected_date_for_parse(reference_utc=reference_utc, shift_timezone=shift_timezone)
    extraction_probe = _parse_extraction_payload(data)
    extraction_probe = _patch_missing_clock_date(
        extraction=extraction_probe,
        raw=raw or "",
        expected_date=expected_date,
    )
    data = _normalize_remote_diff_data(data)

    if extraction_probe.clock_date:
        from services.checkin_clock_time_service import normalize_clock_date_month_day

        norm_date = normalize_clock_date_month_day(extraction_probe.clock_date)
        if norm_date:
            data = dict(data)
            data["clock_date"] = norm_date

    from services.checkin_clock_time_service import resolve_remote_diff_clock_time

    ref_dt = reference_utc if isinstance(reference_utc, datetime) else None
    if ref_dt is not None and ref_dt.tzinfo is None:
        ref_dt = ref_dt.replace(tzinfo=timezone.utc)
    resolved_time = resolve_remote_diff_clock_time(
        clock_time=_remote_nullable_str(data.get("clock_time")),
        clock_period=_remote_nullable_str(data.get("clock_period") or data.get("am_pm")),
        raw_text=raw or "",
        reference_utc=ref_dt,
        shift_timezone=shift_timezone,
        max_skew_minutes=int(config.max_clock_skew_minutes),
    )
    if resolved_time and resolved_time != data.get("clock_time"):
        data = dict(data)
        data["clock_time"] = resolved_time
        log.info(
            "checkin_zhipu: remote_diff clock normalized %r -> %r",
            extraction_probe.clock_time,
            resolved_time,
        )

    max_skew = int(config.max_clock_skew_minutes)
    cur_time = _remote_nullable_str(data.get("clock_time"))
    cur_skew = _remote_clock_skew_minutes(
        clock_time=cur_time,
        reference_utc=ref_dt,
        shift_timezone=shift_timezone,
    )
    if ref_dt is not None and cur_skew is not None and cur_skew > max_skew:
        log.info(
            "checkin_zhipu: remote_diff clock skew %.1fm > %sm (%r), full fallback retry",
            cur_skew,
            max_skew,
            cur_time,
        )
        time_patch = await _remote_diff_time_fallback_full(
            base_url=base_url,
            model=model,
            api_key=config.api_key.strip(),
            image_b64=image_b64,
            timeout_seconds=config.timeout_seconds,
            tg_id=tg_id,
        )
        if time_patch:
            fb_resolved = resolve_remote_diff_clock_time(
                clock_time=_remote_nullable_str(time_patch.get("clock_time")),
                clock_period=_remote_nullable_str(time_patch.get("clock_period") or time_patch.get("am_pm")),
                raw_text=str(time_patch),
                reference_utc=ref_dt,
                shift_timezone=shift_timezone,
                max_skew_minutes=max_skew,
            )
            fb_time = fb_resolved or _remote_nullable_str(time_patch.get("clock_time"))
            fb_skew = _remote_clock_skew_minutes(
                clock_time=fb_time,
                reference_utc=ref_dt,
                shift_timezone=shift_timezone,
            )
            if fb_time and fb_skew is not None and fb_skew <= max_skew:
                data = _merge_remote_time_patch(data, time_patch)
                data = dict(data)
                data["clock_time"] = fb_time
                log.info(
                    "checkin_zhipu: remote_diff clock fallback ok %r -> %r skew=%.1fm",
                    cur_time,
                    fb_time,
                    fb_skew,
                )
            elif fb_time and fb_skew is not None and (cur_skew is None or fb_skew < cur_skew):
                data = _merge_remote_time_patch(data, time_patch)
                data = dict(data)
                data["clock_time"] = fb_time
                log.info(
                    "checkin_zhipu: remote_diff clock fallback improved %r -> %r skew=%.1fm",
                    cur_time,
                    fb_time,
                    fb_skew,
                )

    log.info(
        "checkin_zhipu: remote_diff parsed clock=%r desktop_id=%r beijing=%s folder=%s",
        data.get("clock_time"),
        data.get("desktop_employee_id"),
        data.get("has_beijing_time"),
        data.get("has_green_person_folder"),
    )
    return data, None


_ZHIPU_AVATAR_MENU_PROMPT = """判断这张打卡截图里，是否出现手机 Telegram 设置/资料页中的「设置头像」或「更改头像」文字或按钮。

只依据图片可见内容，不要猜测。
只输出 JSON，不要 markdown：
{"has_avatar_menu":true|false,"evidence":"原样抄写的相关文字或空字符串"}"""


async def detect_avatar_menu_via_zhipu(
    *,
    image_bytes: bytes,
    config: CheckinAiConfig,
) -> bool:
    """智谱专检：图中是否出现「设置头像」「更改头像」。"""
    prepared = _prepare_image_bytes(image_bytes)
    image_b64 = base64.standard_b64encode(prepared).decode("ascii")
    base_url = (config.base_url or ZHIPU_DEFAULT_BASE_URL).rstrip("/")
    model = (config.model or ZHIPU_DEFAULT_MODEL).strip()
    raw = await _call_zhipu_vision(
        base_url=base_url,
        api_key=config.api_key,
        model=model,
        image_b64=image_b64,
        prompt=_ZHIPU_AVATAR_MENU_PROMPT,
        timeout_seconds=min(float(config.timeout_seconds), 45.0),
    )
    text = (raw or "").strip()
    if "设置头像" in text or "更改头像" in text:
        return True
    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            if bool(payload.get("has_avatar_menu")):
                return True
            evidence = str(payload.get("evidence") or "")
            if any(m in evidence for m in ("设置头像", "更改头像")):
                return True
    except json.JSONDecodeError:
        pass
    low = text.lower()
    return "true" in low and ("avatar" in low or "头像" in text)


async def extract_checkin_from_zhipu_vision(
    *,
    image_bytes: bytes,
    config: CheckinAiConfig,
    expected_tg_username: str | None = None,
    expected_english_name: str | None = None,
    reference_utc: object | None = None,
    shift_timezone: str = "Asia/Shanghai",
    tg_id: int | None = None,
    skip_name_verify: bool = False,
    chat_id: int | None = None,
    chat_title: str | None = None,
) -> tuple[Optional[CheckinImageExtraction], Optional[CheckinAiExtractError]]:
    if not image_bytes:
        return None, CheckinAiExtractError("AI_EMPTY_IMAGE", "打卡失败，图片为空")
    if not (config.api_key or "").strip():
        return None, CheckinAiExtractError(
            "AI_CONFIG_MISSING",
            "打卡失败：未配置智谱 API Key（CHECKIN_AI_API_KEY）。",
        )

    from infra.checkin_visible_texts_config import visible_texts_identity_enabled

    use_visible_texts = visible_texts_identity_enabled(chat_id=chat_id, chat_title=chat_title)

    prepared = _prepare_image_bytes(image_bytes)
    image_b64 = base64.standard_b64encode(prepared).decode("ascii")

    base_url = (config.base_url or ZHIPU_DEFAULT_BASE_URL).rstrip("/")
    model = (config.model or ZHIPU_DEFAULT_MODEL).strip()
    candidates = _sender_identity_candidates(
        expected_tg_username=expected_tg_username,
        expected_english_name=expected_english_name,
    )
    extract_prompt = (
        _ZHIPU_EXTRACT_PROMPT_VISIBLE_TEXTS if use_visible_texts else _ZHIPU_EXTRACT_PROMPT
    )
    keyword_prompt = (
        _ZHIPU_EXTRACT_KEYWORD_PROMPT_VISIBLE_TEXTS
        if use_visible_texts
        else _ZHIPU_EXTRACT_KEYWORD_PROMPT
    )
    prompt = _build_prompt_with_candidates(extract_prompt, candidates)

    log.info(
        "checkin_zhipu: extract start model=%s size_kb=%s strict=image_only "
        "visible_texts=%s chat_id=%s sender_candidates=%s",
        model,
        len(prepared) // 1024,
        use_visible_texts,
        chat_id,
        candidates,
    )
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
                "打卡失败：智谱 API Key 无效或已过期，请检查 CHECKIN_AI_API_KEY。",
            )
        if "Insufficient balance" in err_body or '"code":"1113"' in err_body:
            return None, CheckinAiExtractError(
                "AI_BALANCE_EXHAUSTED",
                "打卡失败：智谱账户余额不足，请充值后重试。",
            )
        if status == 429:
            return None, CheckinAiExtractError(
                "AI_RATE_LIMIT",
                "打卡失败：智谱 API 调用频率超限，请稍后重试。",
            )
        return None, CheckinAiExtractError(
            "AI_HTTP_ERROR",
            f"打卡失败，智谱 API 返回错误（HTTP {status}）。",
        )
    except httpx.TimeoutException:
        log.exception("checkin_zhipu: timeout model=%s", model)
        return None, CheckinAiExtractError(
            "AI_TIMEOUT",
            f"打卡失败，智谱识别超时（{int(config.timeout_seconds)} 秒）。请稍后重试。",
        )
    except httpx.ConnectError:
        log.exception("checkin_zhipu: connect failed")
        return None, CheckinAiExtractError(
            "AI_SERVICE_DOWN",
            "打卡失败：无法连接智谱 API，请检查网络。",
        )
    except Exception:
        log.exception("checkin_zhipu: vision failed model=%s", model)
        return None, CheckinAiExtractError(
            "AI_EXTRACT_FAILED",
            "打卡失败，智谱识别异常。请换一张更清晰的截图重试。",
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

    expected_date = _expected_date_for_parse(reference_utc=reference_utc, shift_timezone=shift_timezone)
    if use_visible_texts and not skip_name_verify:
        extraction = _apply_visible_texts_to_extraction(
            extraction,
            raw=raw,
            expected_tg_username=expected_tg_username,
            expected_english_name=expected_english_name,
        )

    # 关键字段缺失时再做关键字优先识别；测试群还可在姓名不像本人时重试
    if _need_keyword_retry(
        extraction,
        expected_date=expected_date,
        expected_tg_username=None if skip_name_verify else expected_tg_username,
        expected_english_name=None if skip_name_verify else expected_english_name,
        retry_on_sender_mismatch=use_visible_texts and not skip_name_verify,
    ):
        try:
            raw_retry = await _call_zhipu_vision(
                base_url=base_url,
                model=model,
                api_key=config.api_key.strip(),
                image_b64=image_b64,
                prompt=_build_prompt_with_candidates(keyword_prompt, candidates),
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
                if use_visible_texts and not skip_name_verify:
                    extraction = _apply_visible_texts_to_extraction(
                        extraction,
                        raw=raw,
                        expected_tg_username=expected_tg_username,
                        expected_english_name=expected_english_name,
                    )
        except Exception:
            log.warning("checkin_zhipu: keyword retry failed", exc_info=True)

    # 二次保障：按月日纠正模型日期（不使用 OCR 兜底）
    extraction = _patch_missing_clock_date(
        extraction=extraction,
        raw=raw,
        expected_date=expected_date,
    )
    if extraction.clock_date:
        from services.checkin_clock_time_service import normalize_clock_date_month_day

        norm_date = normalize_clock_date_month_day(extraction.clock_date)
        if norm_date:
            extraction = replace(extraction, clock_date=norm_date)

    # visible_texts 模式：姓名只认列表本地挑选结果，禁止从 raw JSON / 登记身份回填（防幻觉自证）
    if not (use_visible_texts and not skip_name_verify):
        extraction = _promote_identity_text_from_raw(extraction, raw=raw)
        extraction = _inject_registered_username_hint(
            extraction,
            raw=raw,
            expected_tg_username=expected_tg_username,
            candidates=candidates,
        )
        if not skip_name_verify and (
            expected_tg_username or expected_english_name
        ):
            resolved = checkin_identity_match_service.resolve_sender_identity_plan_b(
                display_name=extraction.display_name,
                username_hint=extraction.username_hint,
                raw=raw,
                tg_username=expected_tg_username,
                english_name=expected_english_name,
            )
            if resolved is not None:
                extraction = replace(
                    extraction,
                    display_name=resolved.display_name or extraction.display_name,
                    username_hint=resolved.username_hint or extraction.username_hint,
                )
                log.info(
                    "checkin_zhipu: plan_b identity filled from raw display=%r hint=%r",
                    extraction.display_name,
                    extraction.username_hint,
                )
            elif checkin_identity_match_service.is_attendance_group_identity_noise(
                extraction.display_name,
                extraction.username_hint,
            ):
                if checkin_identity_match_service.match_expected_sender(
                    display_name=extraction.display_name,
                    username_hint=extraction.username_hint,
                    tg_username=expected_tg_username,
                    english_name=expected_english_name,
                ):
                    # 已认出本人：只清群名噪声字段，保留本人姓名（勿整单清空）
                    disp, hint = checkin_identity_match_service.strip_group_name_noise_fields(
                        display_name=extraction.display_name,
                        username_hint=extraction.username_hint,
                    )
                    extraction = replace(extraction, display_name=disp, username_hint=hint)
                    log.info(
                        "checkin_zhipu: plan_b stripped group-name noise, kept sender display=%r hint=%r",
                        extraction.display_name,
                        extraction.username_hint,
                    )
                else:
                    # 只有群名噪声、全文无本人 → 清空姓名，强制失败（不回填登记名）
                    extraction = replace(extraction, display_name=None, username_hint=None)
                    log.info("checkin_zhipu: plan_b cleared group-name noise without sender in raw")
    elif use_visible_texts and not skip_name_verify:
        # 二次确认：最终姓名仍须能从 visible_texts 挑出，否则清空
        visible = checkin_identity_match_service.parse_visible_texts_from_raw(raw)
        picked = checkin_identity_match_service.pick_sender_identity_from_visible_texts(
            visible_texts=visible,
            tg_username=expected_tg_username,
            english_name=expected_english_name,
        )
        if picked is None and (extraction.display_name or extraction.username_hint):
            log.info(
                "checkin_zhipu: visible_texts final clear ungrounded name=%r",
                extraction.display_name or extraction.username_hint,
            )
            extraction = replace(extraction, display_name=None, username_hint=None)
        elif picked is not None:
            extraction = replace(
                extraction,
                display_name=picked[0],
                username_hint=picked[1],
            )

    ground_err = _validate_image_only_extraction(
        extraction,
        raw=raw,
        skip_name_verify=skip_name_verify,
    )
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
