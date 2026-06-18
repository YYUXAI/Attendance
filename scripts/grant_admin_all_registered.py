"""将全部已注册工号加入 admin_list，并验证 is_admin。"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env", override=True, encoding="utf-8")

from infra.db import get_cursor
from repositories import admin_list_repo


def main() -> None:
    inserted, total = admin_list_repo.grant_admin_all_registered()
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT employee_id, english_name, tg_id
            FROM public.registrations
            ORDER BY employee_id
            """
        )
        rows = cur.fetchall() or []
    ok = 0
    for eid, name, tid in rows:
        if admin_list_repo.is_admin_by_tg_id(tg_id=int(tid)):
            ok += 1
        print(f"  {eid} {name or '-'} tg_id={tid}")
    print(
        f"done: registrations={len(rows)} new_admin_rows={inserted} "
        f"admin_list_total={total} is_admin_ok={ok}/{len(rows)}"
    )


if __name__ == "__main__":
    main()
