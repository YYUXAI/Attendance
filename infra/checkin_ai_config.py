from __future__ import annotations

import os
from dataclasses import dataclass


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


def load_checkin_ai_config() -> CheckinAiConfig:
    enabled = os.getenv("CHECKIN_AI_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
    extract_backend = (os.getenv("CHECKIN_AI_EXTRACT_BACKEND") or "zhipu").strip().lower()
    if extract_backend not in {"ollama", "ocr_only", "ocr_text_llm", "zhipu"}:
        extract_backend = "zhipu"

    if extract_backend == "zhipu":
        base_url = (os.getenv("CHECKIN_AI_BASE_URL") or "https://api.z.ai/api/paas/v4").rstrip("/")
        api_key = (
            os.getenv("CHECKIN_AI_API_KEY")
            or os.getenv("ZAI_API_KEY")
            or os.getenv("ZHIPU_API_KEY")
            or ""
        ).strip()
        model = os.getenv("CHECKIN_AI_MODEL") or "glm-4.6v-flash"
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
