from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# Telegram InlineKeyboardButton.text 常见上限：64 个 UTF-16 码元（含增补平面字符占 2 个码元）
_INLINE_BTN_TEXT_MAX_UTF16 = 64


def _utf16_code_unit_count(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def _truncate_inline_button_text(label: str) -> str:
    s = (label or "").strip() or "."
    while s and _utf16_code_unit_count(s) > _INLINE_BTN_TEXT_MAX_UTF16:
        s = s[:-1]
    return s or "."


def build_pass_attachment_view_keyboard(*, items: list[tuple[int, str]]) -> InlineKeyboardMarkup | None:
    """
    每键绑定 qc_results.id；callback_data 仍为 qcv:pic:{id}。
    按钮文案为展示名（english_name 优先否则 employee_id），过长时截断以符合 Telegram 限制；顺序与 items 一致。
    """
    pairs = [(int(rid), str(nm)) for rid, nm in items if int(rid) > 0 and str(nm).strip()]
    if not pairs:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=_truncate_inline_button_text(nm),
                    callback_data=f"qcv:pic:{int(rid)}",
                )
            ]
            for rid, nm in pairs
        ]
    )
