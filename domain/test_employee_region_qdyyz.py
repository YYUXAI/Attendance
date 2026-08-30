from __future__ import annotations

from datetime import date, time

from domain.employee_region import (
    local_shift_wall_times_to_beijing,
    normalize_region_code,
    timezone_for_region,
)


def test_qdyyz_region_codes_map_to_local_timezones() -> None:
    assert normalize_region_code("T") == "T"
    assert normalize_region_code("F") == "F"
    assert normalize_region_code("D") == "D"
    assert normalize_region_code("S") == "S"
    assert timezone_for_region("T") == "Asia/Bangkok"
    assert timezone_for_region("F") == "Asia/Manila"
    assert timezone_for_region("D") == "Asia/Dubai"
    assert timezone_for_region("S") == "Asia/Colombo"
    # 旧码仍可用
    assert normalize_region_code("TH") == "TH"
    assert normalize_region_code("F-KJY") == "F-KJY"
    assert normalize_region_code("DB") == "DB"
    assert normalize_region_code("PH-K") == "F"


def test_dubai_local_shift_converts_to_beijing_wall_clock() -> None:
    # 迪拜 UTC+4，北京 UTC+8 → +4 小时
    cin, cout = local_shift_wall_times_to_beijing(
        day=date(2026, 9, 1),
        checkin=time(10, 0),
        checkout=time(19, 0),
        local_tz_name="Asia/Dubai",
    )
    assert cin == time(14, 0)
    assert cout == time(23, 0)


def test_bangkok_overnight_shift_converts_to_beijing() -> None:
    # 曼谷 UTC+7 → 北京 +1
    cin, cout = local_shift_wall_times_to_beijing(
        day=date(2026, 9, 1),
        checkin=time(17, 0),
        checkout=time(2, 0),
        local_tz_name="Asia/Bangkok",
    )
    assert cin == time(18, 0)
    assert cout == time(3, 0)


def test_manila_same_offset_as_beijing() -> None:
    cin, cout = local_shift_wall_times_to_beijing(
        day=date(2026, 9, 1),
        checkin=time(12, 0),
        checkout=time(21, 0),
        local_tz_name="Asia/Manila",
    )
    assert cin == time(12, 0)
    assert cout == time(21, 0)
