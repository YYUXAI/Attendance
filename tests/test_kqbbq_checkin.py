from infra.checkin_ocrspace_config import is_ocrspace_extract_chat
from infra.kqbbq_checkin_config import is_kqbbq_chat
from infra.leave_return_keyboard_only_config import is_qdyyz_chat


def test_kqbbq_requires_name_time_date_and_ocrspace() -> None:
    chat_id = -1003883297177
    title = "Y-UX-KQBBQ"
    assert is_kqbbq_chat(chat_id=chat_id, chat_title=title)
    assert is_kqbbq_chat(chat_id=chat_id, chat_title=None)
    assert is_kqbbq_chat(chat_id=None, chat_title=title)
    assert not is_qdyyz_chat(chat_id=chat_id, chat_title=title)
    assert is_ocrspace_extract_chat(chat_id=chat_id, chat_title=title)


def test_other_groups_are_not_kqbbq() -> None:
    assert not is_kqbbq_chat(chat_id=-1004373351741, chat_title="QDYYZ 打卡报备群")
    assert not is_kqbbq_chat(chat_id=-1004347063533, chat_title="ux助手考勤测试群")


import json

from services.leave_flow_guard import (
    check_can_back,
    check_can_leave,
    requires_leave_mutual_exclusion,
)


def test_kqbbq_skips_leave_return_guards_even_if_capability_declared(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        "ATTENDANCE_GROUPS_JSON",
        json.dumps(
            [
                {
                    "title": "Y-UX-KQBBQ",
                    "roster": "main",
                    "capabilities": ["standard-checkin", "leave-mutual-exclusion"],
                }
            ],
            separators=(",", ":"),
        ),
    )
    chat_id = -1003883297177
    title = "Y-UX-KQBBQ"
    assert requires_leave_mutual_exclusion(chat_id=chat_id, chat_title=title) is False
    assert check_can_leave(employee_id="51761", chat_id=chat_id, chat_title=title) == (
        True,
        None,
    )
    assert check_can_back(employee_id="51761", chat_id=chat_id, chat_title=title) == (
        True,
        None,
    )


def test_other_group_keeps_leave_mutual_exclusion(monkeypatch) -> None:
    monkeypatch.setenv(
        "ATTENDANCE_GROUPS_JSON",
        json.dumps(
            [
                {
                    "title": "测试服务器",
                    "roster": "main",
                    "capabilities": ["standard-checkin", "leave-mutual-exclusion"],
                }
            ],
            separators=(",", ":"),
        ),
    )
    assert (
        requires_leave_mutual_exclusion(
            chat_id=-5555156111,
            chat_title="测试服务器",
        )
        is True
    )
