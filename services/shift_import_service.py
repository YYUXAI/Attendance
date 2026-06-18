from __future__ import annotations

import re
from datetime import datetime, time
from typing import Any

from repositories import employee_shift_config_repo

_YM_RE = re.compile(r"^\d{4}-\d{2}$")

# 导入/导出模板表头（中文）；导入时仍兼容旧英文表头
TEMPLATE_HEADERS_CN = ["日期", "工号", "英文名", "班次", "上班时间", "下班时间", "月休"]

# 考勤汇总导出（私聊「导出」、群 23:00 CSV）
ATTENDANCE_EXPORT_HEADERS_CN = [
    "群名",
    "工号",
    "英文名",
    "班次",
    "上班时间",
    "下班时间",
    "离岗时间",
    "状态",
]

# 全局打卡日报 CSV
DAILY_REPORT_HEADERS_CN = ["工号", "英文名", "班次", "上班时间", "下班时间"]

_COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "year_month": ("日期", "year_month", "月份", "month"),
    "employee_id": ("工号", "employee_id", "员工工号"),
    "english_name": ("英文名", "english_name", "english name", "name"),
    "shift_time_range": ("班次", "shift_time_range", "班次时段", "时段"),
    "shift_checkin_time": ("上班时间", "shift_checkin_time", "上班", "签到", "checkin"),
    "shift_checkout_time": ("下班时间", "shift_checkout_time", "下班", "签退", "checkout"),
    "monthly_rest_days": ("月休", "monthly_rest_days", "休息"),
}


def normalize_year_month(raw: str, *, default: str | None = None) -> str:
    s = (raw or "").strip()
    if _YM_RE.fullmatch(s):
        return s
    m = re.match(r"^(\d{2})-([A-Za-z]{3})(?:-(\d{4}))?$", s, re.I)
    if m:
        yy = int(m.group(1))
        mon = m.group(2).title()
        year = int(m.group(3)) if m.group(3) else (2000 + yy if yy < 100 else yy)
        dt = datetime.strptime(f"{mon}-{year}", "%b-%Y")
        return dt.strftime("%Y-%m")
    if default and _YM_RE.fullmatch(default):
        return default
    raise ValueError(f"无法识别月份: {raw!r}，请用 YYYY-MM")


def normalize_rest_days(raw: str) -> str:
    s = (raw or "").strip().replace("，", ",").replace("、", ",")
    parts: list[str] = []
    for p in s.split(","):
        p = p.strip()
        if not p:
            continue
        try:
            d = int(p)
        except ValueError:
            continue
        if 1 <= d <= 31:
            parts.append(str(d))
    return ",".join(parts)


def parse_time_value(raw: str) -> time:
    s = (raw or "").strip()
    if not s:
        raise ValueError("时间为空")
    parts = s.split(":")
    try:
        if len(parts) == 2:
            return time(int(parts[0]), int(parts[1]))
        if len(parts) >= 3:
            return time(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError as e:
        raise ValueError(f"时间格式错误: {raw!r}") from e
    raise ValueError(f"时间格式错误: {raw!r}")


def _canonical_key(header: str) -> str | None:
    h = (header or "").strip().lower()
    for key, aliases in _COLUMN_ALIASES.items():
        for alias in aliases:
            if h == alias.lower():
                return key
    return None


def normalize_row_dict(raw: dict[str, Any], *, default_year_month: str) -> dict[str, str]:
    mapped: dict[str, str] = {}
    for k, v in raw.items():
        ck = _canonical_key(str(k))
        if ck:
            mapped[ck] = str(v).strip() if v is not None else ""
    ym = mapped.get("year_month") or default_year_month
    year_month = normalize_year_month(ym, default=default_year_month)
    employee_id = mapped.get("employee_id", "")
    english_name = mapped.get("english_name", "")
    if not employee_id or not english_name:
        raise ValueError("工号、英文名不能为空")
    cin = parse_time_value(mapped.get("shift_checkin_time", ""))
    cout = parse_time_value(mapped.get("shift_checkout_time", ""))
    rng = mapped.get("shift_time_range", "").strip()
    if not rng:
        rng = f"{cin.strftime('%H:%M')}~{cout.strftime('%H:%M')}"
    rest = normalize_rest_days(mapped.get("monthly_rest_days", ""))
    return {
        "year_month": year_month,
        "employee_id": employee_id,
        "english_name": english_name,
        "shift_time_range": rng,
        "shift_checkin_time": cin.strftime("%H:%M:%S"),
        "shift_checkout_time": cout.strftime("%H:%M:%S"),
        "monthly_rest_days": rest,
    }


def import_row_dicts(
    *,
    rows: list[dict[str, Any]],
    default_year_month: str,
    force_year_month: bool = False,
) -> tuple[int, str, list[str]]:
    """批量导入/保存；返回 (成功条数, 实际月份, 错误列表)。

    force_year_month=True 时（Web 批量导入）：所有行写入 default_year_month，
    全量同步删除也仅针对该月，避免表格「日期」列填了日号等导致写入别月、当前月仍为空。
    """
    if not _YM_RE.fullmatch(default_year_month):
        raise ValueError("invalid year_month")
    employee_shift_config_repo.ensure_table()
    errors: list[str] = []
    saved = 0
    ym_sync = default_year_month
    ym_last = default_year_month
    kept_ids: list[str] = []

    for i, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            continue
        if not any(str(v or "").strip() for v in raw.values()):
            continue
        try:
            norm = normalize_row_dict(raw, default_year_month=default_year_month)
        except ValueError as e:
            errors.append(f"第 {i} 行: {e}")
            continue
        if force_year_month:
            norm["year_month"] = default_year_month
        ym_last = norm["year_month"]
        cin = parse_time_value(norm["shift_checkin_time"])
        cout = parse_time_value(norm["shift_checkout_time"])
        employee_shift_config_repo.upsert_config(
            year_month=ym_last,
            employee_id=norm["employee_id"],
            english_name=norm["english_name"],
            shift_time_range=norm["shift_time_range"],
            shift_checkin_time=cin,
            shift_checkout_time=cout,
            monthly_rest_days=norm["monthly_rest_days"],
        )
        kept_ids.append(norm["employee_id"])
        saved += 1

    if not errors:
        employee_shift_config_repo.delete_not_in(
            year_month=ym_sync if force_year_month else ym_last,
            employee_ids=kept_ids,
        )
    return saved, ym_sync, errors


def template_csv_bytes(*, year_month: str) -> bytes:
    import codecs
    import csv
    import io

    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(TEMPLATE_HEADERS_CN)
    writer.writerow(
        [
            year_month,
            "17025",
            "Brucewillis",
            "13:00~22:00",
            "13:00",
            "22:00",
            "1,2,3,4",
        ]
    )
    return codecs.BOM_UTF8 + buf.getvalue().encode("utf-8")


def _format_time_cell(value: object) -> str:
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M:%S")  # type: ignore[union-attr]
    raw = str(value).strip()
    if len(raw) == 5 and ":" in raw:
        return raw + ":00"
    return raw


def encode_shift_config_csv(*, year_month: str, rows: list) -> bytes:
    """导出当月班次配置表（表头与导入模板一致）。"""
    import codecs
    import csv
    import io

    buf = io.StringIO(newline="")
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(TEMPLATE_HEADERS_CN)
    for row in rows:
        cin = getattr(row, "shift_checkin_time", None)
        cout = getattr(row, "shift_checkout_time", None)
        if isinstance(row, dict):
            writer.writerow(
                [
                    year_month,
                    str(row.get("employee_id") or ""),
                    str(row.get("english_name") or ""),
                    str(row.get("shift_time_range") or ""),
                    _format_time_cell(row.get("shift_checkin_time")),
                    _format_time_cell(row.get("shift_checkout_time")),
                    str(row.get("monthly_rest_days") or ""),
                ]
            )
        else:
            writer.writerow(
                [
                    year_month,
                    str(row.employee_id),
                    str(row.english_name),
                    str(row.shift_time_range),
                    _format_time_cell(cin),
                    _format_time_cell(cout),
                    str(row.monthly_rest_days or ""),
                ]
            )
    return codecs.BOM_UTF8 + buf.getvalue().encode("utf-8")
