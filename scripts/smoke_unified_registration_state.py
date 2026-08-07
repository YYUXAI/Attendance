from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

from repositories import registration_sessions_repo  # noqa: E402


def _consume_child() -> int:
    tg_id = int(os.environ["ATTENDANCE_SMOKE_TG_ID"])
    token = os.environ["ATTENDANCE_SMOKE_TOKEN"]
    consumed = registration_sessions_repo.cancel_preview(
        bot_owner="ux_assistant",
        token=token,
        tg_id=tg_id,
        private_chat_id=tg_id,
        now=datetime.now(timezone.utc),
    )
    print(json.dumps({"consumed": consumed}, sort_keys=True))
    return 0 if consumed else 1


def main() -> int:
    if "--consume-child" in sys.argv:
        return _consume_child()

    now = datetime.now(timezone.utc)
    tg_id = -(8_000_000_000_000_000 + secrets.randbelow(999_999_999_999_999))
    token = secrets.token_urlsafe(24)
    try:
        registration_sessions_repo.begin_session(
            bot_owner="ux_assistant",
            tg_id=tg_id,
            private_chat_id=tg_id,
            now=now,
            inactivity_ttl=timedelta(minutes=15),
            absolute_ttl=timedelta(minutes=30),
        )
        expires_at = registration_sessions_repo.save_preview(
            bot_owner="ux_assistant",
            tg_id=tg_id,
            private_chat_id=tg_id,
            english_name="SYNTHETIC",
            employee_id="SYNTHETIC",
            token=token,
            now=now,
            inactivity_ttl=timedelta(minutes=15),
        )
        child_env = os.environ.copy()
        child_env["ATTENDANCE_SMOKE_TG_ID"] = str(tg_id)
        child_env["ATTENDANCE_SMOKE_TOKEN"] = token
        child = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--consume-child"],
            cwd=ROOT,
            env=child_env,
            check=False,
            capture_output=True,
            text=True,
        )
        child_payload = json.loads(child.stdout or "{}")
        second_consume = registration_sessions_repo.cancel_preview(
            bot_owner="ux_assistant",
            token=token,
            tg_id=tg_id,
            private_chat_id=tg_id,
            now=datetime.now(timezone.utc),
        )
        active_after = registration_sessions_repo.is_active(
            bot_owner="ux_assistant",
            tg_id=tg_id,
            private_chat_id=tg_id,
            now=datetime.now(timezone.utc),
        )
        passed = bool(
            expires_at
            and child.returncode == 0
            and child_payload.get("consumed") is True
            and second_consume is False
            and active_after is False
        )
        print(
            json.dumps(
                {
                    "cross_process_visible": child_payload.get("consumed") is True,
                    "one_time_consume": second_consume is False,
                    "session_cleared": active_after is False,
                    "passed": passed,
                },
                sort_keys=True,
            )
        )
        return 0 if passed else 1
    finally:
        registration_sessions_repo.clear_session(
            bot_owner="ux_assistant",
            tg_id=tg_id,
        )


if __name__ == "__main__":
    raise SystemExit(main())
