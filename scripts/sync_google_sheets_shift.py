#!/usr/bin/env python3
"""从 Google 统筹部排班表同步班次到 PostgreSQL。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

from services.google_sheets_shift_sync_service import sync_shifts_from_google_sheets


def main() -> int:
    result = sync_shifts_from_google_sheets()
    print(result.message)
    if result.ok:
        print(
            f"  year_month={result.year_month} "
            f"employees={result.employee_count} cells={result.calendar_cells} "
            f"sheet={result.sheet_title!r}"
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
