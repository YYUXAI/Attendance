from datetime import datetime, time, timezone
from types import SimpleNamespace

from repositories.profile_repo import EmployeeShiftConfigLite
from services import profile_service


def test_profile_month_stats_use_the_attendance_group_timezone(monkeypatch) -> None:
    monkeypatch.setattr(
        profile_service.profile_repo,
        "get_registration_profile_by_tg_id",
        lambda **_kwargs: SimpleNamespace(english_name="Tester", employee_id="E-001"),
    )
    monkeypatch.setattr(
        profile_service.profile_repo,
        "get_employee_shift_config_for_month",
        lambda **_kwargs: EmployeeShiftConfigLite(
            shift_checkin_time=time(9),
            shift_checkout_time=time(18),
            shift_time_range="09:00~18:00",
            monthly_rest_days="",
        ),
    )
    monkeypatch.setattr(
        profile_service.clock_records_repo,
        "get_latest_chat_id_for_employee",
        lambda **_kwargs: 1001,
    )
    monkeypatch.setattr(
        profile_service,
        "_timezone_for_attendance_group",
        lambda **_kwargs: "Asia/Bangkok",
    )
    monkeypatch.setattr(profile_service, "load_calendar_map", lambda **_kwargs: {})
    monkeypatch.setattr(
        profile_service,
        "_day_schedule_from_calendar",
        lambda **_kwargs: (None, None, None, None),
    )
    observed: dict[str, object] = {}

    def compute_month_stats(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace(
            attendance_days=0,
            missing_count=0,
            late_count=0,
            early_count=0,
        )

    monkeypatch.setattr(profile_service, "compute_month_stats_for_employee", compute_month_stats)

    result = profile_service.get_my_profile_by_tg_id(
        tg_id=1001,
        now_utc=datetime(2026, 8, 1, 16, 30, tzinfo=timezone.utc),
    )

    assert result.ok is True
    assert observed["tz_name"] == "Asia/Bangkok"
