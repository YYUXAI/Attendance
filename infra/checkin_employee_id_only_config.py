"""可选：标准 time.is 打卡仅校验工号（无文件夹）。工号打卡群请用 remote_diff。"""
from __future__ import annotations

import os

_DEFAULT_EMPLOYEE_ID_ONLY_CHAT_IDS: frozenset[int] = frozenset()
_DEFAULT_EMPLOYEE_ID_ONLY_TITLES: frozenset[str] = frozenset()


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
    out: set[str] = set()
    for part in (raw or "").replace("，", ",").split(","):
        p = part.strip()
        if p:
            out.add(p)
    return frozenset(out)


def employee_id_only_chat_ids() -> frozenset[int]:
    raw = (os.getenv("CHECKIN_EMPLOYEE_ID_ONLY_CHAT_IDS") or "").strip()
    if not raw:
        return _DEFAULT_EMPLOYEE_ID_ONLY_CHAT_IDS
    return _parse_int_set(raw)


def employee_id_only_group_titles() -> frozenset[str]:
    raw = (os.getenv("CHECKIN_EMPLOYEE_ID_ONLY_GROUP_TITLES") or "").strip()
    if not raw:
        return _DEFAULT_EMPLOYEE_ID_ONLY_TITLES
    return _parse_str_set(raw)


def requires_employee_id_only_checkin(
    *,
    chat_id: int | None,
    chat_title: str | None = None,
) -> bool:
    """是否为「仅工号校验」群（标准 time.is 流程，跳过姓名识别/比对）。"""
    if chat_id is not None and int(chat_id) in employee_id_only_chat_ids():
        return True
    title = (chat_title or "").strip()
    titles = employee_id_only_group_titles()
    return bool(title and titles and title in titles)
