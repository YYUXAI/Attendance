from __future__ import annotations

from datetime import date

# event_logs.related_event_name 用于审计通知业务键（缺失检查/补建防重）
RELATED_EVENT_NAME_AUDIT_NOTICE = "audit_notice"


def encode_shift_work_date_key(*, shift_id: int, work_date: date) -> int:
    """
    审计通知业务键编码：
    表示“某班次（shift_id）某工作日（上班日 work_date）的审计通知业务键”。

    用途：
    - 作为 event_logs.related_event_id 写入（related_event_name 固定为 'audit_notice'）
    - 缺失检查按业务语义维度防重：shift_id + work_date + notify_tg_id + template_id

    编码方式（可逆、无新字段）：
      key = shift_id * 100000000 + yyyymmdd
    """
    ymd = int(work_date.strftime("%Y%m%d"))
    return int(shift_id) * 100000000 + ymd

