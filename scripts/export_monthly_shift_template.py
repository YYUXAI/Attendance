"""按「每月导入表头」从 registrations + shifts 导出 CSV。"""
from __future__ import annotations

import argparse
import codecs
import csv
import io
import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(override=True, encoding="utf-8")

from infra.db import get_cursor

from services.shift_import_service import TEMPLATE_HEADERS_CN

HEADERS = TEMPLATE_HEADERS_CN


def _fmt_time(t: object) -> str:
    if t is None:
        return ""
    if hasattr(t, "strftime"):
        return t.strftime("%H:%M")  # type: ignore[union-attr]
    return str(t)[:5]


def export_csv(*, year_month: str, out_path: str) -> int:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT r.employee_id, COALESCE(r.english_name, ''),
                   s.checkin_time, s.checkout_time,
                   COALESCE(c.monthly_rest_days, '')
            FROM public.registrations r
            LEFT JOIN public.shifts s ON s.id = r.shift_id
            LEFT JOIN public.employee_shift_config c ON c.employee_id = r.employee_id
            ORDER BY CAST(r.employee_id AS BIGINT)
            """
        )
        try:
            rows = cur.fetchall() or []
        except Exception:
            cur.execute(
                """
                SELECT r.employee_id, COALESCE(r.english_name, ''),
                       s.checkin_time, s.checkout_time, ''::text
                FROM public.registrations r
                LEFT JOIN public.shifts s ON s.id = r.shift_id
                ORDER BY CAST(r.employee_id AS BIGINT)
                """
            )
            rows = cur.fetchall() or []

    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(HEADERS)
    for eid, ename, cin, cout, rest in rows:
        cin_s, cout_s = _fmt_time(cin), _fmt_time(cout)
        rng = f"{cin_s}~{cout_s}" if cin_s and cout_s else ""
        writer.writerow([year_month, str(eid), ename, rng, cin_s, cout_s, rest or ""])

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(codecs.BOM_UTF8 + buf.getvalue().encode("utf-8"))
    return len(rows)


def main() -> None:
    p = argparse.ArgumentParser(description="导出每月班次导入模板 CSV")
    p.add_argument("--month", default=date.today().strftime("%Y-%m"), help="YYYY-MM")
    p.add_argument(
        "--out",
        default="",
        help="输出路径，默认 docs/monthly_shift_template_YYYY-MM.csv",
    )
    args = p.parse_args()
    ym = str(args.month).strip()
    out = args.out or os.path.join(ROOT, "docs", f"monthly_shift_template_{ym}.csv")
    n = export_csv(year_month=ym, out_path=out)
    print(f"已导出 {n} 行 -> {out}")


if __name__ == "__main__":
    main()
