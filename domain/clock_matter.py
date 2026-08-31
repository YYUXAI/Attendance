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


def caption_identity_conflicts_with_registration(
    *,
    caption: str | None,
    english_name: str | None,
    employee_id: str | None,
) -> bool:
    """配文若含英文名或工号，必须与当前发送者注册信息一致。"""
    cap_en = parse_english_name_from_text(caption)
    cap_eid = parse_employee_id_from_text(caption)
    if not cap_en and not cap_eid:
        return False
    reg_en = (english_name or "").strip()
    reg_eid = str(employee_id or "").strip()
    if cap_en and reg_en and cap_en.casefold() != reg_en.casefold():
        return True
    if cap_eid and reg_eid and cap_eid != reg_eid:
        return True
    return False


def validate_caption_identity_for_sender(
    *,
    caption: str | None,
    english_name: str | None,
    employee_id: str | None,
) -> str | None:
    """
    校验配文身份是否属于当前发送者。
    返回 None 表示通过；否则返回错误码 CAPTION_IDENTITY_MISMATCH。
    """
    text = caption or ""
    cap_en = parse_english_name_from_text(text)
    cap_eid = parse_employee_id_from_text(text)
    reg_en = (english_name or "").strip()
    reg_eid = str(employee_id or "").strip()
    uses_checkin_template = "#打卡" in text or bool(cap_en or cap_eid)

    if caption_identity_conflicts_with_registration(
        caption=text,
        english_name=reg_en,
        employee_id=reg_eid,
    ):
        return "CAPTION_IDENTITY_MISMATCH"

    if uses_checkin_template and reg_en and reg_eid:
        if not cap_en or not cap_eid:
            return "CAPTION_IDENTITY_MISMATCH"
        if not caption_identity_matches_registration(
            caption=text,
            english_name=reg_en,
            employee_id=reg_eid,
        ):
            return "CAPTION_IDENTITY_MISMATCH"

    return None


def validate_caption_for_remote_diff(
    *,
    caption: str | None,
    employee_id: str | None,
) -> str | None:
    """
    工号测试群：只校验配文工号（若有），不要求英文名。
    返回 None 表示通过；否则 CAPTION_IDENTITY_MISMATCH。
    """
    text = caption or ""
    cap_eid = parse_employee_id_from_text(text)
    reg_eid = str(employee_id or "").strip()
    if cap_eid and reg_eid and cap_eid != reg_eid:
        return "CAPTION_IDENTITY_MISMATCH"
    uses_checkin_template = "#打卡" in text or bool(cap_eid)
    if uses_checkin_template and reg_eid and not cap_eid:
        return "CAPTION_IDENTITY_MISMATCH"
    return None


def first_valid_action_in_text(text: str | None) -> str | None:
    """配文中按出现顺序取第一个「签到」或「签退」。"""
    if not text:
        return None
    hits: list[tuple[int, str]] = []
    for action in (ACTION_SIGN_IN, ACTION_SIGN_OUT):
        idx = text.find(action)
        if idx >= 0:
            hits.append((idx, action))
    if not hits:
        return None
    hits.sort(key=lambda item: item[0])
    return hits[0][1]


def _strip_wrapping_parens(text: str) -> str:
    s = (text or "").strip()
    if len(s) >= 2 and (
        (s[0] == "(" and s[-1] == ")") or (s[0] == "（" and s[-1] == "）")
    ):
        return s[1:-1].strip()
    return s


def parse_matter_note_from_text(text: str | None) -> str | None:
    """事项行在「签到/签退」之后的备注。无备注返回 None。"""
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
        action = val if val in VALID_ACTIONS else first_valid_action_in_text(val)
        if not action:
            return None
        rest = val[val.find(action) + len(action) :].strip()
        rest = rest.lstrip("：:").strip()
        rest = _strip_wrapping_parens(rest)
        return rest or None
    return None


def format_export_status_with_note(status: str, note: str | None) -> str:
    st = (status or "").strip()
    n = _strip_wrapping_parens(note or "")
    if not n:
        return st
    return f"{st}（{n}）"


def parse_matter_from_text(
    text: str | None,
    *,
    allow_embedded: bool = False,
) -> str | None:
    """从 #打卡 模板或配文中解析「事项：签到/签退」。

    allow_embedded=True 时（QDYYZ）：事项值或整段配文含「签到」「签退」字样即可，
    不要求事项整段恰好等于这两个字。
    """
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
        if allow_embedded:
            embedded = first_valid_action_in_text(val)
            if embedded:
                return embedded
    if allow_embedded:
        return first_valid_action_in_text(text)
    return None
