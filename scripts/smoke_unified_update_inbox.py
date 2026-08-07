from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

import httpx
from dotenv import dotenv_values, load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

from infra.db import get_cursor


def main() -> int:
    env = dotenv_values(ROOT / ".env")
    secret = str(
        env.get("WEBHOOK_SECRET_TOKEN")
        or env.get("UNIFIED_BOT_DOWNSTREAM_SECRET_TOKEN")
        or ""
    ).strip()
    if not secret:
        raise RuntimeError("unified webhook secret is not configured")
    update_id = -(1_000_000_000 + secrets.randbelow(1_000_000_000))
    try:
        headers = {"x-omniai-unified-bot-secret-token": secret}
        first = httpx.post(
            "http://127.0.0.1:8001/webhook",
            headers=headers,
            json={"update_id": update_id},
            timeout=10,
        )
        second = httpx.post(
            "http://127.0.0.1:8001/webhook",
            headers=headers,
            json={"update_id": update_id},
            timeout=10,
        )
        first_payload = first.json() if first.status_code == 200 else {}
        second_payload = second.json() if second.status_code == 200 else {}
        passed = bool(
            first.status_code == 200
            and first_payload.get("ok") is True
            and first_payload.get("duplicate") is not True
            and second.status_code == 200
            and second_payload.get("duplicate") is True
        )
        print(
            json.dumps(
                {
                    "first_processed": first.status_code == 200,
                    "replay_skipped": second_payload.get("duplicate") is True,
                    "passed": passed,
                },
                sort_keys=True,
            )
        )
        return 0 if passed else 1
    finally:
        with get_cursor() as cur:
            cur.execute(
                """
                DELETE FROM public.attendance_telegram_update_inbox
                WHERE bot_owner = 'ux_assistant' AND update_id = %s
                """,
                (update_id,),
            )


if __name__ == "__main__":
    raise SystemExit(main())
