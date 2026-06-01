"""将 Brucewillis（工号 17025）加入 admin_list。"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

load_dotenv(_ROOT / ".env", override=True, encoding="utf-8")

from repositories import admin_list_repo, registrations_repo


def main() -> None:
    reg = registrations_repo.get_by_employee_id("17025")
    if not reg:
        print("未找到工号 17025，请确认 registrations 中已有 Brucewillis")
        return
    inserted = admin_list_repo.grant_admin_by_employee_id(employee_id=str(reg.employee_id))
    ok = admin_list_repo.is_admin_by_tg_id(tg_id=int(reg.tg_id))
    print(
        f"english_name={reg.english_name} employee_id={reg.employee_id} tg_id={reg.tg_id} "
        f"grant_new={inserted} is_admin={ok}"
    )


if __name__ == "__main__":
    main()
