from __future__ import annotations

# 已下线模块（docs05 模板号段）：
# - 1000-1999：报备休息、私聊离岗审批、审批人待办/结果/群公告
# - 2000-2999：质检（QC）全流程通知
DISABLED_NOTIFICATION_TEMPLATE_RANGES: tuple[tuple[int, int], ...] = (
    (1000, 1999),
    (2000, 2999),
)


def is_disabled_notification_template(template_id: int) -> bool:
    tid = int(template_id)
    for lo, hi in DISABLED_NOTIFICATION_TEMPLATE_RANGES:
        if lo <= tid <= hi:
            return True
    return False
