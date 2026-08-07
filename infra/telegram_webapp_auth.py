from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any
from urllib.parse import parse_qsl


def validate_telegram_init_data(
    *,
    init_data: str,
    bot_token: str,
    now_epoch: int | None = None,
    max_age_seconds: int | None = None,
    future_skew_seconds: int = 30,
) -> dict[str, Any] | None:
    """校验 Telegram WebApp initData，成功返回解析后的字段（含 user）。"""
    raw = (init_data or "").strip()
    if not raw or not bot_token:
        return None
    pairs = dict(parse_qsl(raw, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        return None
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        return None
    try:
        auth_date = int(pairs.get("auth_date") or "")
    except (TypeError, ValueError):
        return None
    now = int(time.time()) if now_epoch is None else int(now_epoch)
    max_age = _max_age_seconds() if max_age_seconds is None else int(max_age_seconds)
    if auth_date > now + max(0, int(future_skew_seconds)):
        return None
    if auth_date < now - max(1, max_age):
        return None
    out: dict[str, Any] = dict(pairs)
    if "user" in out and isinstance(out["user"], str):
        try:
            out["user"] = json.loads(out["user"])
        except json.JSONDecodeError:
            return None
    return out


def _max_age_seconds() -> int:
    raw = (os.getenv("SHIFT_WEB_INIT_DATA_MAX_AGE_SECONDS") or "300").strip()
    try:
        value = int(raw)
    except ValueError:
        value = 300
    return max(60, min(value, 3600))


def tg_user_id_from_init_data(parsed: dict[str, Any]) -> int | None:
    user = parsed.get("user")
    if isinstance(user, dict) and user.get("id") is not None:
        try:
            return int(user["id"])
        except (TypeError, ValueError):
            return None
    return None
