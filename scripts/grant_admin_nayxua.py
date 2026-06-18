"""将 NAYXUA（工号 74306）加入 admin_list。"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env", override=True, encoding="utf-8")

from infra.db import get_cursor
from repositories import admin_list_repo, registrations_repo


def main() -> None:
    reg = registrations_repo.get_by_employee_id("74306")
    if not reg:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT employee_id, tg_id, english_name, tg_username
                FROM public.registrations
                WHERE LOWER(english_name) LIKE %s
                ORDER BY employee_id ASC
                """,
                ("%nayxua%",),
            )
            rows = cur.fetchall() or []
        if not rows:
            print("未找到 NAYXUA / 74306，请先完成注册")
            return
        eid = str(rows[0][0])
        reg = registrations_repo.get_by_employee_id(eid)
    if not reg:
        print("未找到注册记录")
        return

    inserted = admin_list_repo.grant_admin_by_employee_id(employee_id=str(reg.employee_id))
    ok = admin_list_repo.is_admin_by_tg_id(tg_id=int(reg.tg_id))
    print(
        f"english_name={reg.english_name} employee_id={reg.employee_id} "
        f"tg_id={reg.tg_id} tg_username={reg.tg_username} "
        f"grant_new={inserted} is_admin={ok}"
    )


if __name__ == "__main__":
    main()
