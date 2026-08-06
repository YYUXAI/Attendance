from __future__ import annotations

from services.attendance_export_service import normalize_export_status
from services.group_attendance_summary_service import AttendanceSummaryRow


def _row(*, status: str, first: str = "", last: str = "") -> AttendanceSummaryRow:
    return AttendanceSummaryRow(
        chat_id=-1,
        group_name="g",
        employee_id="1",
        english_name="A",
        shift_time_range="",
        first_clock_local=first,
        last_clock_local=last,
        leave_time_display="",
        status=status,
    )


def test_normalize_export_checkin_only_not_missing_punch() -> None:
    row = _row(status="缺卡", first="12:31:00", last="")
    assert normalize_export_status(row, on_leave=False) == "正常"


def test_normalize_export_still_missing_punch_when_no_checkin() -> None:
    row = _row(status="缺卡", first="", last="01:06:00")
    assert normalize_export_status(row, on_leave=False) == "缺卡"
