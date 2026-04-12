"""
休假在班次时区下的日历日展开，与 effective_leave_days 按天写入口径一致。

提交前 B 层冲突校验（effective_leave_days）与审批同意后的写入共用本模块的展开函数，
避免两套日期算法漂移。

数据说明：本仓库不会自动清理历史上误写入 effective_leave_days 的记录（例如曾为已驳回单
错误写入生效天）。若测试中出现与已驳回单「无关」的重叠拦截，请先核对是否存在脏数据，
必要时由人工修复 effective_leave_days 后再测。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List

from zoneinfo import ZoneInfo


def iter_leave_dates_in_shift_timezone(
    start_at_utc: datetime,
    end_at_utc: datetime,
    *,
    timezone_name: str,
) -> List[date]:
    """将请假 UTC 区间按班次时区转为连续日历日列表（含首尾）。"""
    tz = ZoneInfo(timezone_name)
    sd = start_at_utc.astimezone(tz).date()
    ed = end_at_utc.astimezone(tz).date()
    out: List[date] = []
    d = sd
    while d <= ed:
        out.append(d)
        d = d + timedelta(days=1)
    return out


def leave_span_calendar_day_count(
    start_at_utc: datetime,
    end_at_utc: datetime,
    *,
    timezone_name: str,
) -> int:
    """与逐日展开长度一致的天数（含首尾）。"""
    return len(
        iter_leave_dates_in_shift_timezone(
            start_at_utc,
            end_at_utc,
            timezone_name=timezone_name,
        )
    )


def format_utc_in_shift_timezone(
    utc_dt: datetime,
    *,
    timezone_name: str,
    fmt: str = "%Y-%m-%d %H:%M:%S",
) -> str:
    """UTC 时刻按班次时区格式化，用于纯文本通知等。"""
    tz = ZoneInfo(timezone_name)
    return utc_dt.astimezone(tz).strftime(fmt)
