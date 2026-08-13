from __future__ import annotations

import os
from dataclasses import dataclass

from repositories import attendance_runtime_config_repo


@dataclass(frozen=True)
class GoogleSheetsAltConfig:
    spreadsheet_id: str
    sheet_gid: int | None
    credentials_json: str
    viewer_employee_ids: frozenset[str]
    mirror_from_to: dict[str, str]


def load_google_sheets_alt_config() -> GoogleSheetsAltConfig | None:
    spreadsheet_id = (os.getenv("GOOGLE_SHEETS_ALT_SPREADSHEET_ID") or "").strip()
    if not spreadsheet_id:
        return None
    gid_raw = (os.getenv("GOOGLE_SHEETS_ALT_SHEET_GID") or "").strip()
    sheet_gid: int | None = None
    if gid_raw:
        try:
            sheet_gid = int(gid_raw)
        except ValueError:
            sheet_gid = None
    creds = (
        os.getenv("GOOGLE_SHEETS_ALT_CREDENTIALS_JSON")
        or os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON")
        or ""
    ).strip()
    viewer_ids = attendance_runtime_config_repo.business_fact_set(
        fact_kind="alt_roster_viewer"
    )
    mirror_from_to = attendance_runtime_config_repo.business_fact_map(
        fact_kind="shift_mirror_employee"
    )
    return GoogleSheetsAltConfig(
        spreadsheet_id=spreadsheet_id,
        sheet_gid=sheet_gid,
        credentials_json=creds,
        viewer_employee_ids=viewer_ids,
        mirror_from_to=mirror_from_to,
    )
