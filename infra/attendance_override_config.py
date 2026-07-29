from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AttendanceOverrideConfig:
    export_employee_chat: dict[str, int]
    export_mirror_from: dict[str, str]
    leave_mutual_exclusion_chat_ids: frozenset[int]


def _parse_int_set(raw: str) -> frozenset[int]:
    out: set[int] = set()
    for part in (raw or "").replace("，", ",").split(","):
        p = part.strip()
        if not p:
            continue
        try:
            out.add(int(p))
        except ValueError:
            continue
    return frozenset(out)


def _parse_employee_chat_map(raw: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for part in (raw or "").replace("，", ",").split(","):
        p = part.strip()
        if not p or ":" not in p:
            continue
        eid, cid = p.split(":", 1)
        eid, cid = eid.strip(), cid.strip()
        if not eid or not cid:
            continue
        try:
            out[eid] = int(cid)
        except ValueError:
            continue
    return out


def _parse_mirror_map(raw: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in (raw or "").replace("，", ",").split(","):
        p = part.strip()
        if not p or ":" not in p:
            continue
        src, dst = p.split(":", 1)
        src, dst = src.strip(), dst.strip()
        if src and dst:
            out[dst] = src
    return out


def load_attendance_override_config() -> AttendanceOverrideConfig:
    export_map = _parse_employee_chat_map(
        os.getenv("CHECKIN_EXPORT_EMPLOYEE_CHAT_OVERRIDES") or ""
    )
    mirror_map = _parse_mirror_map(os.getenv("CHECKIN_EXPORT_MIRROR_EMPLOYEE_IDS") or "")
    _DEFAULT_LEAVE_IDS = frozenset(
        {
            -1004496944161,  # YYMG-DKQ-(NEW)
            -1003785692598,  # New-考勤测试群
        }
    )
    leave_ids = _parse_int_set(os.getenv("LEAVE_MUTUAL_EXCLUSION_CHAT_IDS") or "")
    if not leave_ids:
        leave_ids = _DEFAULT_LEAVE_IDS
    test_chat = (os.getenv("NEW_ATTENDANCE_TEST_CHAT_ID") or "").strip()
    if test_chat:
        try:
            cid = int(test_chat)
            leave_ids = leave_ids | frozenset({cid})
        except ValueError:
            pass
    return AttendanceOverrideConfig(
        export_employee_chat=export_map,
        export_mirror_from=mirror_map,
        leave_mutual_exclusion_chat_ids=leave_ids,
    )
