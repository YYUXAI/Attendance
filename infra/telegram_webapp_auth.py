from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from urllib.parse import parse_qsl


def validate_telegram_init_data(*, init_data: str, bot_token: str) -> dict[str, Any] | None:
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
    out: dict[str, Any] = dict(pairs)
    if "user" in out and isinstance(out["user"], str):
        try:
            out["user"] = json.loads(out["user"])
        except json.JSONDecodeError:
            return None
    return out


def tg_user_id_from_init_data(parsed: dict[str, Any]) -> int | None:
    user = parsed.get("user")
    if isinstance(user, dict) and user.get("id") is not None:
        try:
            return int(user["id"])
        except (TypeError, ValueError):
            return None
    return None
