from __future__ import annotations

import csv
import io

from services.group_attendance_summary_service import AttendanceSummaryRow, encode_csv


def test_scheduled_attendance_csv_neutralizes_formula_capable_cells() -> None:
    dangerous = ("=HYPERLINK(\"https://example.invalid\")", "+cmd", "-2+3", "@SUM(A1)", " \t=cmd")
    rows = [
        AttendanceSummaryRow(
            chat_id=-1001,
            group_name=value,
            employee_id=value,
            english_name=value,
            shift_time_range=value,
            first_clock_local=value,
            last_clock_local=value,
            leave_time_display=value,
            status=value,
        )
        for value in dangerous
    ]

    decoded = list(csv.reader(io.StringIO(encode_csv(rows=rows).decode("utf-8-sig"))))

    assert decoded[0] == ["群名", "工号", "英文名", "班次", "上班时间", "下班时间", "离岗时间", "状态"]
    assert decoded[1:] == [[f"'{value}"] * 8 for value in dangerous]
