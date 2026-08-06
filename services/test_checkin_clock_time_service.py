from __future__ import annotations

from datetime import datetime, timezone

from domain.checkin_image_extraction import CheckinImageExtraction
from services.checkin_clock_time_service import evaluate_clock_time


def test_evaluate_clock_time_fixes_12h_skew() -> None:
    # 智谱误读 23:05 为 11:05 时，应自动 ±12 校正
    now = datetime(2026, 7, 23, 15, 5, 30, tzinfo=timezone.utc)  # 23:05 Shanghai
    extraction = CheckinImageExtraction(
        display_name="Karina",
        username_hint="Y_UX_Karina",
        clock_time="11:05",
        clock_date="07-23",
        timezone_iana="GMT+8",
        confidence=1.0,
    )
    status, clock_utc = evaluate_clock_time(
        extraction=extraction,
        shift_timezone="Asia/Shanghai",
        now_utc=now,
        max_skew_minutes=30,
    )
    assert status == "ok"
    assert clock_utc is not None
    assert clock_utc.astimezone(timezone.utc).hour == 15
