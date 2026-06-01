from __future__ import annotations

import os
import secrets
import time

_sessions: dict[str, tuple[int, float]] = {}


def _ttl_seconds() -> int:
    raw = (os.getenv("SHIFT_WEB_SESSION_TTL_SECONDS") or "86400").strip()
    try:
        n = int(raw)
    except ValueError:
        n = 86400
    return max(600, min(n, 7 * 86400))


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


def _touch_session(token: str) -> None:
    item = _sessions.get(token)
    if not item:
        return
    tg_id, _ = item
    _sessions[token] = (tg_id, time.time() + _ttl_seconds())


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
    _touch_session(raw)
    return tg_id
