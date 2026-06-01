from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

_SWITCH_QUERY_MAX = 256
_TZ = ZoneInfo("Asia/Shanghai")


def _clip_query(text: str) -> str:
    return text if len(text) <= _SWITCH_QUERY_MAX else text[:_SWITCH_QUERY_MAX]


def _now_local_str() -> str:
    return datetime.now(_TZ).strftime("%H:%M:%S")


def build_checkin_draft(*, english_name: str, employee_id: str, action: str) -> str:
    return f"#打卡\n英文名：{english_name}\n工号：{employee_id}\n事项：{action}"


def build_leave_draft(*, english_name: str, employee_id: str) -> str:
    return (
        f"#离岗报备\n人员：{english_name}\n工号：{employee_id}\n"
        f"时间：{_now_local_str()}\n原因："
    )


def build_back_draft(*, english_name: str, employee_id: str) -> str:
    return f"#返岗报备\n人员：{english_name}\n工号：{employee_id}\n时间：{_now_local_str()}"


def build_draft_for_action(*, action: str, english_name: str, employee_id: str) -> str:
    if action == "signin":
        return build_checkin_draft(english_name=english_name, employee_id=employee_id, action="签到")
    if action == "signout":
        return build_checkin_draft(english_name=english_name, employee_id=employee_id, action="签退")
    if action == "leave":
        return build_leave_draft(english_name=english_name, employee_id=employee_id)
    if action == "back":
        return build_back_draft(english_name=english_name, employee_id=employee_id)
    raise ValueError(f"unknown action: {action}")


def _fill_button(*, text: str, draft: str) -> InlineKeyboardButton:
    """一点击即将模板填入输入框（带 ↗）。"""
    return InlineKeyboardButton(
        text=text,
        switch_inline_query_current_chat=_clip_query(draft),
    )


_ACTION_LABELS = {
    "signin": "签到",
    "signout": "签退",
    "leave": "离岗",
    "back": "返岗",
}

_ACTION_CALLBACK = {
    "signin": "act:signin",
    "signout": "act:signout",
    "leave": "act:leave",
    "back": "act:back",
}


def build_single_action_inline(
    *,
    action: str,
    english_name: str,
    employee_id: str,
) -> InlineKeyboardMarkup:
    """已注册：仅一个带 ↗ 的填入按钮（与底部所点项一致）。"""
    label = _ACTION_LABELS.get(action, action)
    draft = build_draft_for_action(
        action=action,
        english_name=english_name,
        employee_id=employee_id,
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [_fill_button(text=label, draft=draft)],
        ]
    )


def build_single_action_inline_or_callback(
    *,
    action: str,
    english_name: str | None = None,
    employee_id: str | None = None,
) -> InlineKeyboardMarkup:
    name = (english_name or "").strip()
    eid = (employee_id or "").strip()
    if name and eid:
        return build_single_action_inline(
            action=action,
            english_name=name,
            employee_id=eid,
        )
    label = _ACTION_LABELS.get(action, action)
    cb = _ACTION_CALLBACK.get(action, f"act:{action}")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=cb)],
        ]
    )


def build_group_actions_inline(
    *,
    english_name: str | None = None,
    employee_id: str | None = None,
) -> InlineKeyboardMarkup:
    """群内：已注册一点击即填入输入框；未注册用 callback 提示注册。"""
    name = (english_name or "").strip()
    eid = (employee_id or "").strip()
    if name and eid:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    _fill_button(
                        text="签到",
                        draft=build_checkin_draft(english_name=name, employee_id=eid, action="签到"),
                    ),
                    _fill_button(
                        text="签退",
                        draft=build_checkin_draft(english_name=name, employee_id=eid, action="签退"),
                    ),
                ],
                [
                    _fill_button(
                        text="离岗",
                        draft=build_leave_draft(english_name=name, employee_id=eid),
                    ),
                    _fill_button(
                        text="返岗",
                        draft=build_back_draft(english_name=name, employee_id=eid),
                    ),
                ],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="签到", callback_data="act:signin"),
                InlineKeyboardButton(text="签退", callback_data="act:signout"),
            ],
            [
                InlineKeyboardButton(text="离岗", callback_data="act:leave"),
                InlineKeyboardButton(text="返岗", callback_data="act:back"),
            ],
        ]
    )
