from __future__ import annotations

import logging
import os
from dataclasses import dataclass, replace

log = logging.getLogger(__name__)

# 专群：测试群 + Y-UX-KQBBQ → 新智谱 API + glm-4.6v
_DEFAULT_PREMIUM_CHAT_IDS: frozenset[int] = frozenset()
_DEFAULT_PREMIUM_TITLES: frozenset[str] = frozenset(
    {
        "测试群",
        "Y-UX-KQBBQ",
    }
)


@dataclass(frozen=True)
class CheckinAiConfig:
    enabled: bool
    base_url: str
    api_key: str
    model: str
    mode: str
    max_clock_skew_minutes: int
    timeout_seconds: float
    trust_sender_when_name_unreadable: bool
    name_verify_mode: str
    extract_backend: str
    clock_fallback_send_time: bool
    text_model: str

    @property
    def ocr_only(self) -> bool:
        return self.extract_backend == "ocr_only"

    @property
    def ocr_text_llm(self) -> bool:
        return self.extract_backend == "ocr_text_llm"


    @property
    def zhipu(self) -> bool:
        return self.extract_backend == "zhipu"


def _parse_int_set(raw: str) -> frozenset[int]:
    out: set[int] = set()
    for part in (raw or "").replace("，", ",").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.add(int(p))
        except ValueError:
            continue
    return frozenset(out)


def _parse_str_set(raw: str) -> frozenset[str]:
    return frozenset(p.strip() for p in (raw or "").replace("，", ",").split(",") if p.strip())


def premium_zhipu_chat_ids() -> frozenset[int]:
    raw = (os.getenv("CHECKIN_AI_PREMIUM_CHAT_IDS") or "").strip()
    if not raw:
        return _DEFAULT_PREMIUM_CHAT_IDS
    return _parse_int_set(raw)


def premium_zhipu_group_titles() -> frozenset[str]:
    raw = (os.getenv("CHECKIN_AI_PREMIUM_GROUP_TITLES") or "").strip()
    if not raw:
        return _DEFAULT_PREMIUM_TITLES
    return _parse_str_set(raw)


def premium_zhipu_enabled(*, chat_id: int | None, chat_title: str | None = None) -> bool:
    """测试群 / BBQ 是否走专群智谱（新 key + glm-4.6v）。"""
    flag = (os.getenv("CHECKIN_AI_PREMIUM_ENABLED") or "true").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    if chat_id is not None and int(chat_id) in premium_zhipu_chat_ids():
        return True
    title = (chat_title or "").strip()
    return bool(title and title in premium_zhipu_group_titles())


def resolve_checkin_ai_config_for_chat(
    config: CheckinAiConfig,
    *,
    chat_id: int | None,
    chat_title: str | None = None,
) -> CheckinAiConfig:
    """按群覆盖智谱 API Key / 模型；非专群原样返回。"""
    if not config.zhipu:
        return config
    if not premium_zhipu_enabled(chat_id=chat_id, chat_title=chat_title):
        return config
    premium_key = (
        os.getenv("CHECKIN_AI_PREMIUM_API_KEY")
        or os.getenv("ZHIPU_PREMIUM_API_KEY")
        or ""
    ).strip()
    if not premium_key:
        log.warning(
            "checkin_ai: premium group chat_id=%s but CHECKIN_AI_PREMIUM_API_KEY empty; keep default key",
            chat_id,
        )
        return config
    premium_model = (os.getenv("CHECKIN_AI_PREMIUM_MODEL") or "glm-4.6v").strip() or "glm-4.6v"
    premium_base = (
        os.getenv("CHECKIN_AI_PREMIUM_BASE_URL") or config.base_url or ""
    ).strip().rstrip("/") or config.base_url
    log.info(
        "checkin_ai: premium zhipu chat_id=%s title=%r model=%s key=...%s",
        chat_id,
        (chat_title or "")[:40],
        premium_model,
        premium_key[-6:] if len(premium_key) >= 6 else "****",
    )
    return replace(
        config,
        api_key=premium_key,
        model=premium_model,
        base_url=premium_base,
    )


def load_checkin_ai_config() -> CheckinAiConfig:
    enabled = os.getenv("CHECKIN_AI_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    extract_backend = (os.getenv("CHECKIN_AI_EXTRACT_BACKEND") or "zhipu").strip().lower()
    if extract_backend not in {"ollama", "ocr_only", "ocr_text_llm", "zhipu"}:
        extract_backend = "zhipu"

    if extract_backend == "zhipu":
        base_url = (os.getenv("CHECKIN_AI_BASE_URL") or "https://open.bigmodel.cn/api/paas/v4").rstrip("/")
        api_key = (
            os.getenv("CHECKIN_AI_API_KEY")
            or os.getenv("ZHIPU_API_KEY")
            or os.getenv("ZAI_API_KEY")
            or ""
        ).strip()
        model = os.getenv("CHECKIN_AI_MODEL") or "glm-4v-flash"
    else:
        base_url = (os.getenv("CHECKIN_AI_BASE_URL") or "http://127.0.0.1:11434/v1").rstrip("/")
        api_key = os.getenv("CHECKIN_AI_API_KEY") or "ollama"
        model = os.getenv("CHECKIN_AI_MODEL") or "moondream"
    # assist：仅当 CHECKIN_AI_ENABLED=false 时由调用方走服务器时间；开启后一律严格校验姓名+时间
    mode = (os.getenv("CHECKIN_AI_MODE") or "required").strip().lower()
    if mode not in {"assist", "required"}:
        mode = "required"
    try:
        max_skew = int(os.getenv("CHECKIN_AI_MAX_CLOCK_SKEW_MINUTES") or "30")
    except ValueError:
        max_skew = 30
    try:
        timeout = float(os.getenv("CHECKIN_AI_TIMEOUT_SECONDS") or "300")
    except ValueError:
        timeout = 90.0
    trust_sender = os.getenv("CHECKIN_AI_TRUST_SENDER_WHEN_NAME_UNREADABLE", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    text_model = (os.getenv("CHECKIN_AI_TEXT_MODEL") or os.getenv("CHECKIN_AI_MODEL") or "qwen2.5:3b").strip()
    name_verify = (os.getenv("CHECKIN_AI_NAME_VERIFY") or "vision").strip().lower()
    if name_verify not in {"vision", "ocr", "both"}:
        name_verify = "vision"
    if extract_backend == "zhipu":
        name_verify = "vision"
    elif extract_backend in {"ocr_only", "ocr_text_llm"} and name_verify == "vision":
        name_verify = "ocr"
    fallback_raw = os.getenv("CHECKIN_AI_CLOCK_FALLBACK_SEND_TIME")
    if fallback_raw is None or not fallback_raw.strip():
        clock_fallback = extract_backend not in {"ocr_only", "ocr_text_llm"}
    else:
        clock_fallback = fallback_raw.strip().lower() in {"1", "true", "yes", "on"}
    return CheckinAiConfig(
        enabled=enabled,
        base_url=base_url,
        api_key=api_key,
        model=model,
        mode=mode,
        max_clock_skew_minutes=max(1, max_skew),
        timeout_seconds=max(5.0, timeout),
        trust_sender_when_name_unreadable=trust_sender,
        name_verify_mode=name_verify,
        extract_backend=extract_backend,
        clock_fallback_send_time=clock_fallback,
        text_model=text_model,
    )
