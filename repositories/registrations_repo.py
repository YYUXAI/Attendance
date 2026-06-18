from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from psycopg2.extensions import cursor as Cursor

from infra.db import get_cursor


@dataclass(frozen=True)
class RegistrationRow:
    id: int
    employee_id: str
    tg_id: int
    english_name: Optional[str]
    tg_username: Optional[str]
    registered_chat_id: Optional[int]
    organization_id: Optional[int]
    shift_id: Optional[int]


def get_by_tg_username(tg_username: str) -> Optional[RegistrationRow]:
    key = (tg_username or "").strip().lstrip("@").lower()
    if not key:
        return None
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, employee_id, tg_id, english_name, tg_username, registered_chat_id,
                   organization_id, shift_id
            FROM public.registrations
            WHERE LOWER(TRIM(BOTH '@' FROM COALESCE(tg_username, ''))) = %s
            ORDER BY id DESC
            LIMIT 1
            """,
            (key,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return RegistrationRow(*row)


def get_by_tg_id(tg_id: int) -> Optional[RegistrationRow]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, employee_id, tg_id, english_name, tg_username, registered_chat_id,
                   organization_id, shift_id
            FROM public.registrations
            WHERE tg_id = %s
            """,
            (tg_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        return RegistrationRow(*row)


def get_by_employee_id_cur(cur: Cursor, *, employee_id: str) -> Optional[RegistrationRow]:
    cur.execute(
        """
        SELECT id, employee_id, tg_id, english_name, tg_username, registered_chat_id,
               organization_id, shift_id
        FROM public.registrations
        WHERE employee_id = %s
        """,
        (str(employee_id),),
    )
    row = cur.fetchone()
    if not row:
        return None
    return RegistrationRow(*row)


def get_by_employee_id(employee_id: str) -> Optional[RegistrationRow]:
    with get_cursor() as cur:
        return get_by_employee_id_cur(cur, employee_id=str(employee_id))


def list_by_employee_ids(*, employee_ids: Iterable[str]) -> List[RegistrationRow]:
    keys = sorted({str(x).strip() for x in employee_ids if x is not None and str(x).strip()})
    if not keys:
        return []
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, employee_id, tg_id, english_name, tg_username, registered_chat_id,
                   organization_id, shift_id
            FROM public.registrations
            WHERE employee_id IN %s
            ORDER BY employee_id ASC
            """,
            (tuple(keys),),
        )
        rows = cur.fetchall() or []
    return [RegistrationRow(*r) for r in rows]


def insert_registration(
    *,
    employee_id: str,
    tg_id: int,
    english_name: str,
    registered_at_utc,
    registered_chat_id: int,
    tg_username: Optional[str],
) -> None:
    with get_cursor() as cur:
        cur.execute(
            """
            INSERT INTO public.registrations
                (employee_id, tg_id, english_name, registered_at, registered_chat_id, tg_username)
            VALUES
                (%s, %s, %s, %s, %s, %s)
            """,
            (employee_id, tg_id, english_name, registered_at_utc, registered_chat_id, tg_username),
        )


def list_by_shift_id_cur(cur: Cursor, *, shift_id: int) -> List[RegistrationRow]:
    """
    一期审计对象口径：registrations.shift_id == 当前班次的员工。
    """
    cur.execute(
        """
        SELECT id, employee_id, tg_id, english_name, tg_username, registered_chat_id,
               organization_id, shift_id
        FROM public.registrations
        WHERE shift_id = %s
        ORDER BY id ASC
        """,
        (shift_id,),
    )
    rows = cur.fetchall()
    return [RegistrationRow(*r) for r in rows]


def list_by_shift_id(*, shift_id: int) -> List[RegistrationRow]:
    with get_cursor() as cur:
        return list_by_shift_id_cur(cur, shift_id=shift_id)


def list_registered_usernames(*, limit: int = 300) -> List[str]:
    cap = max(1, min(int(limit or 300), 2000))
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT LOWER(TRIM(BOTH '@' FROM tg_username)) AS uname
            FROM public.registrations
            WHERE COALESCE(TRIM(tg_username), '') <> ''
            ORDER BY uname ASC
            LIMIT %s
            """,
            (cap,),
        )
        rows = cur.fetchall() or []
    out: List[str] = []
    for (uname,) in rows:
        s = str(uname or "").strip()
        if s:
            out.append(s)
    return out


def update_assignment_by_tg_id(
    *,
    tg_id: int,
    shift_id: Optional[int],
    organization_id: Optional[int],
) -> int:
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE public.registrations
            SET shift_id = %s,
                organization_id = %s
            WHERE tg_id = %s
            """,
            (shift_id, organization_id, int(tg_id)),
        )
        return int(cur.rowcount or 0)


def update_registered_chat_by_tg_id(*, tg_id: int, registered_chat_id: int) -> int:
    with get_cursor() as cur:
        cur.execute(
            """
            UPDATE public.registrations
            SET registered_chat_id = %s
            WHERE tg_id = %s
            """,
            (int(registered_chat_id), int(tg_id)),
        )
        return int(cur.rowcount or 0)
