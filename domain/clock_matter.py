from __future__ import annotations

ACTION_SIGN_IN = "签到"
ACTION_SIGN_OUT = "签退"
VALID_ACTIONS = frozenset({ACTION_SIGN_IN, ACTION_SIGN_OUT})


def _parse_labeled_field(text: str | None, label: str) -> str | None:
    """从模板行解析「标签：值」。"""
    if not text:
        return None
    for line in text.replace("\r", "").split("\n"):
        s = line.strip()
        if not s.startswith(label):
            continue
        if "：" in s:
            val = s.split("：", 1)[1].strip()
        elif ":" in s:
            val = s.split(":", 1)[1].strip()
        else:
            continue
        return val if val else None
    return None


def parse_english_name_from_text(text: str | None) -> str | None:
    return _parse_labeled_field(text, "英文名")


def parse_employee_id_from_text(text: str | None) -> str | None:
    return _parse_labeled_field(text, "工号")


def caption_identity_matches_registration(
    *,
    caption: str | None,
    english_name: str | None,
    employee_id: str | None,
) -> bool:
    """配文模板中的英文名、工号均与注册信息一致时，可信任发送者身份。"""
    cap_en = parse_english_name_from_text(caption)
    cap_eid = parse_employee_id_from_text(caption)
    reg_en = (english_name or "").strip()
    reg_eid = str(employee_id or "").strip()
    if not cap_en or not cap_eid or not reg_en or not reg_eid:
        return False
    return cap_en.casefold() == reg_en.casefold() and cap_eid == reg_eid


def parse_matter_from_text(text: str | None) -> str | None:
    """从 #打卡 模板或配文中解析「事项：签到/签退」。"""
    if not text:
        return None
    for line in text.replace("\r", "").split("\n"):
        s = line.strip()
        if not s.startswith("事项"):
            continue
        if "：" in s:
            val = s.split("：", 1)[1].strip()
        elif ":" in s:
            val = s.split(":", 1)[1].strip()
        else:
            continue
        if val in VALID_ACTIONS:
            return val
    return None
