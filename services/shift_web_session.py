from __future__ import annotations

import os
import secrets
import time

_sessions: dict[str, tuple[int, float]] = {}


def _ttl_seconds() -> int:
    raw = (os.getenv("SHIFT_WEB_SESSION_TTL_SECONDS") or "900").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 900
    return max(60, min(n, 3600))


def _purge_expired() -> None:
    now = time.time()
    expired = [k for k, (_, exp) in _sessions.items() if exp <= now]
    for k in expired:
        _sessions.pop(k, None)


def create_session(*, tg_id: int) -> str:
    """浏览器直连等场景用；Telegram WebApp 内优先用 initData，可不依赖此 token。"""
    _purge_expired()
    token = secrets.token_urlsafe(24)
    _sessions[token] = (int(tg_id), time.time() + _ttl_seconds())
    return token


def verify_session(token: str) -> int | None:
    _purge_expired()
    raw = (token or "").strip()
    if not raw:
        return None
    item = _sessions.get(raw)
    if not item:
        return None
    tg_id, exp = item
    if exp <= time.time():
        _sessions.pop(raw, None)
        return None
    return tg_id
