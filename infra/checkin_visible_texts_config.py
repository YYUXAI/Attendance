"""visible_texts 姓名纠偏：默认关闭；需显式配置群才开启。

正式 BBQ / 测试群当前均走旧姓名逻辑（AI 填名 + plan_b），
因弱模型常抄不全 visible_texts，本地选名通过率过低。
"""
from __future__ import annotations

import os

# 默认全关：测试群也不再走本地选名
_DEFAULT_VISIBLE_TEXTS_CHAT_IDS: frozenset[int] = frozenset()
_DEFAULT_VISIBLE_TEXTS_TITLES: frozenset[str] = frozenset()


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


def visible_texts_chat_ids() -> frozenset[int]:
    raw = (os.getenv("CHECKIN_VISIBLE_TEXTS_CHAT_IDS") or "").strip()
    if not raw:
        return _DEFAULT_VISIBLE_TEXTS_CHAT_IDS
    return _parse_int_set(raw)


def visible_texts_group_titles() -> frozenset[str]:
    raw = (os.getenv("CHECKIN_VISIBLE_TEXTS_GROUP_TITLES") or "").strip()
    if not raw:
        return _DEFAULT_VISIBLE_TEXTS_TITLES
    return _parse_str_set(raw)


def visible_texts_identity_enabled(
    *,
    chat_id: int | None,
    chat_title: str | None = None,
) -> bool:
    """是否启用 visible_texts 抄全 + 本地选姓名。默认关闭。"""
    flag = (os.getenv("CHECKIN_VISIBLE_TEXTS_ENABLED") or "false").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    if chat_id is not None and int(chat_id) in visible_texts_chat_ids():
        return True
    title = (chat_title or "").strip()
    return bool(title and title in visible_texts_group_titles())
