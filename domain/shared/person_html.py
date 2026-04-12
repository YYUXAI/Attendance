from __future__ import annotations

import html
from typing import Optional
from urllib.parse import quote


def person_display_html(
    *,
    english_name: Optional[str],
    tg_username: Optional[str],
    missing_name_fallback: str = "（未填英文名）",
) -> str:
    """
    对外通知中的人员展示规则（HTML）：
    - 优先展示 registrations.english_name
    - 若同时存在 tg_username，则展示为可点击链接
      例如：<a href="https://t.me/xxx">EnglishName</a>
    - 若没有 tg_username，则仅显示 english_name
    - english_name 缺失时使用明确的 fallback（默认：未填英文名）
    """
    name_raw = (english_name or "").strip()
    if not name_raw:
        return html.escape(missing_name_fallback)

    uname = (tg_username or "").strip().lstrip("@") or None
    name = html.escape(name_raw)
    if not uname:
        return name

    href_user = quote(uname, safe="")
    return f'<a href="https://t.me/{href_user}">{name}</a>'

