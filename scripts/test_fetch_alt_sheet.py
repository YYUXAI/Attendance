#!/usr/bin/env python3
"""测试能否读取 MGZ Google 表指定 gid。"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True)

from google.oauth2 import service_account
from googleapiclient.discovery import build

SPREADSHEET_ID = "1PvfjRqbrSxeuS_3qSxg3nqAr6ngosZyZrC5fqeO-k78"
TARGET_GID = 922677905
CURRENT_GID = 2096557884
CREDS = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON", "secrets/google_service_account.json")
_EMP_RE = re.compile(r"^\d{3,8}$")


def main() -> int:
    creds = service_account.Credentials.from_service_account_file(
        CREDS, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    svc = build("sheets", "v4", credentials=creds, cache_discovery=False)
    meta = svc.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()

    print("=== 文档内所有工作表 ===")
    for sh in meta.get("sheets", []):
        p = sh.get("properties", {})
        print(f"  gid={p.get('sheetId')}  title={p.get('title')!r}")

    def fetch_gid(gid: int) -> tuple[str | None, list | None, str | None]:
        title = None
        for sh in meta.get("sheets", []):
            p = sh.get("properties", {})
            if int(p.get("sheetId", -1)) == gid:
                title = str(p.get("title") or "")
                break
        if not title:
            return None, None, "gid not found"
        try:
            res = (
                svc.spreadsheets()
                .values()
                .get(spreadsheetId=SPREADSHEET_ID, range=title, majorDimension="ROWS")
                .execute()
            )
            return title, res.get("values") or [], None
        except Exception as e:
            return title, None, str(e)

    for gid in [TARGET_GID, CURRENT_GID]:
        print(f"\n=== 测试 gid={gid} ===")
        title, rows, err = fetch_gid(gid)
        if err:
            print(f"  FAIL: {err}")
            continue
        print(f"  sheet={title!r} rows={len(rows)}")
        for i, row in enumerate(rows[:5]):
            preview = " | ".join(str(c)[:20] for c in row[:8])
            print(f"  row{i}: {preview}")
        emp_count = sum(
            1 for row in rows if any(_EMP_RE.match(str(c).strip()) for c in row)
        )
        print(f"  疑似员工行(含3-8位工号): ~{emp_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
