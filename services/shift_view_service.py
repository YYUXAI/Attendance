from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from infra.google_sheets_alt_config import load_google_sheets_alt_config
from repositories import admin_list_repo, employee_shift_roster_repo, registrations_repo

SHIFT_VIEW_MAIN = "main"
SHIFT_VIEW_ALT = "alt"


def shift_view_for_tg_id(*, tg_id: int) -> str:
    alt_cfg = load_google_sheets_alt_config()
    if not alt_cfg:
        return SHIFT_VIEW_MAIN
    reg = registrations_repo.get_by_tg_id(int(tg_id))
    if not reg:
        return SHIFT_VIEW_MAIN
    eid = str(reg.employee_id).strip()
    if eid in alt_cfg.viewer_employee_ids:
        return SHIFT_VIEW_ALT
    ym = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")
    alt_roster = employee_shift_roster_repo.roster_set(year_month=ym, source=SHIFT_VIEW_ALT)
    if (
        alt_roster
        and eid in alt_roster
        and admin_list_repo.is_admin_by_tg_id(tg_id=int(tg_id))
    ):
        return SHIFT_VIEW_ALT
    return SHIFT_VIEW_MAIN


def roster_employee_ids(*, year_month: str, view: str) -> frozenset[str]:
    ym = str(year_month).strip()
    if view == SHIFT_VIEW_ALT:
        ids = employee_shift_roster_repo.roster_set(year_month=ym, source=SHIFT_VIEW_ALT)
        alt_cfg = load_google_sheets_alt_config()
        mirror_only = alt_cfg.mirror_from_to.keys() if alt_cfg else ()
        if ids:
            return frozenset(e for e in ids if e not in mirror_only)
        if alt_cfg:
            return frozenset(
                e for e in alt_cfg.viewer_employee_ids if e not in mirror_only
            )
        return frozenset()
    ids = employee_shift_roster_repo.roster_set(year_month=ym, source=SHIFT_VIEW_MAIN)
    return ids


def filter_shift_config_rows(*, rows: list, year_month: str, view: str) -> list:
    allowed = roster_employee_ids(year_month=year_month, view=view)
    if not allowed:
        if view == SHIFT_VIEW_ALT:
            return []
        return rows
    return [
        r for r in rows if str(getattr(r, "employee_id", "")).strip() in allowed
    ]
