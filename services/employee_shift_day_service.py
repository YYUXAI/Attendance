"""按日班表（employee_shift_calendar）解析每人每天的实际上下班时间。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time

from domain.world_cup_shift_codes import default_shift_catalog, lookup_shift
from repositories import employee_shift_calendar_repo


@dataclass(frozen=True)
class DailyShift:
    shift_code: str
    shift_time_range: str
    checkin: time
    checkout: time
    is_rest: bool
    cell_kind: str = ""


def _catalog():
    return default_shift_catalog()


def daily_shift_from_calendar_row(
    *,
    shift_code: str,
    cell_kind: str,
) -> DailyShift | None:
    kind = (cell_kind or "").strip().lower()
    if kind == "rest":
        return DailyShift(
            shift_code="",
            shift_time_range="",
            checkin=time(0, 0),
            checkout=time(0, 0),
            is_rest=True,
            cell_kind=kind,
        )
    code = (shift_code or "").strip().upper()
    if not code:
        return None
    shift = lookup_shift(code, _catalog())
    if not shift:
        return None
    return DailyShift(
        shift_code=code,
        shift_time_range=shift.time_range_display,
        checkin=shift.checkin,
        checkout=shift.checkout,
        is_rest=False,
        cell_kind=kind or "shift",
    )


def load_calendar_map(
    *,
    year_month: str,
    employee_ids: list[str] | None = None,
) -> dict[tuple[str, date], DailyShift]:
    rows = employee_shift_calendar_repo.list_for_month(
        year_month=year_month,
        employee_ids=employee_ids,
    )
    out: dict[tuple[str, date], DailyShift] = {}
    for row in rows:
        ds = daily_shift_from_calendar_row(
            shift_code=row.shift_code,
            cell_kind=row.cell_kind,
        )
        if ds is None:
            continue
        out[(str(row.employee_id), row.work_date)] = ds
    return out


def get_daily_shift(
    *,
    employee_id: str,
    work_date: date,
    year_month: str | None = None,
    calendar_map: dict[tuple[str, date], DailyShift] | None = None,
) -> DailyShift | None:
    ym = year_month or work_date.strftime("%Y-%m")
    if calendar_map is not None:
        return calendar_map.get((str(employee_id), work_date))
    row = employee_shift_calendar_repo.get_by_work_date(
        year_month=ym,
        employee_id=str(employee_id),
        work_date=work_date,
    )
    if not row:
        return None
    return daily_shift_from_calendar_row(
        shift_code=row.shift_code,
        cell_kind=row.cell_kind,
    )
