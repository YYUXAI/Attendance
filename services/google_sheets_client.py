from __future__ import annotations

import logging
import json
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import build

log = logging.getLogger(__name__)

_SCOPES_READONLY = ("https://www.googleapis.com/auth/spreadsheets.readonly",)
_SCOPES_READWRITE = ("https://www.googleapis.com/auth/spreadsheets",)


def _build_service(*, credentials_json: str, write: bool = False):
    scopes = _SCOPES_READWRITE if write else _SCOPES_READONLY
    try:
        value = json.loads(credentials_json)
    except (TypeError, json.JSONDecodeError) as error:
        raise RuntimeError("Google service account binding is invalid") from error
    if not isinstance(value, dict):
        raise RuntimeError("Google service account binding is invalid")
    creds = service_account.Credentials.from_service_account_info(value, scopes=scopes)
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
    sheet_title: str | None = None,
) -> tuple[str, list[list[str]]]:
    service = _build_service(credentials_json=credentials_json)
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    title = sheet_title or _sheet_title_by_gid(meta=meta, sheet_gid=sheet_gid)
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
        "google_sheets: fetched configured sheet rows=%s",
        len(rows),
    )
    return title, rows


def ensure_sheet_tab(
    *,
    spreadsheet_id: str,
    credentials_json: str,
    sheet_title: str,
) -> str:
    """若工作表不存在则新建，返回最终 tab 名称。"""
    want = (sheet_title or "").strip()
    if not want:
        raise ValueError("sheet_title 不能为空")
    service = _build_service(credentials_json=credentials_json, write=True)
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    existing = _sheet_props_by_title(meta=meta, title=want)
    if existing:
        return want
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"addSheet": {"properties": {"title": want}}}]},
    ).execute()
    log.info("google_sheets: created configured sheet tab")
    return want


def replace_sheet_values(
    *,
    spreadsheet_id: str,
    credentials_json: str,
    values: list[list[object]],
    sheet_gid: int | None = None,
    sheet_title: str | None = None,
) -> tuple[str, int]:
    """整表重写指定工作表的单元格值（先 clear 再 update）。"""
    service = _build_service(credentials_json=credentials_json, write=True)
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    title = sheet_title or _sheet_title_by_gid(meta=meta, sheet_gid=sheet_gid)
    if not title:
        raise ValueError("无法定位 Google 工作表")
    service.spreadsheets().values().clear(
        spreadsheetId=spreadsheet_id,
        range=title,
    ).execute()
    row_count = len(values)
    if row_count > 0:
        service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=f"{title}!A1",
            valueInputOption="RAW",
            body={"values": values},
        ).execute()
    log.info(
        "google_sheets: replaced configured sheet rows=%s cols_max=%s",
        row_count,
        max((len(r) for r in values), default=0),
    )
    return title, row_count


def _sheet_props_by_gid(*, meta: dict[str, Any], sheet_gid: int) -> dict[str, Any] | None:
    for sh in meta.get("sheets") or []:
        props = sh.get("properties") or {}
        if int(props.get("sheetId") or -1) == int(sheet_gid):
            return props
    return None


def _sheet_props_by_title(*, meta: dict[str, Any], title: str) -> dict[str, Any] | None:
    want = (title or "").strip()
    for sh in meta.get("sheets") or []:
        props = sh.get("properties") or {}
        if str(props.get("title") or "").strip() == want:
            return props
    return None


def copy_sheet_to_spreadsheet(
    *,
    source_spreadsheet_id: str,
    source_sheet_gid: int,
    destination_spreadsheet_id: str,
    credentials_json: str,
    new_title: str | None = None,
) -> tuple[int, str]:
    """复制工作表到目标表格（保留格式）。"""
    service = _build_service(credentials_json=credentials_json, write=True)
    meta = service.spreadsheets().get(spreadsheetId=source_spreadsheet_id).execute()
    src_props = _sheet_props_by_gid(meta=meta, sheet_gid=source_sheet_gid)
    if not src_props:
        raise ValueError("configured source sheet does not exist")
    src_id = int(src_props["sheetId"])
    resp = (
        service.spreadsheets()
        .sheets()
        .copyTo(
            spreadsheetId=source_spreadsheet_id,
            sheetId=src_id,
            body={"destinationSpreadsheetId": destination_spreadsheet_id},
        )
        .execute()
    )
    dst_id = int(resp["sheetId"])
    dst_title = str(resp.get("title") or "")
    if new_title and new_title.strip() and new_title.strip() != dst_title:
        service.spreadsheets().batchUpdate(
            spreadsheetId=destination_spreadsheet_id,
            body={
                "requests": [
                    {
                        "updateSheetProperties": {
                            "properties": {"sheetId": dst_id, "title": new_title.strip()},
                            "fields": "title",
                        }
                    }
                ]
            },
        ).execute()
        dst_title = new_title.strip()
    log.info("google_sheets: copied configured sheet")
    return dst_id, dst_title


def delete_sheet_by_title(
    *,
    spreadsheet_id: str,
    credentials_json: str,
    sheet_title: str,
) -> bool:
    service = _build_service(credentials_json=credentials_json, write=True)
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    props = _sheet_props_by_title(meta=meta, title=sheet_title)
    if not props:
        return False
    sid = int(props["sheetId"])
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={"requests": [{"deleteSheet": {"sheetId": sid}}]},
    ).execute()
    log.info("google_sheets: deleted configured sheet")
    return True


def delete_sheet_rows(
    *,
    spreadsheet_id: str,
    credentials_json: str,
    sheet_id: int,
    start_index: int,
    end_index: int,
) -> None:
    """删除 [start_index, end_index) 行（0-based）。"""
    if end_index <= start_index:
        return
    service = _build_service(credentials_json=credentials_json, write=True)
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "deleteDimension": {
                        "range": {
                            "sheetId": int(sheet_id),
                            "dimension": "ROWS",
                            "startIndex": int(start_index),
                            "endIndex": int(end_index),
                        }
                    }
                }
            ]
        },
    ).execute()


def sheet_id_for_title(
    *,
    spreadsheet_id: str,
    credentials_json: str,
    sheet_title: str,
) -> int | None:
    service = _build_service(credentials_json=credentials_json, write=True)
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    return _sheet_id_by_title(meta=meta, title=sheet_title)


def copy_row_format(
    *,
    spreadsheet_id: str,
    credentials_json: str,
    sheet_id: int,
    source_row_index: int,
    dest_row_index: int,
    start_col: int = 0,
    end_col: int = 40,
) -> None:
    """复制整行单元格格式（背景色、边框等，不含数值）。"""
    if source_row_index == dest_row_index:
        return
    service = _build_service(credentials_json=credentials_json, write=True)
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "copyPaste": {
                        "source": {
                            "sheetId": int(sheet_id),
                            "startRowIndex": int(source_row_index),
                            "endRowIndex": int(source_row_index) + 1,
                            "startColumnIndex": int(start_col),
                            "endColumnIndex": int(end_col),
                        },
                        "destination": {
                            "sheetId": int(sheet_id),
                            "startRowIndex": int(dest_row_index),
                            "endRowIndex": int(dest_row_index) + 1,
                            "startColumnIndex": int(start_col),
                            "endColumnIndex": int(end_col),
                        },
                        "pasteType": "PASTE_FORMAT",
                        "pasteOrientation": "NORMAL",
                    }
                }
            ]
        },
    ).execute()


def update_sheet_range(
    *,
    spreadsheet_id: str,
    credentials_json: str,
    range_a1: str,
    values: list[list[object]],
) -> None:
    service = _build_service(credentials_json=credentials_json, write=True)
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=range_a1,
        valueInputOption="RAW",
        body={"values": values},
    ).execute()


def _sheet_id_by_title(*, meta: dict[str, Any], title: str) -> int | None:
    props = _sheet_props_by_title(meta=meta, title=title)
    if not props:
        return None
    return int(props["sheetId"])


def apply_cell_backgrounds(
    *,
    spreadsheet_id: str,
    credentials_json: str,
    sheet_id: int,
    cells: list[tuple[int, int]],
    red: float = 1.0,
    green: float = 1.0,
    blue: float = 0.0,
) -> None:
    """对指定单元格（0-based row/col）设置背景色。"""
    if not cells:
        return
    service = _build_service(credentials_json=credentials_json, write=True)
    requests = []
    for row_idx, col_idx in cells:
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": int(sheet_id),
                        "startRowIndex": int(row_idx),
                        "endRowIndex": int(row_idx) + 1,
                        "startColumnIndex": int(col_idx),
                        "endColumnIndex": int(col_idx) + 1,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": {"red": red, "green": green, "blue": blue},
                        }
                    },
                    "fields": "userEnteredFormat.backgroundColor",
                }
            }
        )
    for i in range(0, len(requests), 100):
        service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests[i : i + 100]},
        ).execute()


def reset_sheet_background(
    *,
    spreadsheet_id: str,
    credentials_json: str,
    sheet_id: int,
    row_count: int,
    col_count: int,
) -> None:
    """整表重置为白底（避免旧标黄残留）。"""
    if row_count <= 0 or col_count <= 0:
        return
    service = _build_service(credentials_json=credentials_json, write=True)
    service.spreadsheets().batchUpdate(
        spreadsheetId=spreadsheet_id,
        body={
            "requests": [
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": int(sheet_id),
                            "startRowIndex": 0,
                            "endRowIndex": int(row_count),
                            "startColumnIndex": 0,
                            "endColumnIndex": int(col_count),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                            }
                        },
                        "fields": "userEnteredFormat.backgroundColor",
                    }
                }
            ]
        },
    ).execute()


def write_attendance_export_to_sheet(
    *,
    spreadsheet_id: str,
    credentials_json: str,
    sheet_title: str,
    values: list[list[object]],
    yellow_cells: list[tuple[int, int]] | None = None,
) -> tuple[str, int, int]:
    """写入导出网格到指定 tab，异常单元格标黄；不影响其他工作表。"""
    ensure_sheet_tab(
        spreadsheet_id=spreadsheet_id,
        credentials_json=credentials_json,
        sheet_title=sheet_title,
    )
    title, row_count = replace_sheet_values(
        spreadsheet_id=spreadsheet_id,
        credentials_json=credentials_json,
        values=values,
        sheet_title=sheet_title,
    )
    col_count = max((len(r) for r in values), default=0)
    service = _build_service(credentials_json=credentials_json, write=True)
    meta = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
    sheet_id = _sheet_id_by_title(meta=meta, title=title)
    if sheet_id is None:
        return title, row_count, col_count
    reset_sheet_background(
        spreadsheet_id=spreadsheet_id,
        credentials_json=credentials_json,
        sheet_id=sheet_id,
        row_count=row_count,
        col_count=col_count,
    )
    apply_cell_backgrounds(
        spreadsheet_id=spreadsheet_id,
        credentials_json=credentials_json,
        sheet_id=sheet_id,
        cells=yellow_cells or [],
    )
    return title, row_count, col_count
