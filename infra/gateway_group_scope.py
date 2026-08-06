"""统一网关分流：判断群是否走 Omni（读 bot_gateway/.env 或环境变量）。"""

from __future__ import annotations

import os
from functools import lru_cache

from dotenv import load_dotenv


def _parse_id_set(raw: str | None) -> frozenset[int]:
    if not raw or not str(raw).strip():
        return frozenset()
    out: set[int] = set()
    for part in str(raw).split(","):
        part = part.strip()
        if part:
            out.add(int(part))
    return frozenset(out)


def _gateway_enabled() -> bool:
    v = (os.getenv("GATEWAY_ENABLED") or "").strip().lower()
    if not v:
        return False
    return v in ("1", "true", "yes", "on")


@lru_cache
def _load_sets() -> tuple[frozenset[int], frozenset[int]]:
    load_dotenv(override=False)
    attendance = _parse_id_set(os.getenv("GATEWAY_ATTENDANCE_CHAT_IDS"))
    omni_in = _parse_id_set(os.getenv("GATEWAY_OMNI_INPUT_CHAT_IDS"))
    omni_client = _parse_id_set(os.getenv("GATEWAY_OMNI_CLIENT_GROUP_CHAT_IDS"))
    if not omni_client:
        omni_client = _parse_id_set(os.getenv("GROUP_CHAT_IDS"))
    if not omni_in:
        omni_in = _parse_id_set(os.getenv("ALLOWED_CHAT_IDS"))
    omni = omni_in | omni_client
    return attendance, omni


def attendance_group_chat_ids() -> frozenset[int]:
    if not _gateway_enabled():
        return frozenset()
    return _load_sets()[0]


def omni_group_chat_ids() -> frozenset[int]:
    if not _gateway_enabled():
        return frozenset()
    return _load_sets()[1]


def is_omni_group_chat(chat_id: int) -> bool:
    return int(chat_id) in omni_group_chat_ids()


def is_attendance_group_chat(chat_id: int) -> bool:
    ids = attendance_group_chat_ids()
    if not ids:
        return not is_omni_group_chat(chat_id)
    return int(chat_id) in ids
