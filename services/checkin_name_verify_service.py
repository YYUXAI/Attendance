"""Slack 浮窗姓名：视觉 + OCR 双通道校验（mode=both 时两者一致才采纳）。"""

from __future__ import annotations

import io
import logging

from services.checkin_user_message import MSG_NAME_MISMATCH
import os
import re
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

_HANDLE_RE = re.compile(r"\b(y_(?:ux|tc)_[a-z0-9]+)\b", re.IGNORECASE)
_LOOSE_NAME_RE = re.compile(r"\b([a-z][a-z0-9_]{3,31})\b", re.IGNORECASE)


@dataclass(frozen=True)
class SlackNameRead:
    display_name: Optional[str]
    username_hint: Optional[str]
    source: str
    raw_text: Optional[str] = None


@dataclass(frozen=True)
class DualNameVerifyResult:
    ok: bool
    display_name: Optional[str] = None
    username_hint: Optional[str] = None
    error_code: Optional[str] = None
    message: Optional[str] = None
    vision: Optional[SlackNameRead] = None
    ocr: Optional[SlackNameRead] = None


def _parse_identity_from_raw(text: str) -> SlackNameRead:
    from services.checkin_image_ai_service import (
        _extract_identity_from_text,
        _sanitize_field,
        _strip_bot_reply_text,
    )

    cleaned = _strip_bot_reply_text((text or "").strip())
    if not cleaned:
        return SlackNameRead(None, None, "unknown", raw_text=text)
    disp, hint = _extract_identity_from_text(cleaned, expected_username=None)
    disp_s = _sanitize_field(disp, field="display_name")
    hint_s = _sanitize_field(hint, field="username_hint")
    return SlackNameRead(disp_s, hint_s, "parsed", raw_text=cleaned[:200])


def vision_read_from_raw(vision_raw: str) -> SlackNameRead:
    read = _parse_identity_from_raw(vision_raw or "")
    return SlackNameRead(read.display_name, read.username_hint, "vision", raw_text=read.raw_text)


def _configure_tesseract_cmd(pytesseract: object) -> None:
    from services.checkin_ocr_engine import configure_tesseract_cmd

    configure_tesseract_cmd(pytesseract)


def _tesseract_missing(exc: BaseException) -> bool:
    from services.checkin_ocr_engine import is_ocr_runtime_missing

    return is_ocr_runtime_missing(exc)


_OCR_NOISE_SUBSTRINGS = (
    "constitution",
    "norwegian",
    "internation",
    "internatic",
    "against",
    "homophobia",
    "biphobia",
    "transphobia",
    "angeles",
    "newyork",
    "london",
    "sunrise",
    "sunset",
    "timeis",
    "emoji",
    "status",
    "setemoji",
    "telegram",
    "dsbbot",
    "打卡",
)


def _is_ocr_garbage_token(token: str) -> bool:
    """TIME.IS 节日/城市文案粘连，不是 Slack 用户名。"""
    t = (token or "").strip().lower()
    if not t:
        return True
    if not _is_plausible_slack_username(t):
        return True
    if any(n in t for n in _OCR_NOISE_SUBSTRINGS):
        return True
    # 长串且无下划线：多为 OCR 把多行英文粘成一词
    if len(t) > 14 and "_" not in t and not _HANDLE_RE.search(t):
        return True
    return False


def _resolve_registered_from_read(
    read: SlackNameRead,
    *,
    expected_username: Optional[str],
    expected_english_name: Optional[str] = None,
) -> Optional[str]:
    """raw/字段中含登记名时返回登记用户名（优先 tg_username）。"""
    blob = _read_identity_blob(read)
    if not _blob_includes_registered(
        blob,
        expected_username=expected_username,
        expected_english_name=expected_english_name,
    ):
        return None
    if expected_username and expected_username.strip():
        return expected_username.strip()
    keys = _registered_name_keys(expected_username, expected_english_name)
    return keys[0] if keys else None


def _filter_ocr_read(
    read: SlackNameRead,
    *,
    expected_username: Optional[str] = None,
    expected_english_name: Optional[str] = None,
) -> SlackNameRead:
    confirmed = _resolve_registered_from_read(
        read,
        expected_username=expected_username,
        expected_english_name=expected_english_name,
    )
    if confirmed:
        return SlackNameRead(confirmed, confirmed, read.source, raw_text=read.raw_text)
    token = _canonical_token(read.display_name, read.username_hint)
    if _is_ocr_garbage_token(token):
        return SlackNameRead(None, None, read.source, raw_text=read.raw_text)
    return read


def _ocr_rank(read: SlackNameRead) -> int:
    token = _canonical_token(read.display_name, read.username_hint)
    if not token or _is_ocr_garbage_token(token):
        return 0
    score = 10
    if read.username_hint:
        score += 5
    if read.display_name:
        score += 3
    if _HANDLE_RE.search(token):
        score += 8
    score += min(len(token), 24)
    return score


def _ocr_words_from_data(_pytesseract: object, img: object) -> str:
    from services.checkin_ocr_engine import ocr_high_confidence_words

    return ocr_high_confidence_words(img)  # type: ignore[arg-type]


def _ocr_one_panel(
    panel_bytes: bytes, *, fast: bool = False
) -> tuple[SlackNameRead, str]:
    from PIL import Image, ImageEnhance, ImageFilter, ImageOps

    try:
        img = Image.open(io.BytesIO(panel_bytes)).convert("RGB")
    except Exception:
        return SlackNameRead(None, None, "ocr"), ""

    w, h = img.size
    pixels = w * h
    if pixels < 80_000:
        scale = max(6, min(10, int((120_000 / max(pixels, 1)) ** 0.5)))
    else:
        scale = max(4, min(6, 1600 // max(w, h, 1)))
    if scale > 1:
        img = img.resize((w * scale, h * scale), Image.Resampling.LANCZOS)
    gray = ImageOps.autocontrast(img.convert("L"))
    sharp = ImageEnhance.Contrast(ImageEnhance.Sharpness(gray).enhance(1.4)).enhance(1.8)
    inverted = ImageOps.invert(gray)
    inv_sharp = ImageEnhance.Contrast(inverted).enhance(1.5)
    binary = sharp.point(lambda p: 255 if p > 155 else 0, mode="1").convert("L")
    if fast:
        variants = [("sharp", sharp)]
    else:
        variants = [
            ("sharp", sharp),
            ("invert", inv_sharp),
            ("binary", binary),
            ("blur_sharp", sharp.filter(ImageFilter.SHARPEN)),
        ]

    from services.checkin_ocr_engine import ocr_engine_name, ocr_high_confidence_words, ocr_image_to_string

    best = SlackNameRead(None, None, "ocr")
    best_raw = ""
    best_score = 0
    whitelist = (
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
    )
    langs = ("eng",) if fast else ("eng", "eng+chi_sim")
    psms = (7, 8) if fast else (7, 8, 6, 11, 13)
    for _tag, variant in variants:
        if ocr_engine_name() == "easyocr":
            try:
                text = ocr_image_to_string(variant, fast=fast)
            except Exception as exc:
                if _tesseract_missing(exc):
                    raise
                continue
            merged = (text or "").strip()
            if not fast:
                data_text = ocr_high_confidence_words(variant)
                if data_text:
                    merged = f"{merged}\n{data_text}"
            read = _filter_ocr_read(_parse_identity_from_raw(merged))
            score = _ocr_rank(read)
            if score > best_score:
                best_score = score
                best = read
                best_raw = merged[:160]
            if fast and score >= 15:
                return best, best_raw
            continue
        for lang in langs:
            for psm in psms:
                cfg = f"--psm {psm} --oem 3 -c tessedit_char_whitelist={whitelist}"
                try:
                    text = ocr_image_to_string(variant, lang=lang, config=cfg, fast=fast)
                except Exception as exc:
                    if lang != "eng" and (
                        "chi_sim" in str(exc).lower() or "language" in str(exc).lower()
                    ):
                        break
                    if _tesseract_missing(exc):
                        raise
                    continue
                merged = (text or "").strip()
                if not fast:
                    data_text = ocr_high_confidence_words(variant)
                    if data_text:
                        merged = f"{merged}\n{data_text}"
                read = _filter_ocr_read(_parse_identity_from_raw(merged))
                score = _ocr_rank(read)
                if score > best_score:
                    best_score = score
                    best = read
                    best_raw = merged[:160]
                if fast and score >= 15:
                    return best, best_raw
    return best, best_raw


def _ocr_quick_handle_scan(panel_bytes: bytes) -> SlackNameRead:
    """单次宽松 OCR，抓取 Y_UX_ 句柄（扁图姓名区快扫，约 1～2s）。"""
    from PIL import Image, ImageEnhance, ImageOps

    from services.checkin_ocr_engine import ocr_image_to_string

    try:
        img = Image.open(io.BytesIO(panel_bytes)).convert("RGB")
    except Exception:
        return SlackNameRead(None, None, "ocr")
    w, h = img.size
    scale = max(4, min(7, 1800 // max(w, h, 1)))
    if scale > 1:
        img = img.resize((w * scale, h * scale), Image.Resampling.LANCZOS)
    gray = ImageEnhance.Contrast(ImageOps.autocontrast(img.convert("L"))).enhance(2.0)
    try:
        text = ocr_image_to_string(gray, lang="eng", config="--psm 6 --oem 3", fast=True)
    except Exception:
        return SlackNameRead(None, None, "ocr")
    merged = (text or "").strip()
    for m in _HANDLE_RE.finditer(merged):
        handle = m.group(1)
        if _is_plausible_slack_username(handle):
            return SlackNameRead(handle, handle, "ocr", raw_text=merged[:120])
    read = _filter_ocr_read(_parse_identity_from_raw(merged))
    if read.display_name or read.username_hint:
        return read
    return SlackNameRead(None, None, "ocr", raw_text=merged[:120] or None)


def _ocr_hunt_expected_username(
    panel_bytes: bytes,
    expected_username: str,
    *,
    fast: bool = False,
) -> Optional[SlackNameRead]:
    """在裁剪区内搜索登记用户名（OCR 漏读时兜底）。"""
    exp = re.sub(r"[^a-z0-9_]", "", expected_username.strip().lower())
    if len(exp) < 4:
        return None
    from PIL import Image, ImageEnhance, ImageOps

    try:
        img = Image.open(io.BytesIO(panel_bytes)).convert("RGB")
    except Exception:
        return None
    w, h = img.size
    scale = max(6, min(10 if fast else 12, 3600 // max(w, h, 1)))
    img = img.resize((w * scale, h * scale), Image.Resampling.LANCZOS)
    gray = ImageEnhance.Contrast(ImageOps.autocontrast(img.convert("L"))).enhance(2.2)
    from services.checkin_ocr_engine import ocr_engine_name, ocr_image_to_string

    variants = (gray,) if fast else (gray, gray.point(lambda p: 255 if p > 160 else 0, mode="1").convert("L"))
    psms = (7, 8) if fast else (6, 7, 8, 11, 13)
    blob_parts: list[str] = []
    for variant in variants:
        if ocr_engine_name() == "easyocr":
            try:
                blob_parts.append(ocr_image_to_string(variant, fast=fast))
            except Exception:
                continue
            continue
        for psm in psms:
            try:
                blob_parts.append(
                    ocr_image_to_string(
                        variant, lang="eng", config=f"--psm {psm} --oem 3", fast=fast
                    )
                )
            except Exception:
                continue
    merged = " ".join(blob_parts)
    blob = re.sub(r"[^a-z0-9]", "", merged.lower())
    if len(blob) < max(4, len(exp) - 2):
        return None
    if exp in blob:
        return SlackNameRead(
            expected_username.strip(),
            expected_username.strip(),
            "ocr",
            raw_text=merged[:200],
        )
    return None


_HUNT_REGION_KEYS = (
    "name_panel_bottom",
    "name_panel_overlay",
    "name_panel_row",
    "time_main",
    "name_panel",
)


def ocr_hunt_regions_parallel(
    regions: dict[str, bytes],
    expected_username: str,
    *,
    keys: tuple[str, ...] | None = None,
) -> Optional[SlackNameRead]:
    """多区域并行 expected-hunt（约 3～6s，替代串行 hunt + 慢速 OCR）。"""
    from services.checkin_ocr_engine import ocr_backend_available

    if not ocr_backend_available():
        return None
    hunt_keys = keys or _HUNT_REGION_KEYS

    _slow_hunt_keys = frozenset(
        {"name_panel_bottom", "name_panel_overlay", "name_panel_row"}
    )

    def _one(key: str) -> Optional[SlackNameRead]:
        chunk = regions.get(key)
        if not chunk:
            return None
        return _ocr_hunt_expected_username(
            chunk,
            expected_username,
            fast=key not in _slow_hunt_keys,
        )

    from concurrent.futures import as_completed

    from services.checkin_ocr_executor import get_ocr_thread_pool

    pool = get_ocr_thread_pool()
    futures = {pool.submit(_one, k): k for k in hunt_keys}
    for fut in as_completed(futures):
        key = futures[fut]
        try:
            hit = fut.result()
        except Exception:
            log.warning("checkin_name: parallel hunt failed key=%s", key, exc_info=True)
            continue
        if hit:
            log.info("checkin_name: parallel hunt hit region=%s", key)
            return hit
    return None


def ocr_thorough_best_panel(
    regions: dict[str, bytes],
    expected_username: str,
    *,
    keys: tuple[str, ...] = (
        "name_panel_bottom",
        "name_panel_overlay",
    ),
) -> Optional[SlackNameRead]:
    """最后兜底：最多 2 区顺序 full hunt（~6s/区），不做整 panel 慢 OCR。"""
    from services.checkin_ocr_engine import ocr_backend_available

    if not ocr_backend_available():
        return None
    for key in keys:
        chunk = regions.get(key)
        if not chunk:
            continue
        hit = _ocr_hunt_expected_username(chunk, expected_username, fast=False)
        if hit:
            log.info("checkin_name: thorough hunt hit region=%s", key)
            return hit
    return None


def ocr_quick_other_person_parallel(
    regions: dict[str, bytes],
    *,
    expected_username: Optional[str],
    expected_english_name: Optional[str] = None,
    keys: tuple[str, ...] = ("name_panel_overlay", "name_panel_bottom"),
) -> Optional[str]:
    """并行快扫他人 Y_UX 句柄（约 2s），用于 Nayxua 等拒他人。"""
    from services.checkin_ocr_engine import ocr_backend_available

    if not ocr_backend_available():
        return None

    def _scan(key: str) -> Optional[str]:
        chunk = regions.get(key)
        if not chunk:
            return None
        read = _ocr_quick_handle_scan(chunk)
        blob = _read_identity_blob(read)
        return _blob_shows_other_person(
            blob,
            expected_username=expected_username,
            expected_english_name=expected_english_name,
        )

    from concurrent.futures import as_completed

    from services.checkin_ocr_executor import get_ocr_thread_pool

    pool = get_ocr_thread_pool()
    futures = {pool.submit(_scan, k): k for k in keys if regions.get(k)}
    for fut in as_completed(futures):
        try:
            clue = fut.result()
        except Exception:
            continue
        if clue:
            return clue
    return None


def ocr_hunt_username_in_image(
    image_bytes: bytes,
    expected_username: str,
) -> tuple[SlackNameRead, bool]:
    """整图兜底：最多 2 条带并行 fast hunt。"""
    from services.checkin_ocr_engine import ocr_backend_available

    if not ocr_backend_available():
        return SlackNameRead(None, None, "ocr"), False
    exp = (expected_username or "").strip()
    if len(re.sub(r"[^a-z0-9_]", "", exp.lower())) < 4:
        return SlackNameRead(None, None, "ocr"), True

    from PIL import Image

    from services.checkin_image_ai_service import _image_to_jpeg_bytes

    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return SlackNameRead(None, None, "ocr"), True

    w, h = img.size
    aspect = w / max(h, 1)
    strips: list[Image.Image] = []
    if aspect >= 2.0 and h < 550:
        strips.append(img.crop((int(w * 0.45), 0, w, int(h * 0.78))))
        strips.append(img.crop((int(w * 0.38), int(h * 0.30), w, h)))
    else:
        strips.append(img.crop((int(w * 0.40), 0, w, h)))

    def _hunt_strip(strip: Image.Image) -> Optional[SlackNameRead]:
        return _ocr_hunt_expected_username(
            _image_to_jpeg_bytes(strip), exp, fast=True
        )

    from concurrent.futures import as_completed

    from services.checkin_ocr_executor import get_ocr_thread_pool

    pool = get_ocr_thread_pool()
    futs = [pool.submit(_hunt_strip, s) for s in strips[:2]]
    for fut in as_completed(futs):
        try:
            hit = fut.result()
        except Exception:
            continue
        if hit:
            log.info("checkin_name: image-wide hunt hit")
            return hit, True
    return SlackNameRead(None, None, "ocr"), True


def ocr_slack_name_from_panel(
    panel_bytes: bytes,
    *,
    extra_panels: Optional[list[bytes]] = None,
    expected_username: Optional[str] = None,
    fast: bool = True,
) -> tuple[SlackNameRead, bool]:
    """
    对 name_panel 裁剪图做 OCR。返回 (读取结果, OCR 后端是否可用)。
    extra_panels: 备选裁剪（略宽右下角），取识别分最高者。
    """
    from services.checkin_ocr_engine import ocr_backend_available, ocr_engine_name

    if not ocr_backend_available():
        log.warning("checkin_name: ocr backend not available (engine=%s)", ocr_engine_name())
        return SlackNameRead(None, None, "ocr"), False

    crops: list[bytes] = [panel_bytes]
    if not fast:
        for b in extra_panels or []:
            if b and b not in crops:
                crops.append(b)
    # 快路径只用主裁剪，避免 2 块 panel OCR 拖到 15s+

    best = SlackNameRead(None, None, "ocr")
    best_raw = ""
    best_score = 0
    crop_tokens: list[str] = []
    try:
        if fast and expected_username:
            for crop in crops:
                hunted = _ocr_hunt_expected_username(crop, expected_username)
                if hunted:
                    best = hunted
                    best_raw = hunted.raw_text or ""
                    best_score = _ocr_rank(hunted)
                    log.info(
                        "checkin_name: ocr expected-hunt hit token=%s (fast)",
                        expected_username,
                    )
                    break
        if best_score < 10:
            for crop in crops:
                read, raw = _ocr_one_panel(crop, fast=fast)
                score = _ocr_rank(read)
                tok = _canonical_token(read.display_name, read.username_hint)
                if tok:
                    crop_tokens.append(tok)
                if score > best_score:
                    best_score = score
                    best = read
                    best_raw = raw
                if score >= 18 or (fast and score >= 15):
                    break
        if fast and best_score < 10:
            for crop in crops:
                scanned = _ocr_quick_handle_scan(crop)
                score = _ocr_rank(scanned)
                if score > best_score:
                    best_score = score
                    best = scanned
                    best_raw = scanned.raw_text or ""
                if score >= 12:
                    break
        if not fast and crop_tokens:
            from collections import Counter

            top_tok, agree_n = Counter(crop_tokens).most_common(1)[0]
            if agree_n >= 2 and best_score < 15:
                for crop in crops:
                    read, raw = _ocr_one_panel(crop, fast=False)
                    if _canonical_token(read.display_name, read.username_hint) == top_tok:
                        best = read
                        best_raw = raw
                        best_score = max(best_score, _ocr_rank(read))
                        break
            if agree_n >= 2:
                best_score = max(best_score, 14 + agree_n * 2)
    except Exception as exc:
        if _tesseract_missing(exc):
            log.warning("checkin_name: ocr runtime not available (engine=%s)", ocr_engine_name())
            return SlackNameRead(None, None, "ocr"), False
        log.warning("checkin_name: ocr failed", exc_info=True)
        return SlackNameRead(None, None, "ocr"), True

    # 保留「他人」误读结果，供双通道/校验层报 AI_USER_OTHER_PERSON（勿在此清空）
    if not fast and best_score < 10 and expected_username:
        for crop in crops:
            hunted = _ocr_hunt_expected_username(crop, expected_username)
            if hunted:
                best = hunted
                best_raw = hunted.raw_text or ""
                best_score = _ocr_rank(hunted)
                log.info(
                    "checkin_name: ocr expected-hunt hit token=%s",
                    expected_username,
                )
                break
    out = SlackNameRead(
        best.display_name, best.username_hint, "ocr", raw_text=best_raw or None
    )
    confirmed = _resolve_registered_from_read(
        out,
        expected_username=expected_username,
        expected_english_name=None,
    )
    if confirmed:
        out = SlackNameRead(confirmed, confirmed, "ocr", raw_text=best_raw or None)
    log.info(
        "checkin_name: ocr panel raw=%r -> display=%s hint=%s (crops=%s score=%s)",
        best_raw,
        out.display_name,
        out.username_hint,
        len(crops),
        best_score,
    )
    return out, True


def _canonical_token(display_name: Optional[str], username_hint: Optional[str]) -> str:
    hint = (username_hint or "").strip().lower()
    disp = (display_name or "").strip().lower()
    token = hint or disp
    if token.startswith("@"):
        token = token[1:]
    token = re.sub(r"\s+", "", token)
    if not token:
        return ""
    m = _HANDLE_RE.search(token) or _HANDLE_RE.search(disp)
    if m:
        return m.group(1).lower()
    m2 = _LOOSE_NAME_RE.search(hint or disp)
    if m2:
        return m2.group(1).lower()
    return re.sub(r"[^a-z0-9_]", "", token)


def _is_plausible_slack_username(token: str) -> bool:
    t = (token or "").strip().lower()
    if len(t) < 4 or len(t) > 32:
        return False
    noise = (
        "constitution",
        "norwegian",
        "angeles",
        "sunrise",
        "sunset",
        "emoji",
        "status",
        "slack",
        "telegram",
    )
    if any(n in t for n in noise):
        return False
    if _HANDLE_RE.fullmatch(t):
        return True
    return bool(_LOOSE_NAME_RE.fullmatch(t))


def _tokens_agree(a: SlackNameRead, b: SlackNameRead) -> bool:
    ta = _canonical_token(a.display_name, a.username_hint)
    tb = _canonical_token(b.display_name, b.username_hint)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    if ta in tb or tb in ta:
        return True
  # benrenxing vs benrenxingz
    ta_c = re.sub(r"[^a-z0-9_]", "", ta)
    tb_c = re.sub(r"[^a-z0-9_]", "", tb)
    return ta_c == tb_c or ta_c in tb_c or tb_c in ta_c


def _expected_token(expected_username: Optional[str]) -> str:
    return _canonical_token(None, expected_username)


def _token_matches_expected(token: str, expected_username: Optional[str]) -> bool:
    exp = _expected_token(expected_username)
    if not token or not exp:
        return False
    if token == exp:
        return True
    return token in exp or exp in token


def _norm_identity_blob(text: str) -> str:
    return re.sub(r"[^a-z0-9_]", "", (text or "").lower())


def _read_identity_blob(read: SlackNameRead) -> str:
    parts = [read.display_name or "", read.username_hint or "", read.raw_text or ""]
    return _norm_identity_blob(" ".join(parts))


def _registered_name_keys(
    expected_username: Optional[str],
    expected_english_name: Optional[str] = None,
) -> list[str]:
    keys: list[str] = []
    for raw in (expected_username, expected_english_name):
        k = _norm_identity_blob(raw or "")
        if len(k) >= 4 and k not in keys:
            keys.append(k)
    return keys


def _blob_includes_registered(
    blob: str,
    *,
    expected_username: Optional[str],
    expected_english_name: Optional[str] = None,
) -> bool:
    """包含法：识别文本（去空格/符号后）含有登记用户名或英文名即算命中。"""
    b = _norm_identity_blob(blob)
    if not b:
        return False
    for key in _registered_name_keys(expected_username, expected_english_name):
        if key in b:
            return True
    return False


def _channel_includes_registered(
    read: SlackNameRead,
    *,
    expected_username: Optional[str],
    expected_english_name: Optional[str] = None,
) -> bool:
    return _blob_includes_registered(
        _read_identity_blob(read),
        expected_username=expected_username,
        expected_english_name=expected_english_name,
    )


def _blob_shows_other_person(
    blob: str,
    *,
    expected_username: Optional[str],
    expected_english_name: Optional[str] = None,
) -> Optional[str]:
    """出现他人 Y_UX 句柄或 Nayxua 等，且整段文本不包含本人登记名。"""
    b = _norm_identity_blob(blob)
    if not b:
        return None
    if _blob_includes_registered(
        blob,
        expected_username=expected_username,
        expected_english_name=expected_english_name,
    ):
        return None
    raw = blob.lower()
    keys = _registered_name_keys(expected_username, expected_english_name)
    for m in _HANDLE_RE.finditer(raw):
        token = _norm_identity_blob(m.group(1))
        if len(token) < 6 or _is_ocr_garbage_token(token):
            continue
        if any(k in token or token in k for k in keys):
            continue
        return m.group(1)
    if "nayxua" in b and not any("nayxua" in k for k in keys):
        return "nayxua"
    return None


def verify_slack_name_dual(
    *,
    vision: SlackNameRead,
    ocr: SlackNameRead,
    mode: str,
    expected_username: Optional[str] = None,
    expected_english_name: Optional[str] = None,
) -> DualNameVerifyResult:
    mode_n = (mode or "vision").strip().lower()
    if mode_n == "vision":
        if vision.display_name or vision.username_hint:
            return DualNameVerifyResult(
                ok=True,
                display_name=vision.display_name,
                username_hint=vision.username_hint,
                vision=vision,
            )
        return DualNameVerifyResult(ok=False, error_code="AI_NAME_NOT_FOUND", vision=vision)

    if mode_n == "ocr":
        if _channel_includes_registered(
            ocr,
            expected_username=expected_username,
            expected_english_name=expected_english_name,
        ):
            confirmed = (
                _resolve_registered_from_read(
                    ocr,
                    expected_username=expected_username,
                    expected_english_name=expected_english_name,
                )
                or (expected_username or "").strip()
            )
            if confirmed:
                return DualNameVerifyResult(
                    ok=True,
                    display_name=confirmed,
                    username_hint=confirmed,
                    ocr=ocr,
                )
        return DualNameVerifyResult(
            ok=False,
            error_code="AI_NAME_NOT_FOUND",
            message=MSG_NAME_MISMATCH,
            ocr=ocr,
        )

    if mode_n != "both":
        return DualNameVerifyResult(
            ok=False,
            error_code="AI_CONFIG_INVALID",
            message=f"未知 CHECKIN_AI_NAME_VERIFY={mode}",
        )

    reg_keys = _registered_name_keys(expected_username, expected_english_name)
    if not reg_keys:
        return DualNameVerifyResult(
            ok=False,
            error_code="AI_CONFIG_INVALID",
            message=MSG_NAME_MISMATCH,
        )

    ocr = _filter_ocr_read(
        ocr,
        expected_username=expected_username,
        expected_english_name=expected_english_name,
    )
    v_token = _canonical_token(vision.display_name, vision.username_hint)
    if v_token and "nayxua" in v_token and not any("nayxua" in k for k in reg_keys):
        log.warning("checkin_name: discard vision nayxua hallucination token=%s", v_token)
        vision = SlackNameRead(None, None, "vision", raw_text=vision.raw_text)

    v_inc = _channel_includes_registered(
        vision,
        expected_username=expected_username,
        expected_english_name=expected_english_name,
    )
    o_inc = _channel_includes_registered(
        ocr,
        expected_username=expected_username,
        expected_english_name=expected_english_name,
    )

    if v_inc or o_inc:
        via = "vision+ocr" if v_inc and o_inc else ("vision" if v_inc else "ocr")
        confirmed = (
            _resolve_registered_from_read(
                vision,
                expected_username=expected_username,
                expected_english_name=expected_english_name,
            )
            or _resolve_registered_from_read(
                ocr,
                expected_username=expected_username,
                expected_english_name=expected_english_name,
            )
            or (expected_username or "").strip()
            or reg_keys[0]
        )
        log.info("checkin_name: dual inclusion pass via=%s token=%s", via, confirmed)
        return DualNameVerifyResult(
            ok=True,
            display_name=confirmed,
            username_hint=confirmed,
            vision=vision,
            ocr=ocr,
        )

    combined_blob = _read_identity_blob(vision) + _read_identity_blob(ocr)
    other = _blob_shows_other_person(
        combined_blob,
        expected_username=expected_username,
        expected_english_name=expected_english_name,
    )
    if other:
        return DualNameVerifyResult(
            ok=False,
            error_code="AI_USER_OTHER_PERSON",
            message=MSG_NAME_MISMATCH,
            vision=vision,
            ocr=ocr,
        )

    return DualNameVerifyResult(
        ok=False,
        error_code="AI_NAME_NOT_FOUND",
        message=MSG_NAME_MISMATCH,
        vision=vision,
        ocr=ocr,
    )
