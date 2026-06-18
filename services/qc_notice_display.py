from __future__ import annotations

"""质检群/私信公告共用展示口径（仅文案与字段格式化，不含业务状态机）。"""

from domain.audit_rules import as_time
from repositories import organizations_repo, registrations_repo, shifts_repo


def format_shift_time_range_hhmm(*, shift: shifts_repo.ShiftRow) -> str:
    """班次上下班时间段，24 小时制 HH:MM — HH:MM，不使用数据库 str() 直出。"""
    cin = as_time(shift.checkin_time)
    cout = as_time(shift.checkout_time)
    return f"{cin.hour:02d}:{cin.minute:02d} — {cout.hour:02d}:{cout.minute:02d}"


def department_display_for_shift_id(*, shift_id: int) -> str:
    """
    单一部门展示规则（与 2004 / 完结 / 汇总一致）：
    - 单部门：部门名（空名记为「未命名部门」）
    - 多部门：固定「多部门」
    - 无组织绑定：「未绑定」
    """
    regs = registrations_repo.list_by_shift_id(shift_id=int(shift_id))
    org_ids = {int(r.organization_id) for r in regs if r.organization_id is not None}
    if not org_ids:
        return "未绑定"
    org_rows = organizations_repo.list_by_ids(organization_ids=sorted(org_ids))
    labels: set[str] = set()
    for o in org_rows:
        dn = (o.department_name or "").strip()
        labels.add(dn if dn else "未命名部门")
    if not labels:
        return "未绑定"
    if len(labels) > 1:
        return "多部门"
    return next(iter(labels))
