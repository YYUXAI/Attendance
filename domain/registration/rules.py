from __future__ import annotations

import re

_REGISTER_PROMPT_PREFIXES = ("请输入：", "请输入:", "示例：", "示例:")
_EMPLOYEE_ID_RE = re.compile(r"^\d{3,8}$")


def parse_register_input(text: str) -> tuple[str, str] | None:
    """Parse 英文名$工号. Returns (english_name, employee_id) or None."""
    raw = (text or "").strip()
    if "$" not in raw:
        return None
    left, right = raw.split("$", 1)
    english_name = normalize_english_name_for_template(left)
    employee_id = normalize_employee_id_for_template(right)
    if not english_name or not employee_id:
        return None
    if not _EMPLOYEE_ID_RE.fullmatch(employee_id):
        return None
    if len(english_name) > 64:
        return None
    return english_name, employee_id


def normalize_english_name_for_template(raw: str | None) -> str:
    """去掉误粘贴的注册提示前缀，供打卡模板/展示使用。"""
    name = (raw or "").strip()
    for prefix in _REGISTER_PROMPT_PREFIXES:
        if name.startswith(prefix):
            name = name[len(prefix) :].strip()
    if name.startswith("英文名"):
        for sep in ("：", ":"):
            if sep in name:
                name = name.split(sep, 1)[1].strip()
                break
    return name


def normalize_employee_id_for_template(raw: str | None) -> str:
    """工号只取首行数字，去掉误粘贴的「示例：…」等。"""
    text = (raw or "").strip()
    if not text:
        return ""
    first_line = text.replace("\r", "").split("\n", 1)[0].strip()
    for prefix in _REGISTER_PROMPT_PREFIXES:
        if first_line.startswith(prefix):
            first_line = first_line[len(prefix) :].strip()
    if "$" in first_line:
        first_line = first_line.split("$", 1)[-1].strip()
    m = re.search(r"\d{3,8}", first_line)
    return m.group(0) if m else first_line
