"""Inspect QDYYZ (alt roster) September sheet sync vs DB."""
from __future__ import annotations

import os
from collections import Counter

from infra.db import database_url_scope
from infra.google_sheets_alt_config import load_google_sheets_alt_config
from infra.google_sheets_config import load_google_sheets_config
from repositories import employee_shift_roster_repo
from services.google_sheets_shift_sync_service import fetch_shift_matrix_sheet, parse_shift_matrix

YM = "2026-09"


def main() -> None:
    db = os.environ["ATTENDANCE_DATABASE_URL"]
    with database_url_scope(db):
        cfg = load_google_sheets_config()
        alt = load_google_sheets_alt_config()
        print(f"config year_month={cfg.year_month!r} enabled={cfg.enabled}")
        if not alt:
            print("alt config: MISSING")
            return
        print(f"alt sheet id={alt.spreadsheet_id} gid={alt.sheet_gid}")

        title, rows = fetch_shift_matrix_sheet(
            spreadsheet_id=alt.spreadsheet_id,
            credentials_json=alt.credentials_json,
            year_month=YM,
            source="alt",
            fallback_gid=alt.sheet_gid,
        )
        _, emps = parse_shift_matrix(rows, year_month=YM)
        print(f"sheet tab={title!r} rows={len(rows)} employees={len(emps)}")

        sheet_combos: Counter[tuple[str, str, str]] = Counter()
        for e in emps:
            sheet_combos[(e.shift_time_range, e.shift_timezone, e.region_code)] += 1
        print("\nfrom Google sheet (shift_range, timezone, region):")
        for key, count in sorted(sheet_combos.items(), key=lambda x: (x[0][1], x[0][0])):
            print(f"  {count:2d}  {key[0]:14s}  {key[1]:16s}  {key[2]}")

        alt_ids = set(employee_shift_roster_repo.list_roster(year_month=YM, source="alt"))
        print(f"\nalt roster in DB: {len(alt_ids)} employees")

        from infra.db import get_cursor

        with get_cursor() as cur:
            cur.execute(
                """
                SELECT shift_time_range, shift_timezone, region_code, COUNT(*)
                FROM employee_shift_config
                WHERE year_month = %s AND employee_id = ANY(%s)
                GROUP BY 1, 2, 3
                ORDER BY 2, 1
                """,
                (YM, list(alt_ids) if alt_ids else ["__none__"]),
            )
            db_rows = cur.fetchall() or []
        print("\nfrom DB employee_shift_config:")
        for row in db_rows:
            print(f"  {row[3]:2d}  {row[0]:14s}  {row[1]:16s}  {row[2]}")

        sheet_ids = {e.employee_id for e in emps}
        only_sheet = sheet_ids - alt_ids
        only_db = alt_ids - sheet_ids
        if only_sheet:
            print(f"\nonly in sheet ({len(only_sheet)}): {sorted(only_sheet)[:10]}...")
        if only_db:
            print(f"\nonly in DB roster ({len(only_db)}): {sorted(only_db)[:10]}...")
        if not only_sheet and not only_db and len(sheet_ids) == len(alt_ids):
            print("\nroster employee ids: sheet == DB")


if __name__ == "__main__":
    main()
