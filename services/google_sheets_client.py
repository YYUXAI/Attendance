from __future__ import annotations

import logging
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build

log = logging.getLogger(__name__)

_SCOPES = ("https://www.googleapis.com/auth/spreadsheets.readonly",)


def _build_service(*, credentials_json: str):
    creds = service_account.Credentials.from_service_account_file(
        credentials_json,
        scopes=_SCOPES,
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def _sheet_title_by_gid(*, meta: dict[str, Any], sheet_gid: int | None) -> str | None:
    sheets = meta.get("sheets") or []
    if sheet_gid is not None:
        for sh in sheets:
            props = sh.get("properties") or {}
            if int(props.get("sheetId") or -1) == int(sheet_gid):
                return str(props.get("title") or "")
    if sheets:
        props = sheets[0].get("properties") or {}
        return str(props.get("title") or "")
    return None


def fetch_sheet_values(
    *,
    spreadsheet_id: str,
    credentials_json: str,
    sheet_gid: int | None = None,
) -> tuple[str, list[list[str]]]:
    service = _build_service(credentials_json=credentials_json)
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    title = _sheet_title_by_gid(meta=meta, sheet_gid=sheet_gid)
    if not title:
        raise ValueError("无法定位 Google 工作表")
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=title, majorDimension="ROWS")
        .execute()
    )
    raw_rows = result.get("values") or []
    rows = [[str(c) if c is not None else "" for c in row] for row in raw_rows]
    log.info(
        "google_sheets: fetched spreadsheet=%s sheet=%r rows=%s",
        spreadsheet_id,
        title,
        len(rows),
    )
    return title, rows
