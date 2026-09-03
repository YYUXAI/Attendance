from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from domain.world_cup_shift_codes import default_shift_catalog, lookup_shift
from infra.google_sheets_config import GoogleSheetsConfig
from services.google_sheets_shift_sync_service import (
    _extract_shift_code,
    main_export_roster_employee_ids,
    parse_shift_matrix,
    sync_shifts_from_google_sheets,
)


def test_extract_shift_code_supports_single_letter_and_w_prefix() -> None:
    assert _extract_shift_code("WG") == "WG"
    assert _extract_shift_code("G") == "G"
    assert _extract_shift_code("Q") == "Q"
    assert _extract_shift_code("▲") == ""
    assert _extract_shift_code("月休") == ""


def test_single_letter_g_differs_from_wg() -> None:
    catalog = default_shift_catalog()
    g = lookup_shift("G", catalog)
    wg = lookup_shift("WG", catalog)
    assert g is not None and wg is not None
    assert g.time_range_display == "13:00~22:00"
    assert wg.time_range_display == "13:00~01:00"


def test_parse_shift_matrix_reads_single_letter_cells() -> None:
    rows = [
        ["7月排班表"],
        ["", "", "", "", "", "", "G", "13:00-22:00"],
        ["序号", "职位", "名字", "工号", "中文名", "入职时间", "一", "二", "三"],
        ["", "", "", "", "", "", "1", "2", "3"],
        ["UX设计组"],
        ["1", "UX设计师", "NAYXUA", "74306", "朵拉", "2024-1-1", "▲", "WG", "G"],
        ["夏荷组"],
        ["2", "设计", "MAL", "31485", "xx", "2024-1-1", "G", "G", "G"],
    ]
    _, employees = parse_shift_matrix(rows, year_month="2026-07")
    assert len(employees) == 2
    by_id = {e.employee_id: e for e in employees}
    assert by_id["74306"].sheet_team_group == "UX设计组"
    assert by_id["31485"].sheet_team_group == "夏荷组"
    assert main_export_roster_employee_ids(employees) == ["74306"]


def test_sync_preserves_main_roster_when_primary_tab_missing() -> None:
    cfg = GoogleSheetsConfig(
        enabled=True,
        spreadsheet_id="sheet-2026-09",
        sheet_gid=None,
        credentials_json="{}",
        sync_interval_seconds=3600,
        year_month="2026-09",
    )
    alt_cfg = SimpleNamespace(
        spreadsheet_id="alt-sheet",
        sheet_gid=1,
        credentials_json="{}",
        mirror_from_to={},
    )

    with (
        patch(
            "services.google_sheets_shift_sync_service.fetch_shift_matrix_sheet",
            side_effect=ValueError("未找到 2026-09 班表 tab"),
        ),
        patch(
            "services.google_sheets_shift_sync_service.load_google_sheets_alt_config",
            return_value=alt_cfg,
        ),
        patch(
            "services.google_sheets_shift_sync_service._sync_alt_sheet_employees",
            return_value=(16, 480, "alt-tab", ["10001"]),
        ),
        patch(
            "services.google_sheets_shift_sync_service.load_test_group_google_config",
            return_value=SimpleNamespace(enabled=False, shift_spreadsheet_id=""),
        ),
        patch("services.google_sheets_shift_sync_service.employee_shift_config_repo.ensure_table"),
        patch("services.google_sheets_shift_sync_service.employee_shift_calendar_repo.ensure_table"),
        patch("services.google_sheets_shift_sync_service.employee_shift_roster_repo.ensure_table"),
        patch(
            "services.google_sheets_shift_sync_service.employee_shift_roster_repo.list_roster",
            return_value=["74306", "59242"],
        ) as list_roster,
        patch(
            "services.google_sheets_shift_sync_service.employee_shift_roster_repo.set_roster",
        ) as set_roster,
        patch(
            "services.google_sheets_shift_sync_service._upsert_employees",
        ) as upsert_employees,
        patch(
            "services.google_sheets_shift_sync_service.employee_shift_config_repo.delete_not_in",
        ),
        patch(
            "services.google_sheets_shift_sync_service.employee_shift_calendar_repo.delete_not_in",
        ) as delete_calendar,
    ):
        result = sync_shifts_from_google_sheets(cfg=cfg, year_month="2026-09")

    assert result.ok is True
    set_roster.assert_not_called()
    upsert_employees.assert_not_called()
    list_roster.assert_called_once_with(year_month="2026-09", source="main")
    delete_calendar.assert_called_once()
    keep_ids = set(delete_calendar.call_args.kwargs["employee_ids"])
    assert {"74306", "59242", "10001"} <= keep_ids
