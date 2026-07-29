from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
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


def _norm_ocr_confusable(s: str) -> str:
    """OCR 易混字母归一：仅 i 视为 l（如 Nigelito ↔ Nlgelito），不改动数字。"""
    return _norm_alnum(s).replace("i", "l")


def _identity_matches_blob(*, needle: str, blob_alnum: str, min_len: int) -> bool:
    """姓名/用户名与识别 blob 比对：先精确包含，再 OCR 模糊 + 相似度。"""
    key = _norm_alnum(needle)
    if len(key) < min_len or not blob_alnum:
        return False
    if key in blob_alnum or blob_alnum in key:
        return True

    key_o = _norm_ocr_confusable(needle)
    blob_o = _norm_ocr_confusable(blob_alnum)
    if key_o in blob_o or blob_o in key_o:
        return True
    if len(key_o) >= min_len and _alnum_similar(key_o, blob_o, min_len=min_len, threshold=0.84):
        return True
    if len(key_o) >= min_len:
        for start in range(0, max(1, len(blob_o) - len(key_o) + 1)):
            chunk = blob_o[start : start + len(key_o) + 2]
            if key_o in chunk or _alnum_similar(key_o, chunk, min_len=min_len, threshold=0.84):
                return True
    return False


def _alnum_similar(a: str, b: str, *, min_len: int = 8, threshold: float = 0.84) -> bool:
    """OCR 易漏下划线、多/少字母（如 Brucewillis→Brucewillls）时仍视为同一人。"""
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    if min(len(a), len(b)) < min_len:
        return False
    return SequenceMatcher(None, a, b).ratio() >= threshold


def _ocr_identity_blob(*, display_name: Optional[str], username_hint: Optional[str]) -> str:
    return _norm_alnum(f"{display_name or ''} {username_hint or ''}")


def _english_core(s: str) -> str:
    """去掉 Y_UX_ / Y_TC_ 等前缀，只比英文名本体。"""
    a = _norm_alnum(s)
    for prefix in ("yux", "ytc"):
        if a.startswith(prefix):
            return a[len(prefix) :]
    return a


def _alnum_contains_either(a: str, b: str) -> bool:
    return bool(a and b and (a in b or b in a))


def _english_name_matches_blob(english_name: str, blob_alnum: str) -> bool:
    """注册英文名与识别 blob：互相包含即可（含 OCR i/l 归一）。"""
    key = _norm_alnum(english_name)
    if len(key) < 3 or not blob_alnum:
        return False
    if _alnum_contains_either(key, blob_alnum):
        return True

    key_o = _norm_ocr_confusable(english_name)
    blob_o = _norm_ocr_confusable(blob_alnum)
    if _alnum_contains_either(key_o, blob_o):
        return True

    key_c = _english_core(english_name)
    if len(key_c) >= 3:
        blob_c = _english_core(blob_alnum)
        if _alnum_contains_either(key_c, blob_c):
            return True
        if _alnum_contains_either(key_c, blob_o):
            return True

    if len(key) >= 6 and _alnum_similar(key, blob_alnum, min_len=6):
        return True
    if len(key) >= 6:
        for start in range(0, max(1, len(blob_alnum) - len(key) + 1)):
            chunk = blob_alnum[start : start + len(key) + 2]
            if key in chunk or _alnum_similar(key, chunk, min_len=6):
                return True
    return False


def _username_alnum_matches(uname: str, blob_alnum: str, *, display_name: str, hint: str) -> bool:
    u = _norm_alnum(uname)
    if len(u) < 4 or not blob_alnum:
        return False
    if u == blob_alnum or u in blob_alnum or blob_alnum in u:
        return True
    if _alnum_similar(u, blob_alnum):
        return True
    for part in (display_name, hint):
        p = _norm_alnum(part)
        if not p:
            continue
        if p == u or u in p or p in u:
            return True
        if _alnum_similar(u, p):
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
    disp = _strip_bot_identity_noise((display_name or "").strip())
    hint = _strip_bot_identity_noise((username_hint or "").strip())

    if not uname and not ename:
        return 0

    blob_alnum = _ocr_identity_blob(display_name=disp or None, username_hint=hint or None)
    if ename and _english_name_matches_blob(ename, blob_alnum):
        return 100
    if uname and _username_alnum_matches(uname, blob_alnum, display_name=disp, hint=hint):
        return 95
    if uname and blob_alnum and _alnum_similar(_norm_alnum(uname), blob_alnum):
        return 92

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
    "@zpxinbot",
    "#打卡",
    "#离岗报备",
    "#返岗报备",
    "事项：",
    "英文名：",
    "工号：",
    "人员：",
    "时间：",
    "原因：",
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


def _literal_in_raw(value: str, raw: str) -> bool:
    """字段值须在模型原文中出现（含归一化子串）。"""
    if not value or not raw:
        return False
    v = value.strip()
    if v in raw:
        return True
    vn = _norm_alnum(v)
    rn = _norm_alnum(raw)
    return bool(vn) and vn in rn


def match_expected_sender(
    *,
    display_name: Optional[str],
    username_hint: Optional[str],
    tg_username: Optional[str],
    english_name: Optional[str],
) -> bool:
    """仅比对发送者登记用户名/英文名，无需完整 RegistrationRow。"""
    sender = RegistrationRow(
        id=0,
        employee_id="",
        tg_id=0,
        english_name=(english_name or None),
        tg_username=(tg_username or None),
        registered_chat_id=None,
        organization_id=None,
        shift_id=None,
    )
    return match_registration_for_sender(
        sender=sender,
        display_name=display_name,
        username_hint=username_hint,
    )


def sender_identity_present_in_raw(
    *,
    raw: str,
    tg_username: Optional[str],
    english_name: Optional[str],
) -> bool:
    """发送者登记身份是否出现在 AI 全文任意位置。"""
    if not (raw or "").strip():
        return False
    blob_alnum = _norm_alnum(raw)
    uname = (tg_username or "").strip().lstrip("@")
    ename = (english_name or "").strip()
    if uname and _identity_matches_blob(needle=uname, blob_alnum=blob_alnum, min_len=4):
        return True
    if ename and _identity_matches_blob(needle=ename, blob_alnum=blob_alnum, min_len=3):
        return True
    return False


def _expand_display_around_ename(raw: str, ename: str) -> Optional[str]:
    low = raw.lower()
    el = ename.lower()
    idx = low.find(el)
    if idx < 0:
        return None
    start = idx
    while start > 0 and raw[start - 1] not in " \n\t\",{[]":
        start -= 1
    end = idx + len(ename)
    while end < len(raw) and raw[end] not in " \n\t\",{[]":
        end += 1
    snippet = raw[start:end].strip().strip('"').strip("'")
    if snippet and _literal_in_raw(snippet, raw):
        return snippet
    return None


def _hint_from_raw_for_username(raw: str, uname: str) -> Optional[str]:
    if not uname:
        return None
    low_raw = raw.lower()
    low_u = uname.lower().lstrip("@")
    idx = low_raw.find(low_u)
    if idx >= 0:
        snippet = raw[idx : idx + len(uname)]
        if _literal_in_raw(snippet, raw):
            return snippet.lstrip("@").lower()
    if _literal_in_raw(uname, raw):
        return uname.lstrip("@").lower()
    return None


def extract_grounded_sender_identity_from_raw(
    *,
    raw: str,
    tg_username: Optional[str],
    english_name: Optional[str],
) -> Optional[tuple[str, str]]:
    """
    在 AI 全文里只找发送者本人；找到则返回可在原文 grounding 的 (display, hint)。
    找不到发送者则返回 None（不强行填登记名）。
    """
    if not sender_identity_present_in_raw(
        raw=raw,
        tg_username=tg_username,
        english_name=english_name,
    ):
        return None

    uname = (tg_username or "").strip().lstrip("@")
    ename = (english_name or "").strip()
    display_out: Optional[str] = None
    hint_out: Optional[str] = None

    for m in _OTHER_HANDLE_RE.finditer(raw):
        token = m.group(1)
        if match_expected_sender(
            display_name=token,
            username_hint=token,
            tg_username=tg_username,
            english_name=english_name,
        ):
            if _literal_in_raw(token, raw):
                display_out = token
                hint_out = token.lstrip("@").lower()
                break

    if not hint_out and uname:
        hint_out = _hint_from_raw_for_username(raw, uname)

    if not display_out and ename:
        display_out = _expand_display_around_ename(raw, ename)

    if not display_out and hint_out and _literal_in_raw(hint_out, raw):
        display_out = hint_out

    if not hint_out and display_out and _literal_in_raw(display_out, raw):
        hint_out = display_out.lstrip("@").lower()

    if not display_out and not hint_out:
        return None

    if display_out and not _literal_in_raw(display_out, raw):
        display_out = None
    if hint_out and not _literal_in_raw(hint_out, raw):
        hint_out = None
    if not display_out and not hint_out:
        return None
    return display_out or "", hint_out or ""


_ATTENDANCE_GROUP_NOISE_RE = re.compile(
    r"y[-_ ]?ux[-_ ]?kq[a-z0-9]*|y[-_ ]?ux[-_ ]?dkq|yymg[-_ ]?dkq",
    re.IGNORECASE,
)
_ATTENDANCE_GROUP_NOISE_ALNUM = frozenset(
    {"kqbbq", "kqbqq", "kqbhq", "kqbb", "yymg", "dkqnew", "dkq"}
)


def is_attendance_group_identity_noise(
    display_name: Optional[str],
    username_hint: Optional[str],
) -> bool:
    """方案 B：识别结果是否像考勤群名/群标题误读。"""
    for val in (display_name, username_hint):
        if not (val or "").strip():
            continue
        text = val.strip()
        low = text.lower()
        alnum = _norm_alnum(text)
        if _ATTENDANCE_GROUP_NOISE_RE.search(low):
            return True
        if any(marker in alnum for marker in _ATTENDANCE_GROUP_NOISE_ALNUM):
            return True
        if "考勤" in text and "y_ux_" not in low and "y-ux-" not in low:
            return True
    return False


def strip_group_name_noise_fields(
    *,
    display_name: Optional[str],
    username_hint: Optional[str],
) -> tuple[Optional[str], Optional[str]]:
    """只清掉为群名噪声的字段，保留非噪声字段（如本人姓名）。"""
    disp = display_name
    hint = username_hint
    if is_attendance_group_identity_noise(None, hint):
        hint = None
    if is_attendance_group_identity_noise(disp, None):
        disp = None
    return disp, hint


_UI_IDENTITY_NOISE_RE = re.compile(
    r"("
    r"macos|新功能|登录项|扩展|"
    r"time\.?is|现在的北京|将北京时间|"
    r"更改表情|emoji\s*status|set emoji|"
    r"my profile|new group|new channel|saved messages|night mode|"
    r"world population|independence day|更多信息|取消关注"
    r")",
    re.IGNORECASE,
)


def is_ui_identity_noise(text: Optional[str]) -> bool:
    """系统通知/菜单/网页装饰文案，不能当姓名。"""
    t = (text or "").strip()
    if not t:
        return False
    if _UI_IDENTITY_NOISE_RE.search(t):
        return True
    # 纯中文说明句且不含 Y_UX / 英文名形态
    if re.search(r"[\u4e00-\u9fff]", t) and not re.search(r"[A-Za-z]{3,}", t):
        if any(k in t for k in ("查看", "管理", "设置", "功能", "通知")):
            return True
    return False


def parse_visible_texts_from_payload(data: object) -> list[str]:
    """从模型 JSON 中提取 visible_texts。"""
    if not isinstance(data, dict):
        return []
    raw = data.get("visible_texts")
    if raw is None:
        return []
    out: list[str] = []
    if isinstance(raw, str):
        parts = [p.strip() for p in re.split(r"[\n|;]+", raw) if p.strip()]
        raw_list: list[object] = parts
    elif isinstance(raw, list):
        raw_list = raw
    else:
        return []
    seen: set[str] = set()
    for item in raw_list:
        if item is None:
            continue
        s = str(item).strip()
        if not s or s.lower() in {"null", "none"}:
            continue
        key = _norm_alnum(s) or s.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= 40:
            break
    return out


def parse_visible_texts_from_raw(raw: str) -> list[str]:
    if not (raw or "").strip():
        return []
    payload = raw.strip()
    if payload.startswith("```"):
        payload = re.sub(r"^```(?:json)?\s*", "", payload)
        payload = re.sub(r"\s*```$", "", payload)
    try:
        data = json.loads(payload)
    except Exception:
        repaired = re.sub(r",\s*([}\]])", r"\1", payload)
        try:
            data = json.loads(repaired)
        except Exception:
            return []
    return parse_visible_texts_from_payload(data)


def pick_sender_identity_from_visible_texts(
    *,
    visible_texts: list[str],
    tg_username: Optional[str],
    english_name: Optional[str],
) -> Optional[tuple[str, str]]:
    """
    从可见字符串列表中挑选发送者身份。
    命中本人则返回 (display, hint)；未命中返回 None（不回填登记名）。
    """
    if not visible_texts:
        return None
    best: Optional[tuple[int, str, str]] = None
    for text in visible_texts:
        if is_ui_identity_noise(text):
            continue
        if is_attendance_group_identity_noise(text, text):
            continue
        if not match_expected_sender(
            display_name=text,
            username_hint=text,
            tg_username=tg_username,
            english_name=english_name,
        ):
            continue
        # 更长、更像完整 handle 的优先
        score = len(_norm_alnum(text))
        if re.search(r"y[_-]?ux[_-]?", text, re.IGNORECASE):
            score += 20
        hint = text.lstrip("@").split()[0] if text.strip() else text
        cand = (score, text.strip(), hint)
        if best is None or cand[0] > best[0]:
            best = cand
    if best is None:
        return None
    return best[1], best[2]


def apply_visible_texts_identity(
    *,
    display_name: Optional[str],
    username_hint: Optional[str],
    visible_texts: list[str],
    tg_username: Optional[str],
    english_name: Optional[str],
) -> tuple[Optional[str], Optional[str], str]:
    """
    用 visible_texts 纠正姓名（严格）：姓名只能来自可见列表，禁止沿用 AI 自填。

    返回 (display, hint, action)：
    - picked: 从可见列表选中本人
    - cleared_ungrounded: 列表无本人 → 清空（含 AI 幻觉登记名、UI 噪声）
    - keep: 列表无本人且 AI 也未填姓名
    """
    picked = pick_sender_identity_from_visible_texts(
        visible_texts=visible_texts,
        tg_username=tg_username,
        english_name=english_name,
    )
    if picked is not None:
        return picked[0], picked[1], "picked"

    # 图上列表找不到本人：一律清空，禁止 AI 凭 prompt 登记身份「编」出姓名后通过校验
    if display_name or username_hint:
        return None, None, "cleared_ungrounded"
    return None, None, "keep"


@dataclass(frozen=True)
class PlanBSenderIdentityResult:
    display_name: str
    username_hint: str


def resolve_sender_identity_plan_b(
    *,
    display_name: Optional[str],
    username_hint: Optional[str],
    raw: str,
    tg_username: Optional[str],
    english_name: Optional[str],
) -> Optional[PlanBSenderIdentityResult]:
    """
    方案 B：群名噪声时丢弃误读，仅当 AI 全文里真有发送者身份才纠正回填。
    只有群名、没有本人 → 不回填登记名（必须失败）。
    """
    if match_expected_sender(
        display_name=display_name,
        username_hint=username_hint,
        tg_username=tg_username,
        english_name=english_name,
    ):
        return None

    resolved = extract_grounded_sender_identity_from_raw(
        raw=raw,
        tg_username=tg_username,
        english_name=english_name,
    )
    if resolved is None:
        return None

    display_out, hint_out = resolved
    return PlanBSenderIdentityResult(
        display_name=display_out or "",
        username_hint=hint_out or "",
    )


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

    del min_score
    disp = _strip_bot_identity_noise((display_name or "").strip())
    hint = _strip_bot_identity_noise((username_hint or "").strip())
    blob_alnum = _ocr_identity_blob(display_name=disp or None, username_hint=hint or None)
    if not blob_alnum:
        return False

    uname = (sender.tg_username or "").strip()
    ename = (sender.english_name or "").strip()
    if uname and _identity_matches_blob(needle=uname, blob_alnum=blob_alnum, min_len=4):
        return True
    if ename and _identity_matches_blob(needle=ename, blob_alnum=blob_alnum, min_len=3):
        return True
    for part in (disp, hint):
        if part and uname and _identity_matches_blob(needle=uname, blob_alnum=_norm_alnum(part), min_len=4):
            return True
        if part and ename and _identity_matches_blob(needle=ename, blob_alnum=_norm_alnum(part), min_len=3):
            return True

    return False
