from __future__ import annotations


def build_supergroup_open_url(*, chat_id: int) -> str | None:
    """
    超级群组/频道打开链接（用户须已是成员）。
    chat_id 形如 -1003883297177 → https://t.me/c/3883297177
    """
    cid = int(chat_id)
    if cid >= 0:
        return None
    raw = str(cid)
    if raw.startswith("-100"):
        return f"https://t.me/c/{raw[4:]}"
    if raw.startswith("-"):
        return f"https://t.me/c/{raw[1:]}"
    return None
