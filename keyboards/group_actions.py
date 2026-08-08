from __future__ import annotations

from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup

from domain.action_drafts import (
    build_back_draft,
    build_checkin_draft,
    build_leave_draft,
)

_SWITCH_QUERY_MAX = 256
_BOT_MENTION = "@zpxinbot"


def _clip_query(text: str) -> str:
    """保留开头换行（用于 @bot 与 #标签 分行）；仅去掉末尾空白。"""
    clipped = (text or "").rstrip()
    return clipped if len(clipped) <= _SWITCH_QUERY_MAX else clipped[:_SWITCH_QUERY_MAX]


def build_draft_for_action(
    *,
    action: str,
    english_name: str,
    employee_id: str,
    leave_duration: str | None = None,
    leave_overtime: bool = False,
    remote_diff: bool = False,
) -> str:
    if action == "signin":
        return build_checkin_draft(
            english_name=english_name,
            employee_id=employee_id,
            action="签到",
        )
    if action == "signout":
        return build_checkin_draft(
            english_name=english_name,
            employee_id=employee_id,
            action="签退",
        )
    if action == "leave":
        return build_leave_draft(english_name=english_name, employee_id=employee_id)
    if action == "back":
        return build_back_draft(
            english_name=english_name,
            employee_id=employee_id,
            leave_duration=leave_duration,
            leave_overtime=leave_overtime,
        )
    raise ValueError(f"unknown action: {action}")


def _copy_button(*, text: str, draft: str) -> InlineKeyboardButton:
    """签到/签退「复制」兜底。"""
    return InlineKeyboardButton(
        text=text,
        copy_text=CopyTextButton(text=_clip_query(draft)),
    )


def _fill_button(*, text: str, draft: str) -> InlineKeyboardButton:
    """一点击即将完整模板填入输入框（↗）；离岗/返岗为 @bot 与 #标签 分行。"""
    return InlineKeyboardButton(
        text=text,
        switch_inline_query_current_chat=_clip_query(draft),
    )


def _action_button_row(*, label: str, draft: str, copy_fallback: bool = False) -> list[InlineKeyboardButton]:
    clipped = _clip_query(draft)
    row = [InlineKeyboardButton(text=label, switch_inline_query_current_chat=clipped)]
    if copy_fallback:
        row.append(InlineKeyboardButton(text="复制", copy_text=CopyTextButton(text=clipped)))
    return row


_ACTION_LABELS = {
    "signin": "签到",
    "signout": "签退",
    "leave": "离岗",
    "back": "返岗",
}

_ACTION_CALLBACK = {
    "signin": "att:signin",
    "signout": "att:signout",
    "leave": "att:leave",
    "back": "att:back",
}


def build_single_action_inline(
    *,
    action: str,
    english_name: str,
    employee_id: str,
    copy_fallback: bool = False,
    leave_duration: str | None = None,
    leave_overtime: bool = False,
    remote_diff: bool = False,
) -> InlineKeyboardMarkup:
    """已注册：带 ↗ 的填入按钮（与底部所点项一致）。"""
    label = _ACTION_LABELS.get(action, action)
    draft = build_draft_for_action(
        action=action,
        english_name=english_name,
        employee_id=employee_id,
        leave_duration=leave_duration,
        leave_overtime=leave_overtime,
        remote_diff=remote_diff,
    )
    if copy_fallback:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                _action_button_row(label=label, draft=draft, copy_fallback=True),
            ]
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
    copy_fallback: bool = False,
    leave_duration: str | None = None,
    leave_overtime: bool = False,
    remote_diff: bool = False,
) -> InlineKeyboardMarkup:
    name = (english_name or "").strip()
    eid = (employee_id or "").strip()
    if name and eid:
        return build_single_action_inline(
            action=action,
            english_name=name,
            employee_id=eid,
            copy_fallback=copy_fallback,
            leave_duration=leave_duration,
            leave_overtime=leave_overtime,
            remote_diff=remote_diff,
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
    copy_fallback: bool = False,
    remote_diff: bool = False,
) -> InlineKeyboardMarkup:
    """群内：已注册一点击即填入输入框；未注册用 callback 提示注册。"""
    name = (english_name or "").strip()
    eid = (employee_id or "").strip()
    if name and eid:
        if copy_fallback:
            return InlineKeyboardMarkup(
                inline_keyboard=[
                    _action_button_row(
                        label="签到",
                        draft=build_checkin_draft(
                            english_name=name, employee_id=eid, action="签到"
                        ),
                        copy_fallback=True,
                    ),
                    _action_button_row(
                        label="签退",
                        draft=build_checkin_draft(
                            english_name=name, employee_id=eid, action="签退"
                        ),
                        copy_fallback=True,
                    ),
                    _action_button_row(
                        label="离岗",
                        draft=build_leave_draft(english_name=name, employee_id=eid),
                        copy_fallback=True,
                    ),
                    _action_button_row(
                        label="返岗",
                        draft=build_back_draft(english_name=name, employee_id=eid),
                        copy_fallback=True,
                    ),
                ]
            )
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    _fill_button(
                        text="签到",
                        draft=build_checkin_draft(
                            english_name=name, employee_id=eid, action="签到"
                        ),
                    ),
                    _fill_button(
                        text="签退",
                        draft=build_checkin_draft(
                            english_name=name, employee_id=eid, action="签退"
                        ),
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
                InlineKeyboardButton(text="签到", callback_data="att:signin"),
                InlineKeyboardButton(text="签退", callback_data="att:signout"),
            ],
            [
                InlineKeyboardButton(text="离岗", callback_data="att:leave"),
                InlineKeyboardButton(text="返岗", callback_data="att:back"),
            ],
        ]
    )
