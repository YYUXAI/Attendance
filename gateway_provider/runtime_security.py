from __future__ import annotations

from collections.abc import Mapping


_TELEGRAM_OWNER_CREDENTIAL_NAMES = frozenset(
    {
        "BOT_TOKEN",
        "SHIFT_WEB_TELEGRAM_BOT_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "TG_BOT_TOKEN",
    }
)


def assert_no_telegram_owner_credentials(
    environment: Mapping[str, str],
) -> None:
    present = sorted(
        name
        for name in _TELEGRAM_OWNER_CREDENTIAL_NAMES
        if (environment.get(name) or "").strip()
    )
    if present:
        raise RuntimeError(
            "Attendance Provider must not receive Telegram owner credentials: "
            + ", ".join(present)
        )
