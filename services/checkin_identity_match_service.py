from __future__ import annotations

import re
from typing import Optional

from repositories.registrations_repo import RegistrationRow


def _norm_identity(s: str) -> str:
    t = s.strip().lower()
    if t.startswith("@"):
        t = t[1:]
    return re.sub(r"\s+", "", t)


def _norm_loose(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


def _norm_alnum(s: str) -> str:
    """仅保留字母数字（小写），用于忽略下划线/空格/大小写后的姓名比对。"""
    return re.sub(r"[^a-z0-9]", "", (s or "").strip().lower())


def _ocr_identity_blob(*, display_name: Optional[str], username_hint: Optional[str]) -> str:
    return _norm_alnum(f"{display_name or ''} {username_hint or ''}")


def _english_name_matches_blob(english_name: str, blob_alnum: str) -> bool:
    key = _norm_alnum(english_name)
    if len(key) < 3 or not blob_alnum:
        return False
    return key in blob_alnum


def _username_alnum_matches(uname: str, blob_alnum: str, *, display_name: str, hint: str) -> bool:
    u = _norm_alnum(uname)
    if len(u) < 4 or not blob_alnum:
        return False
    if u == blob_alnum or u in blob_alnum or blob_alnum in u:
        return True
    for part in (display_name, hint):
        p = _norm_alnum(part)
        if p and (p == u or u in p or p in u):
            return True
    return False


def _score_candidate(
    *,
    reg: RegistrationRow,
    display_name: Optional[str],
    username_hint: Optional[str],
) -> int:
    uname = (reg.tg_username or "").strip()
    ename = (reg.english_name or "").strip()
    disp = (display_name or "").strip()
    hint = (username_hint or "").strip()

    if not uname and not ename:
        return 0

    blob_alnum = _ocr_identity_blob(display_name=disp or None, username_hint=hint or None)
    if ename and _english_name_matches_blob(ename, blob_alnum):
        return 100
    if uname and _username_alnum_matches(uname, blob_alnum, display_name=disp, hint=hint):
        return 95

    best = 0
    uname_n = _norm_identity(uname) if uname else ""
    ename_n = _norm_loose(ename) if ename else ""
    disp_n = _norm_loose(disp) if disp else ""
    hint_n = _norm_identity(hint) if hint else ""

    if hint_n and uname_n:
        if hint_n == uname_n:
            best = max(best, 100)
        elif uname_n in hint_n or hint_n in uname_n:
            best = max(best, 85)

    if disp_n and uname_n:
        if disp_n.startswith(uname_n.lower() + " ") or disp_n == uname_n.lower():
            best = max(best, 95)
        elif uname_n.lower() in disp_n:
            best = max(best, 80)

    if disp_n and ename_n:
        if ename_n in disp_n or disp_n in ename_n:
            best = max(best, 75)

    if hint_n and ename_n:
        if hint_n == _norm_identity(ename):
            best = max(best, 70)

    # 普通 Slack 名：display「benrenxing Z」↔ tg_username「benrenxing」
    if disp_n and uname_n and uname_n in disp_n.replace(" ", ""):
        best = max(best, 90)

    return best


_OTHER_PERSON_MARKERS = ("nayxua", "朵拉", "y_ux_", "y_tc_")
_OTHER_HANDLE_RE = re.compile(r"\b(y_(?:ux|tc)_[a-z0-9]+)\b", re.IGNORECASE)
# Bot 失败回复模板，其中的 Nayxua 是上一张图结论，不是当前 Slack 浮窗
_BOT_IDENTITY_NOISE_MARKERS = (
    "打卡失败",
    "截图识别为他人",
    "请勿使用他人",
    "检测到 Telegram",
    "dsb_bot",
    "正在识别打卡",
)


def _strip_bot_identity_noise(text: str) -> str:
    earliest = len(text)
    for marker in _BOT_IDENTITY_NOISE_MARKERS:
        idx = text.find(marker)
        if 0 <= idx < earliest:
            earliest = idx
    cleaned = text[:earliest] if earliest < len(text) else text
    kept: list[str] = []
    for line in cleaned.splitlines():
        if any(m in line for m in _BOT_IDENTITY_NOISE_MARKERS):
            continue
        kept.append(line)
    return " ".join(kept).strip()


def detect_other_person_identity(
    *,
    sender: RegistrationRow,
    display_name: Optional[str],
    username_hint: Optional[str],
) -> Optional[str]:
    """
    若截图识别结果里出现他人身份线索，返回用于展示的字符串；否则 None。
    用于 trust_sender 开启时仍拒绝「代他人截图」。
    """
    disp = _strip_bot_identity_noise((display_name or "").strip())
    hint = _strip_bot_identity_noise((username_hint or "").strip())
    blob = f"{disp} {hint}".lower()
    if not blob.strip():
        return None

    if match_registration_for_sender(sender=sender, display_name=disp or None, username_hint=hint or None):
        return None

    uname = (sender.tg_username or "").lower()
    ename = (sender.english_name or "").lower()
    uname_alnum = _norm_alnum(uname)
    blob_alnum = _norm_alnum(blob)

    # 发送者用户名已在识别结果中 → 不以泛词 nayxua 误判（Bot 气泡里可能出现）
    if uname_alnum and len(uname_alnum) >= 4 and uname_alnum in blob_alnum:
        for m in _OTHER_HANDLE_RE.finditer(blob):
            token = m.group(1)
            if uname in token.lower():
                continue
            if not match_registration_for_sender(
                sender=sender, display_name=token, username_hint=token
            ):
                return disp or hint or token
        return None

    for marker in _OTHER_PERSON_MARKERS:
        if marker in blob and marker not in uname and marker not in _norm_alnum(ename):
            return disp or hint or marker

    for m in _OTHER_HANDLE_RE.finditer(blob):
        token = m.group(1)
        if match_registration_for_sender(sender=sender, display_name=token, username_hint=token):
            continue
        return disp or hint or token

    return None


def match_registration_for_sender(
    *,
    sender: RegistrationRow,
    display_name: Optional[str],
    username_hint: Optional[str],
    min_score: int = 70,
) -> bool:
    """
    校验截图中的 Slack/显示名是否与当前 Telegram 发送者注册信息一致。
    """
    if not display_name and not username_hint:
        return False

    score = _score_candidate(
        reg=sender,
        display_name=display_name,
        username_hint=username_hint,
    )
    return score >= min_score
