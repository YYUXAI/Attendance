"""仅指定考勤群要求 PC 端截图（手机端浏览器 / Telegram 拒绝打卡）。"""
from __future__ import annotations

import os


def pc_only_checkin_chat_ids() -> frozenset[int]:
    raw = (os.getenv("CHECKIN_PC_ONLY_CHAT_IDS") or "-1003200046237").strip()
    if not raw:
        return frozenset()
    out: set[int] = set()
    for part in raw.replace("，", ",").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.add(int(p))
        except ValueError:
            continue
    return frozenset(out)


def requires_pc_screenshot(*, chat_id: int | None) -> bool:
    if chat_id is None:
        return False
    return int(chat_id) in pc_only_checkin_chat_ids()
