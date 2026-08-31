from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from services.attendance_export_service import normalize_export_status
from services.group_attendance_summary_service import AttendanceSummaryRow

_TZ = ZoneInfo("Asia/Shanghai")
_WORK = date(2026, 8, 31)
_BEFORE_CHECKOUT = datetime(2026, 8, 31, 16, 0, tzinfo=_TZ)
_AFTER_CHECKOUT = datetime(2026, 8, 31, 19, 0, tzinfo=_TZ)


def _row(
    *,
    status: str,
    first: str = "",
    last: str = "",
    shift_time_range: str = "09:00 - 18:00",
    work_date: date | None = _WORK,
) -> AttendanceSummaryRow:
    return AttendanceSummaryRow(
        chat_id=-1,
        group_name="g",
        employee_id="1",
        english_name="A",
        shift_time_range=shift_time_range,
        first_clock_local=first,
        last_clock_local=last,
        leave_time_display="",
        status=status,
        work_date=work_date,
    )


def test_normalize_export_checkin_only_before_checkout_is_normal() -> None:
    row = _row(status="缺卡", first="12:31:00", last="")
    assert normalize_export_status(row, on_leave=False, now=_BEFORE_CHECKOUT) == "正常"


def test_normalize_export_checkin_only_after_checkout_is_missing() -> None:
    row = _row(status="缺卡", first="12:31:00", last="")
    assert normalize_export_status(row, on_leave=False, now=_AFTER_CHECKOUT) == "缺卡"


def test_normalize_export_checkin_only_past_day_is_missing() -> None:
    row = _row(status="缺卡", first="12:31:00", last="", work_date=date(2026, 8, 30))
    assert normalize_export_status(row, on_leave=False, now=_AFTER_CHECKOUT) == "缺卡"


def test_normalize_export_overnight_checkin_only_before_next_morning() -> None:
    row = _row(
        status="缺卡",
        first="22:10:00",
        last="",
        shift_time_range="22:00 - 06:00",
        work_date=date(2026, 8, 30),
    )
    now = datetime(2026, 8, 31, 3, 0, tzinfo=_TZ)
    assert normalize_export_status(row, on_leave=False, now=now) == "正常"


def test_normalize_export_overnight_checkin_only_after_next_morning() -> None:
    row = _row(
        status="缺卡",
        first="22:10:00",
        last="",
        shift_time_range="22:00 - 06:00",
        work_date=date(2026, 8, 30),
    )
    now = datetime(2026, 8, 31, 7, 0, tzinfo=_TZ)
    assert normalize_export_status(row, on_leave=False, now=now) == "缺卡"


def test_normalize_export_still_missing_punch_when_no_checkin() -> None:
    row = _row(status="缺卡", first="", last="01:06:00")
    assert normalize_export_status(row, on_leave=False, now=_AFTER_CHECKOUT) == "缺卡"


def test_export_grid_appends_status_note() -> None:
    from datetime import date

    from services.attendance_export_service import (
        AttendanceExportOverview,
        EmployeeExportPivot,
        build_attendance_export_grid,
    )

    work_date = date(2026, 8, 31)
    pivot = [
        EmployeeExportPivot(
            group_name="QDYYZ 打卡报备群",
            english_name="Chapkups",
            employee_id="58643",
            daily_status={work_date: "正常"},
            daily_note={work_date: "未迟到 虚拟机无法登记 群里已报备"},
        )
    ]
    overview = AttendanceExportOverview(
        expected_count=1,
        actual_count=1,
        monthly_rest=0,
        absent=0,
        late=0,
        early=0,
        missed_punch=0,
        leave=0,
    )
    grid = build_attendance_export_grid(
        pivot=pivot,
        dates=[work_date],
        overview=overview,
        range_label="今日",
    )
    data_rows = [row for row in grid if row and str(row[0]) == "QDYYZ 打卡报备群"]
    assert data_rows, grid
    assert data_rows[0][3] == "正常（未迟到 虚拟机无法登记 群里已报备）"
