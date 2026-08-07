from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import urlencode

from infra.telegram_webapp_auth import validate_telegram_init_data


def _signed_init_data(*, token: str, auth_date: int) -> str:
    fields = {
        "auth_date": str(auth_date),
        "query_id": "query-test",
        "user": json.dumps({"id": 42}, separators=(",", ":")),
    }
    data_check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


def test_init_data_requires_fresh_auth_date() -> None:
    token = "test-token-placeholder"
    now = 1_800_000_000

    assert validate_telegram_init_data(
        init_data=_signed_init_data(token=token, auth_date=now - 30),
        bot_token=token,
        now_epoch=now,
        max_age_seconds=300,
    ) is not None
    assert validate_telegram_init_data(
        init_data=_signed_init_data(token=token, auth_date=now - 301),
        bot_token=token,
        now_epoch=now,
        max_age_seconds=300,
    ) is None
    assert validate_telegram_init_data(
        init_data=_signed_init_data(token=token, auth_date=now + 31),
        bot_token=token,
        now_epoch=now,
        max_age_seconds=300,
    ) is None


def test_init_data_without_auth_date_is_rejected() -> None:
    token = "test-token-placeholder"
    raw = _signed_init_data(token=token, auth_date=1_800_000_000).replace("auth_date=1800000000&", "")

    assert validate_telegram_init_data(
        init_data=raw,
        bot_token=token,
        now_epoch=1_800_000_000,
    ) is None


def test_init_data_signed_by_another_bot_token_is_rejected() -> None:
    now = 1_800_000_000
    init_data = _signed_init_data(token="legacy-bot-token", auth_date=now)

    assert validate_telegram_init_data(
        init_data=init_data,
        bot_token="ux-assistant-bot-token",
        now_epoch=now,
    ) is None
