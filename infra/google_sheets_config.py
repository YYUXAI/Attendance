from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GoogleSheetsConfig:
    enabled: bool
    spreadsheet_id: str
    sheet_gid: int | None
    credentials_json: str
    sync_interval_seconds: int
    year_month: str


def load_google_sheets_config() -> GoogleSheetsConfig:
    enabled = os.getenv("GOOGLE_SHEETS_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    spreadsheet_id = (os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID") or "").strip()
    gid_raw = (os.getenv("GOOGLE_SHEETS_SHEET_GID") or "").strip()
    sheet_gid: int | None = None
    if gid_raw:
        try:
            sheet_gid = int(gid_raw)
        except ValueError:
            sheet_gid = None
    creds = (os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON") or "secrets/google_service_account.json").strip()
    if creds and not os.path.isabs(creds):
        root = Path(__file__).resolve().parents[1]
        creds = str((root / creds).resolve())
    try:
        interval = int(os.getenv("GOOGLE_SHEETS_SYNC_INTERVAL_SECONDS") or "3600")
    except ValueError:
        interval = 3600
    year_month = (os.getenv("GOOGLE_SHEETS_YEAR_MONTH") or "").strip()
    return GoogleSheetsConfig(
        enabled=enabled,
        spreadsheet_id=spreadsheet_id,
        sheet_gid=sheet_gid,
        credentials_json=creds,
        sync_interval_seconds=max(60, interval),
        year_month=year_month,
    )
