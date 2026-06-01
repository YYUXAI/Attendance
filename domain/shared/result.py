from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ServiceResult:
    ok: bool
    message: str
    error_code: Optional[str] = None
    leave_application_id: Optional[int] = None
    expected_attendance_group_id: Optional[int] = None
    current_attendance_group_id: Optional[int] = None
