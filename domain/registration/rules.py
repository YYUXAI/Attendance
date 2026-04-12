from __future__ import annotations


def parse_register_input(text: str) -> tuple[str, str] | None:
    """Parse 英文名$工号. Returns (english_name, employee_id) or None."""
    raw = (text or "").strip()
    if "$" not in raw:
        return None
    left, right = raw.split("$", 1)
    english_name = left.strip()
    employee_id = right.strip()
    if not english_name or not employee_id:
        return None
    if len(english_name) > 64 or len(employee_id) > 64:
        return None
    return english_name, employee_id
