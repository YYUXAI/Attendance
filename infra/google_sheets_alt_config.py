from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GoogleSheetsAltConfig:
    spreadsheet_id: str
    sheet_gid: int | None
    credentials_json: str
    viewer_employee_ids: frozenset[str]
    mirror_from_to: dict[str, str]
    attendance_chat_id: int | None


def _parse_csv_ids(raw: str) -> frozenset[str]:
    out: set[str] = set()
    for part in (raw or "").replace("，", ",").split(","):
        p = part.strip()
        if p:
            out.add(p)
    return frozenset(out)


def _parse_mirror_map(raw: str) -> dict[str, str]:
    """
    格式：7882:99999,7882:88888
    表示目标工号复制源工号的班表（仅复制 value 侧）。
    """
    out: dict[str, str] = {}
    for part in (raw or "").replace("，", ",").split(","):
        p = part.strip()
        if not p or ":" not in p:
            continue
        src, dst = p.split(":", 1)
        src, dst = src.strip(), dst.strip()
        if src and dst:
            out[dst] = src
    return out


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
        or "secrets/google_service_account.json"
    ).strip()
    if creds and not os.path.isabs(creds):
        root = Path(__file__).resolve().parents[1]
        creds = str((root / creds).resolve())
    viewer_ids = _parse_csv_ids(
        os.getenv("GOOGLE_SHEETS_ALT_VIEWER_EMPLOYEE_IDS")
        or os.getenv("GOOGLE_SHEETS_ALT_EMPLOYEE_IDS")
        or ""
    )
    mirror_from_to = _parse_mirror_map(os.getenv("GOOGLE_SHEETS_MIRROR_EMPLOYEE_IDS") or "")
    chat_raw = (os.getenv("GOOGLE_SHEETS_ALT_ATTENDANCE_CHAT_ID") or "").strip()
    attendance_chat_id: int | None = None
    if chat_raw:
        try:
            attendance_chat_id = int(chat_raw)
        except ValueError:
            attendance_chat_id = None
    return GoogleSheetsAltConfig(
        spreadsheet_id=spreadsheet_id,
        sheet_gid=sheet_gid,
        credentials_json=creds,
        viewer_employee_ids=viewer_ids,
        mirror_from_to=mirror_from_to,
        attendance_chat_id=attendance_chat_id,
    )
