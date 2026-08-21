"""UX 考勤：仅 ux助手考勤测试群走 OCR.space（分块/规则/Key 轮换；基建失败回退智谱）。"""
from __future__ import annotations

import os
import threading
from pathlib import Path

_DEFAULT_EXTRACT_CHAT_IDS: frozenset[int] = frozenset(
    {
        -1004347063533,  # ux助手考勤测试群
    }
)
_DEFAULT_EXTRACT_TITLES: frozenset[str] = frozenset(
    {
        "ux助手考勤测试群",
    }
)

_RR_LOCK = threading.Lock()
_RR_INDEX = 0


def is_ocrspace_extract_chat(
    *,
    chat_id: int | None,
    chat_title: str | None = None,
) -> bool:
    if chat_id is not None and int(chat_id) in _DEFAULT_EXTRACT_CHAT_IDS:
        return True
    title = (chat_title or "").strip()
    return bool(title and title in _DEFAULT_EXTRACT_TITLES)


def is_ocrspace_experiment_chat(
    *,
    chat_id: int | None,
    chat_title: str | None = None,
) -> bool:
    return is_ocrspace_extract_chat(chat_id=chat_id, chat_title=chat_title)


def _raw_api_keys_text() -> str:
    raw = (os.getenv("OCRSPACE_API_KEYS") or "").strip()
    if raw:
        return raw
    single = (os.getenv("OCRSPACE_API_KEY") or "").strip()
    if single:
        return single
    file_env = (os.getenv("OCRSPACE_API_KEYS_FILE") or "").strip()
    candidates = []
    if file_env:
        candidates.append(file_env)
    candidates.extend(
        (
            "/run/secrets/ocrspace_api_keys",
            "/run/secrets/ocrspace_api_key",
        )
    )
    for candidate in candidates:
        try:
            text = Path(candidate).read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            return text
    return ""


def ocrspace_api_keys() -> list[str]:
    raw = _raw_api_keys_text()
    keys: list[str] = []
    for part in raw.replace("，", ",").replace("\n", ",").split(","):
        p = part.strip()
        if p and p not in keys:
            keys.append(p)
    return keys


def ocrspace_api_key() -> str:
    return next_ocrspace_api_key()


def next_ocrspace_api_key() -> str:
    global _RR_INDEX
    keys = ocrspace_api_keys()
    if not keys:
        return ""
    with _RR_LOCK:
        key = keys[_RR_INDEX % len(keys)]
        _RR_INDEX += 1
        return key


def ocrspace_api_key_count() -> int:
    return len(ocrspace_api_keys())


def ocrspace_api_url() -> str:
    return "https://api.ocr.space/parse/image"


def ocrspace_language() -> str:
    return "auto"


def ocrspace_engine() -> str:
    return "2"
