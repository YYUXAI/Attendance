from __future__ import annotations

import os


ATTENDANCE_BOT_OWNERS = frozenset({"legacy_attendance", "ux_assistant"})


def load_attendance_bot_owner(*, require_unified: bool = False) -> str:
    configured = os.getenv("ATTENDANCE_BOT_OWNER")
    owner = (configured or "legacy_attendance").strip()
    if owner not in ATTENDANCE_BOT_OWNERS:
        raise RuntimeError(
            "ATTENDANCE_BOT_OWNER must be one of: legacy_attendance, ux_assistant"
        )
    if require_unified and owner != "ux_assistant":
        raise RuntimeError(
            "Attendance unified webhook requires ATTENDANCE_BOT_OWNER=ux_assistant"
        )
    return owner
