"""visible_texts 姓名纠偏：默认关闭；需显式配置群才开启。

正式 BBQ / 测试群当前均走旧姓名逻辑（AI 填名 + plan_b），
因弱模型常抄不全 visible_texts，本地选名通过率过低。
"""
from __future__ import annotations

from infra.attendance_group_policy import title_has_capability


def visible_texts_identity_enabled(
    *,
    chat_id: int | None,
    chat_title: str | None = None,
) -> bool:
    """是否启用 visible_texts 抄全 + 本地选姓名。默认关闭。"""
    del chat_id
    return title_has_capability(chat_title, "visible-texts-identity-correction")
