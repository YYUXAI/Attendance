from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal


def safe_csv_cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    text = str(value)
    if text.startswith(("\t", "\r")) or text.lstrip(" \t\r\n").startswith(
        ("=", "+", "-", "@")
    ):
        return "'" + text
    return text
