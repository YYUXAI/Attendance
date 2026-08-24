from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from infra.admin_export_scope_config import admin_export_chat_id_for_employee
from infra.google_sheets_alt_config import load_google_sheets_alt_config
from repositories import admin_list_repo, employee_shift_roster_repo, registrations_repo

SHIFT_VIEW_MAIN = "main"
SHIFT_VIEW_ALT = "alt"
SHIFT_VIEW_TEST_GROUP = "test_group"
# ux助手考勤测试群：管理员导出范围绑此群时，班表 Web 走 test_group roster。
_UX_ASSISTANT_ATTENDANCE_TEST_GROUP_CHAT_ID = -1004347063533


def _admin_export_scoped_shift_view(*, tg_id: int) -> str | None:
    if not admin_list_repo.is_admin_by_tg_id(tg_id=int(tg_id)):
        return None
    reg = registrations_repo.get_by_tg_id(int(tg_id))
    if not reg:
        return None
    export_chat = admin_export_chat_id_for_employee(employee_id=str(reg.employee_id))
    if export_chat == _UX_ASSISTANT_ATTENDANCE_TEST_GROUP_CHAT_ID:
        return SHIFT_VIEW_TEST_GROUP
    return None


def shift_view_for_tg_id(*, tg_id: int) -> str:
    scoped = _admin_export_scoped_shift_view(tg_id=tg_id)
    if scoped:
        return scoped
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
    if view == SHIFT_VIEW_TEST_GROUP:
        return employee_shift_roster_repo.roster_set(
            year_month=ym, source=SHIFT_VIEW_TEST_GROUP
        )
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
        if view in {SHIFT_VIEW_ALT, SHIFT_VIEW_TEST_GROUP}:
            return []
        return rows
    return [
        r for r in rows if str(getattr(r, "employee_id", "")).strip() in allowed
    ]
