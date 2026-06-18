from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple

from infra.db import get_cursor


@dataclass(frozen=True)
class OrganizationRow:
    id: int
    department_name: Optional[str]
    leader_employee_id: Optional[str]
    highest_responsible_employee_id: Optional[str]


def get_department_name_by_id(organization_id: int) -> Optional[str]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT department_name
            FROM public.organizations
            WHERE id = %s
            """,
            (organization_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return row[0]


def get_leader_fields(organization_id: int) -> Tuple[Optional[str], Optional[str]]:
    """审批人解析用：leader_employee_id, highest_responsible_employee_id（仅读库，无业务判断）。"""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT leader_employee_id, highest_responsible_employee_id
            FROM public.organizations
            WHERE id = %s
            """,
            (organization_id,),
        )
        row = cur.fetchone()
        if not row:
            return None, None
        return row[0], row[1]


def list_by_ids(*, organization_ids: Iterable[int]) -> list[OrganizationRow]:
    ids = [int(x) for x in organization_ids if x is not None]
    if not ids:
        return []
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, department_name, leader_employee_id, highest_responsible_employee_id
            FROM public.organizations
            WHERE id IN %s
            ORDER BY id ASC
            """,
            (tuple(ids),),
        )
        rows = cur.fetchall() or []
    return [OrganizationRow(int(r[0]), r[1], r[2], r[3]) for r in rows]


def list_by_highest_responsible_employee_ids(
    *,
    highest_responsible_employee_ids: Iterable[str],
) -> list[OrganizationRow]:
    keys = [str(x).strip() for x in highest_responsible_employee_ids if x is not None and str(x).strip()]
    if not keys:
        return []
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, department_name, leader_employee_id, highest_responsible_employee_id
            FROM public.organizations
            WHERE highest_responsible_employee_id IN %s
            ORDER BY highest_responsible_employee_id ASC, id ASC
            """,
            (tuple(keys),),
        )
        rows = cur.fetchall() or []
    return [OrganizationRow(int(r[0]), r[1], r[2], r[3]) for r in rows]
