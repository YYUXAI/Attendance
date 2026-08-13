#!/usr/bin/env python3
"""测试能否读取 MGZ Google 表指定 gid。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from infra.google_sheets_alt_config import load_google_sheets_alt_config
from services.google_sheets_client import fetch_sheet_values

_EMP_RE = re.compile(r"^\d{3,8}$")


def main() -> int:
    cfg = load_google_sheets_alt_config()
    if cfg is None or not cfg.credentials_json:
        raise RuntimeError("alt-roster Sheet private bindings are required")
    title, rows = fetch_sheet_values(
        spreadsheet_id=cfg.spreadsheet_id,
        credentials_json=cfg.credentials_json,
        sheet_gid=cfg.sheet_gid,
    )
    print(f"sheet={title!r} rows={len(rows)}")
    emp_count = sum(
        1 for row in rows if any(_EMP_RE.match(str(c).strip()) for c in row)
    )
    print(f"疑似员工行(含3-8位工号): ~{emp_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
