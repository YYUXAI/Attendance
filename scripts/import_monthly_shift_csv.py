"""导入每月班次 CSV（桌面或任意路径）到 employee_shift_config。"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(override=True, encoding="utf-8")

from services.shift_import_service import (
    TEMPLATE_HEADERS_CN,
    _canonical_key,
    import_row_dicts,
)


def import_csv(path: str, *, default_month: str | None = None) -> tuple[int, str]:
    default_month = (default_month or "").strip() or date.today().strftime("%Y-%m")
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV 无表头")
        mapped = {_canonical_key(c) for c in reader.fieldnames if c and _canonical_key(c)}
        need = {
            "year_month",
            "employee_id",
            "english_name",
            "shift_checkin_time",
            "shift_checkout_time",
        }
        missing = need - mapped
        if missing:
            raise ValueError(
                f"缺少列（需中文表头 {','.join(TEMPLATE_HEADERS_CN)} 或旧英文表头）: {', '.join(sorted(missing))}"
            )
        rows = list(reader)
    saved, ym, errors = import_row_dicts(rows=rows, default_year_month=default_month)
    if errors:
        raise ValueError("；".join(errors[:10]))
    return saved, ym


def main() -> None:
    p = argparse.ArgumentParser(description="导入每月班次 CSV")
    p.add_argument("csv_path", help="CSV 文件路径")
    p.add_argument("--month", default="", help="默认月份 YYYY-MM（「日期」列可写 2026-05 或 May-26）")
    args = p.parse_args()
    path = os.path.abspath(args.csv_path)
    if not os.path.isfile(path):
        raise SystemExit(f"文件不存在: {path}")

    n, ym = import_csv(path, default_month=args.month or None)
    print(f"导入完成: {n} 行 -> employee_shift_config (year_month={ym})")


if __name__ == "__main__":
    main()
