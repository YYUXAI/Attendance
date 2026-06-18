from __future__ import annotations

import time

_TTL_SECONDS = 900
_pending: dict[int, tuple[str, float]] = {}


def set_pending_checkin_action(*, tg_id: int, action: str) -> None:
    """记录用户刚点的「签到/签退」，供下一次发图打卡使用。"""
    if action not in {"签到", "签退"}:
        return
    _pending[int(tg_id)] = (action, time.time() + _TTL_SECONDS)


def pop_pending_checkin_action(*, tg_id: int) -> str | None:
    item = _pending.get(int(tg_id))
    if not item:
        return None
    action, exp = item
    if exp <= time.time():
        _pending.pop(int(tg_id), None)
        return None
    _pending.pop(int(tg_id), None)
    return action
