from __future__ import annotations

from aiogram.types import Message, ReplyKeyboardRemove

from infra.checkin_remote_diff_config import requires_remote_diff_checkin
from infra.gateway_group_scope import is_omni_group_chat
from infra.shift_web_config import build_shift_web_app_url, current_year_month, load_shift_web_config
from services.shift_web_session import create_session
from keyboards.group_actions import build_single_action_inline_or_callback
from keyboards.main_menu import build_group_reply_keyboard, build_private_reply_keyboard
from repositories import registrations_repo
from services.leave_flow_guard import (
    check_can_back,
    check_can_leave,
    compute_open_leave_draft_info,
    requires_leave_back_copy_fallback,
    requires_leave_mutual_exclusion,
)

MENU_TEXT = "请选择功能（使用输入框下方按钮；输入 / 可打开命令）："
GROUP_REPLY_MENU_TEXT = "功能菜单（底部按钮或 /start）"
_GROUP_INLINE_HINT = "请点击下方按钮操作"
_GROUP_INLINE_HINT_REMOTE = (
    "请点击 ↗ 填入模板；发截图时请「回复本条消息」发送（群隐私模式下否则 Bot 收不到）。"
    "若无法 ↗，请点「复制」后粘贴并回复本条发送。"
)


def build_shift_web_app_url_for_admin(*, tg_id: int) -> str | None:
    """每次生成带新 web_session 的链接；WebApp 内也可用 initData 换票。"""
    cfg = load_shift_web_config()
    ym = current_year_month(tz_name=cfg.timezone_name)
    session = create_session(tg_id=tg_id)
    return build_shift_web_app_url(year_month=ym, web_session=session)


async def reply_actions_menu(*, message: Message, is_admin: bool, tg_id: int | None = None) -> None:
    uid = tg_id if tg_id is not None else (message.from_user.id if message.from_user else None)
    if message.chat.type == "private":
        shift_url = build_shift_web_app_url_for_admin(tg_id=int(uid)) if uid is not None and is_admin else None
        await message.reply(
            MENU_TEXT,
            reply_markup=build_private_reply_keyboard(
                is_admin=is_admin,
                shift_web_app_url=shift_url,
            ),
        )
        return
    if is_omni_group_chat(int(message.chat.id)):
        await message.reply(
            "本群为 Omni 工作群，请使用 /qa 或 import；考勤菜单仅在考勤群提供。",
            reply_markup=ReplyKeyboardRemove(),
        )
        return
    await message.reply(
        GROUP_REPLY_MENU_TEXT,
        reply_markup=build_group_reply_keyboard(),
    )


async def reply_group_single_fill_menu(
    *,
    message: Message,
    action: str,
    tg_id: int | None = None,
) -> None:
    """点底部某一键后：只弹对应一个带 ↗ 的按钮（签到→签到，签退→签退…）。"""
    uid = tg_id if tg_id is not None else (message.from_user.id if message.from_user else None)
    reg = registrations_repo.get_by_tg_id(int(uid)) if uid is not None else None
    chat_id = int(message.chat.id)
    chat_title = message.chat.title if message.chat else None
    is_remote_group = requires_remote_diff_checkin(chat_id=chat_id, chat_title=chat_title)
    # 工号打卡群签到/签退需附截图，保留「复制」；YYMG 离岗/返岗单独加「复制」
    copy_fallback = (
        is_remote_group
        and action in ("signin", "signout")
    ) or (
        requires_leave_back_copy_fallback(chat_id=chat_id)
        and action in ("leave", "back")
    )

    if not reg:
        markup = build_single_action_inline_or_callback(
            action=action,
            copy_fallback=copy_fallback,
            remote_diff=is_remote_group,
        )
        await message.reply("请先私聊机器人完成注册（英文名$工号）。", reply_markup=markup)
        return
    if message.chat.type in ("group", "supergroup") and action == "leave":
        ok, hint = check_can_leave(
            employee_id=str(reg.employee_id),
            chat_id=chat_id,
        )
        if not ok:
            await message.reply(hint or "无法离岗")
            return
    if message.chat.type in ("group", "supergroup") and action == "back":
        ok, hint = check_can_back(
            employee_id=str(reg.employee_id),
            chat_id=chat_id,
        )
        if not ok:
            await message.reply(hint or "无法返岗")
            return
    name = (reg.english_name or "").strip() or "未命名"
    leave_duration = None
    leave_overtime = False
    if (
        message.chat.type in ("group", "supergroup")
        and action == "back"
        and requires_leave_mutual_exclusion(chat_id=chat_id)
    ):
        leave_info = compute_open_leave_draft_info(
            employee_id=str(reg.employee_id),
            chat_id=chat_id,
        )
        if leave_info is not None:
            leave_duration = leave_info.duration_text
            leave_overtime = leave_info.overtime
    markup = build_single_action_inline_or_callback(
        action=action,
        english_name=name,
        employee_id=str(reg.employee_id),
        copy_fallback=copy_fallback,
        leave_duration=leave_duration,
        leave_overtime=leave_overtime,
        remote_diff=is_remote_group,
    )
    hint = (
        _GROUP_INLINE_HINT_REMOTE
        if copy_fallback
        else _GROUP_INLINE_HINT
    )
    await message.reply(hint, reply_markup=markup)
