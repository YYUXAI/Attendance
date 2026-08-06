"""世界杯班次代码 → 上下班时间（统筹部排班表图例默认映射）。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True)
class ShiftCodeRange:
    code: str
    checkin: time
    checkout: time

    @property
    def time_range_display(self) -> str:
        cin = self.checkin.strftime("%H:%M")
        cout = self.checkout.strftime("%H:%M")
        return f"{cin}~{cout}"


_DEFAULT_CODES: dict[str, tuple[str, str]] = {
    "WR": ("06:00", "18:00"),
    "WA": ("07:00", "19:00"),
    "WB": ("08:00", "20:00"),
    "WC": ("09:00", "21:00"),
    "WD": ("10:00", "22:00"),
    "WE": ("11:00", "23:00"),
    "WF": ("12:00", "00:00"),
    "WG": ("13:00", "01:00"),
    "WH": ("14:00", "02:00"),
    "WI": ("15:00", "03:00"),
    "WJ": ("16:00", "04:00"),
    "WK": ("17:00", "05:00"),
    "WL": ("18:00", "06:00"),
    "WM": ("19:00", "07:00"),
    "WN": ("20:00", "08:00"),
    "WO": ("21:00", "09:00"),
    "WP": ("22:00", "10:00"),
    "WQ": ("23:00", "11:00"),
    "WX": ("05:00", "17:00"),
    "WY": ("06:00", "15:00"),
}

# 统筹部排班表图例单字母班次（与 W 前缀 12h 班不同，多为 9h）
_SINGLE_LETTER_CODES: dict[str, tuple[str, str]] = {
    "R": ("00:00", "09:00"),
    "S": ("01:00", "10:00"),
    "X": ("05:00", "14:00"),
    "Y": ("06:00", "15:00"),
    "A": ("07:00", "16:00"),
    "B": ("08:00", "17:00"),
    "C": ("09:00", "18:00"),
    "D": ("10:00", "19:00"),
    "E": ("11:00", "20:00"),
    "F": ("12:00", "21:00"),
    "G": ("13:00", "22:00"),
    "H": ("14:00", "23:00"),
    "I": ("15:00", "00:00"),
    "J": ("16:00", "01:00"),
    "K": ("17:00", "02:00"),
    "L": ("18:00", "03:00"),
    "M": ("19:00", "04:00"),
    "N": ("20:00", "05:00"),
    "O": ("21:00", "06:00"),
    "P": ("22:00", "07:00"),
    "Q": ("23:00", "08:00"),
}

_TIME_RANGE_RE = re.compile(
    r"(\d{1,2}:\d{2})\s*[-~～至到]\s*(\d{1,2}:\d{2})",
    re.I,
)
_W_CODE_RE = re.compile(r"^W[A-Z]$")
_SINGLE_CODE_RE = re.compile(r"^[A-Z]$")
_LEGEND_CODE_RE = re.compile(r"^(?:W[A-Z]|[A-Z])$")


def _parse_hm(raw: str) -> time:
    parts = raw.strip().split(":")
    return time(int(parts[0]), int(parts[1]))


def default_shift_catalog() -> dict[str, ShiftCodeRange]:
    out: dict[str, ShiftCodeRange] = {}
    merged = {**_SINGLE_LETTER_CODES, **_DEFAULT_CODES}
    for code, (cin, cout) in merged.items():
        out[code] = ShiftCodeRange(code=code, checkin=_parse_hm(cin), checkout=_parse_hm(cout))
    return out


def parse_time_range_text(text: str) -> tuple[time, time] | None:
    m = _TIME_RANGE_RE.search(text or "")
    if not m:
        return None
    return _parse_hm(m.group(1)), _parse_hm(m.group(2))


def merge_legend_from_sheet_rows(
    rows: list[list[str]],
    *,
    base: dict[str, ShiftCodeRange] | None = None,
) -> dict[str, ShiftCodeRange]:
    """从表格顶部图例行补充/覆盖班次时段。"""
    catalog = dict(base or default_shift_catalog())
    for row in rows[:20]:
        cells = [str(c or "").strip() for c in row]
        for i, cell in enumerate(cells):
            up = cell.upper()
            if not _LEGEND_CODE_RE.fullmatch(up):
                continue
            window = ""
            if i + 1 < len(cells):
                window = cells[i + 1]
            if not window and i + 2 < len(cells):
                window = f"{cells[i + 1]} {cells[i + 2]}"
            parsed = parse_time_range_text(window)
            if parsed:
                cin, cout = parsed
                catalog[up] = ShiftCodeRange(code=up, checkin=cin, checkout=cout)
    return catalog


def lookup_shift(code: str, catalog: dict[str, ShiftCodeRange]) -> ShiftCodeRange | None:
    key = (code or "").strip().upper()
    if not key:
        return None
    return catalog.get(key)
