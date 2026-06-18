from __future__ import annotations

import secrets
import time

_TTL_SECONDS = 600
_sessions: dict[str, tuple[int, str, float]] = {}


def create_session(*, tg_id: int, action: str) -> str:
    if action not in {"签到", "签退"}:
        raise ValueError(f"invalid action: {action}")
    _purge_expired()
    token = secrets.token_urlsafe(24)
    _sessions[token] = (int(tg_id), action, time.time() + _TTL_SECONDS)
    return token


def verify_session(token: str) -> tuple[int, str] | None:
    _purge_expired()
    raw = (token or "").strip()
    if not raw:
        return None
    item = _sessions.get(raw)
    if not item:
        return None
    tg_id, action, exp = item
    if exp <= time.time():
        _sessions.pop(raw, None)
        return None
    return tg_id, action


def _purge_expired() -> None:
    now = time.time()
    expired = [k for k, (_, _, exp) in _sessions.items() if exp <= now]
    for k in expired:
        _sessions.pop(k, None)
