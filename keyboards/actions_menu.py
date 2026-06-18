from __future__ import annotations

from aiogram.types import Message

from infra.shift_web_config import build_shift_web_app_url, current_year_month, load_shift_web_config
from services.shift_web_session import create_session
from keyboards.group_actions import build_single_action_inline_or_callback
from keyboards.main_menu import build_group_reply_keyboard, build_private_reply_keyboard
from repositories import registrations_repo
MENU_TEXT = "请选择功能（使用输入框下方按钮；输入 / 可打开命令）："
# 群聊：输入框下方常驻四键（ReplyKeyboard）提示文案
GROUP_REPLY_MENU_TEXT = "功能菜单（底部按钮或 /start）"
# 群聊单键 Inline（带 ↗ 填入模板）提示
_GROUP_INLINE_HINT = "请点击下方按钮操作"


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
    # 群聊目标效果：仅弹出输入框下方 2×2 常驻键（签到/签退/离岗/返岗），不附带消息内 Inline 四宫格
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
    if not reg:
        markup = build_single_action_inline_or_callback(action=action)
        await message.reply("请先私聊机器人完成注册（英文名$工号）。", reply_markup=markup)
        return
    name = (reg.english_name or "").strip() or "未命名"
    markup = build_single_action_inline_or_callback(
        action=action,
        english_name=name,
        employee_id=str(reg.employee_id),
    )
    await message.reply(_GROUP_INLINE_HINT, reply_markup=markup)
