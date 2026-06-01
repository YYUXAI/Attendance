from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import re
import time
from dataclasses import dataclass, replace
from datetime import datetime, time as dt_time, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx

from domain.checkin_image_extraction import CheckinImageExtraction
from infra.checkin_ai_config import CheckinAiConfig

log = logging.getLogger(__name__)


_EXTRACT_PROMPT = """Read this check-in screenshot. Copy ONLY text you truly see. Never invent names or times.

Return one JSON object, no markdown. Use null for missing fields.

Keys:
- display_name: text on Slack/IM profile popup (string or null)
- username_hint: login/handle without @ (string or null)
- clock_time: largest HH:MM:SS on screen (string or null)
- clock_date: YYYY-MM-DD if visible (string or null)
- timezone_iana: e.g. Asia/Shanghai (string or null)
- confidence: 0-1

Forbidden: copy these instructions, use placeholder text, or guess.
"""

_TIME_FOCUS_PROMPT = (
    "This is a time.is screenshot. Read ONLY the huge main clock in the center. "
    "IGNORE smaller city times at the bottom (London, New York, Los Angeles, etc). "
    "Reply with ONLY that main clock in HH:MM:SS format. No other words."
)
# moondream 常复读 prompt 示例时间
_VISION_PROMPT_ECHO_CLOCKS = frozenset({"20:12:24", "20:12:24"})
_NAME_FOCUS_PROMPT = (
    "Look ONLY at the small Slack profile popup (round avatar + display name beside it). "
    "Ignore TIME.IS clock, holidays, cities, Telegram chat, and bot messages. "
    "Reply with ONLY the display name text next to the avatar. One word or handle only."
)
# 模型常把 prompt 示例复读为识别结果，必须丢弃
_VISION_PROMPT_ECHO_HANDLES = frozenset(
    {
        "y_ux_nayxua",
        "y_tc_nayxua",
        "y_ux_nayxu",
        "nayxua",
    }
)
_CHAT_SCREENSHOT_MARKERS = (
    "正在识别打卡",
    "打卡失败",
    "dsb_bot",
    "replied to",
    "telegram",
)
# Bot 成功/失败回复里的字段，避免 OCR 到「打卡时间：20:12:24」误当作 time.is 时钟
_BOT_REPLY_LINE_MARKERS = (
    "打卡时间",
    "时间来源",
    "截图 AI",
    "截图用户",
    "已按 Telegram",
    "英文名",
    "工号",
    "部门",
    "班次",
    "文件ID",
    "dsb_bot",
    "打卡失败",
    "正在识别打卡",
)
_BOT_REPLY_CUT_MARKERS = _BOT_REPLY_LINE_MARKERS + ("2026-05-15", "2026-05-14")
_OLLAMA_VISION_OPTIONS: dict[str, Any] = {"num_predict": 128, "temperature": 0}
_TIME_CROP_ORDER = (
    "full",
    "time_digits",
    "time_clock",
    "time_panel",
    "time_top",
    "time_embedded",
    "time",
)
# 仅 Slack 浮窗（name_panel），不用更大 name 区，避免扫到 Telegram/Bot 文字
_NAME_CROP_ORDER = ("name_panel",)


def _image_digest(image_bytes: bytes) -> str:
    return hashlib.sha256(image_bytes).hexdigest()


def _digest_from_b64(image_b64: str) -> str:
    return _image_digest(base64.standard_b64decode(image_b64))


def _ollama_options_for_image(image_digest: str, *, attempt: int = 0) -> dict[str, Any]:
    """每张图独立 seed，避免 Ollama 连续请求时沿用上一次视觉结果。"""
    seed = (int(image_digest[:8], 16) + attempt * 9973) % (2**31 - 1)
    predict = 128 + attempt * 64
    return {**_OLLAMA_VISION_OPTIONS, "seed": seed, "num_predict": predict}


def _bind_prompt_to_image(prompt: str, image_digest: str, *, attempt: int) -> str:
    return f"{prompt}\n[image:{image_digest[:16]}:{attempt}]"

_PLACEHOLDER_RE = re.compile(
    r"用户名片段|浮窗|HH:MM:SS|YYYY-MM-DD|IANA|或\s*null|如\s*Y_|example|字段|json|forbidden",
    re.IGNORECASE,
)
_INVALID_IDENTITY_WORDS = frozenset(
    {
        "shows",
        "show",
        "the",
        "image",
        "clock",
        "time",
        "profile",
        "website",
        "screenshot",
        "displayed",
        "button",
        "corner",
        "slack",
        "popup",
        "chinese",
        "content",
        "digital",
        "large",
        "screen",
        "this",
        "that",
        "with",
        "from",
        "have",
        "page",
        "pages",
        "text",
        "reply",
        "only",
        "name",
        "bot",
        "dsb",
        "person",
        "window",
        "small",
        "bottom",
        "right",
        "left",
        "top",
        "set",
        "emoji",
        "status",
    }
)
_USERNAME_TOKEN_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,31}$")
_SLACK_HANDLE_RE = re.compile(r"\b([A-Za-z][A-Za-z0-9_]{2,31})\b")


def _name_focus_prompt(*, expected_username: str | None) -> str:
    if expected_username:
        return (
            f"Look at the Slack profile popup in the image. "
            f"The name contains '{expected_username}'. "
            "Reply with ONLY that person's name text, nothing else."
        )
    return _NAME_FOCUS_PROMPT


def _is_plausible_identity(value: str) -> bool:
    low = value.strip().lower()
    if not low or low in _INVALID_IDENTITY_WORDS:
        return False
    if low in {"null", "none", "n/a"}:
        return False
  # 单个英文常用词（如 shows）不是人名
    if re.fullmatch(r"[a-z]{2,8}", low) and low in _INVALID_IDENTITY_WORDS:
        return False
    if len(low) < 4 and not re.search(r"y_(?:ux|tc)_", low):
        return False
    return True


@dataclass(frozen=True)
class CheckinAiExtractError:
    error_code: str
    message: str


def _strip_json_payload(text: str) -> str:
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw, flags=re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        return raw[start : end + 1]
    return raw


def _sanitize_field(value: str | None, *, field: str) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip().strip('"').strip("'")
    if not s:
        return None
    low = s.lower()
    if low in {"null", "none", "n/a", "na", "unknown", "undefined"}:
        return None
    if _PLACEHOLDER_RE.search(s):
        return None

    if field in {"display_name", "username_hint"}:
        if not _is_plausible_identity(s):
            return None
        if field == "username_hint" and not _USERNAME_TOKEN_RE.match(s):
            um = re.search(r"\b(Y_(?:UX|TC)_[A-Za-z0-9]+)\b", s) or _SLACK_HANDLE_RE.search(s)
            cand = um.group(1) if um else None
            return cand if cand and _is_plausible_identity(cand) else None
        if field == "display_name" and " " in s:
            first = s.split()[0]
            if _is_plausible_identity(first):
                pass
            elif not re.search(r"[A-Za-z0-9_]{4,}", s):
                return None

    if field == "clock_time":
        if not re.match(r"^\d{1,2}:\d{2}(:\d{2})?$", s):
            tm = re.search(r"\b(\d{1,2}:\d{2}:\d{2})\b", s)
            return tm.group(1) if tm else None

    if field == "clock_date" and not re.match(r"^20\d{2}-\d{1,2}-\d{1,2}$", s):
        dm = re.search(r"\b(20\d{2}-\d{1,2}-\d{1,2})\b", s)
        return dm.group(1) if dm else None

    if field in {"display_name", "username_hint"} and not _is_plausible_identity(s):
        return None
    return s


def has_valid_identity_fields(extraction: CheckinImageExtraction) -> bool:
    d = _sanitize_field(extraction.display_name, field="display_name")
    h = _sanitize_field(extraction.username_hint, field="username_hint")
    return bool(d or h)


def pick_single_identity(extraction: CheckinImageExtraction) -> Optional[str]:
    """对外只展示一个识别到的用户名（优先 Slack 用户名 token）。"""
    hint = extraction.username_hint
    disp = extraction.display_name
    if hint and disp:
        if hint.lower() in disp.lower():
            return disp
        return f"{disp}（{hint}）"
    return hint or disp


def _parse_extraction_payload(data: dict[str, Any]) -> CheckinImageExtraction:
    conf = data.get("confidence")
    confidence: Optional[float] = None
    if conf is not None:
        try:
            confidence = float(conf)
        except (TypeError, ValueError):
            confidence = None

    def _opt_str(key: str) -> Optional[str]:
        val = data.get(key)
        if val is None:
            return None
        return _sanitize_field(str(val), field=key)

    return _enrich_identity_from_display(
        CheckinImageExtraction(
            display_name=_opt_str("display_name"),
            username_hint=_opt_str("username_hint"),
            clock_time=_opt_str("clock_time"),
            clock_date=_opt_str("clock_date"),
            timezone_iana=_opt_str("timezone_iana"),
            confidence=confidence,
        )
    )


def _ollama_root(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return "http://127.0.0.1:11434"


def _is_ollama_base(base_url: str) -> bool:
    root = _ollama_root(base_url).lower()
    return "11434" in root or base_url.rstrip("/").endswith("/api")


def _image_to_jpeg_bytes(img: Any, *, quality: int = 85) -> bytes:
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()


def _prepare_image_bytes(image_bytes: bytes, *, max_side: int = 1280) -> bytes:
    """统一转 JPEG 并缩小，便于 moondream 稳定识别。"""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        if max(w, h) < 960:
            scale = 960 / float(max(w, h))
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        elif max(w, h) > max_side:
            scale = max_side / float(max(w, h))
            img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        compressed = _image_to_jpeg_bytes(img)
        if len(compressed) < len(image_bytes) or not image_bytes.startswith(b"\xff\xd8"):
            log.info(
                "checkin_ai: image prepared %sKB -> %sKB (%sx%s)",
                len(image_bytes) // 1024,
                len(compressed) // 1024,
                img.size[0],
                img.size[1],
            )
        return compressed
    except Exception:
        log.warning("checkin_ai: image resize skipped", exc_info=True)
        return image_bytes


def _detect_bright_panel_box(img: Any, *, lum_threshold: int = 168) -> Optional[tuple[int, int, int, int]]:
    """在 Telegram 对话截图中定位上部嵌入的 time.is 白底区域。"""
    w, h = img.size
    if w < 200 or h < 200:
        return None
    pixels = img.load()
    step_x = max(1, w // 80)
    step_y = max(1, h // 80)

    def sample_lum(x: int, y: int) -> float:
        r, g, b = pixels[min(x, w - 1), min(y, h - 1)]
        return (r + g + b) / 3.0

    def row_lum(y: int) -> float:
        total = 0.0
        n = 0
        for x in range(0, w, step_x):
            total += sample_lum(x, y)
            n += 1
        return total / max(n, 1)

    y_end = int(h * 0.78)
    bands: list[tuple[int, int]] = []
    band_start: Optional[int] = None
    for y in range(int(h * 0.02), y_end):
        lum = row_lum(y)
        if lum >= lum_threshold:
            if band_start is None:
                band_start = y
        elif band_start is not None:
            bands.append((band_start, y - 1))
            band_start = None
    if band_start is not None:
        bands.append((band_start, y_end - 1))
    min_band_h = int(h * 0.18)
    bands = [(a, b) for a, b in bands if (b - a + 1) >= min_band_h]
    if not bands:
        return None
    y0, y1 = max(bands, key=lambda b: b[1] - b[0])

    def col_lum(x: int) -> float:
        total = 0.0
        n = 0
        for y in range(y0, y1 + 1, step_y):
            total += sample_lum(x, y)
            n += 1
        return total / max(n, 1)

    x0: Optional[int] = None
    x1: Optional[int] = None
    for x in range(0, w, step_x):
        if col_lum(x) >= lum_threshold - 10:
            if x0 is None:
                x0 = x
            x1 = x
    if x0 is None or x1 is None or (x1 - x0) < int(w * 0.35):
        return None
    pad_x = int(w * 0.02)
    pad_y = int(h * 0.02)
    return (
        max(0, x0 - pad_x),
        max(0, y0 - pad_y),
        min(w, x1 + pad_x),
        min(h, y1 + pad_y),
    )


def _is_vision_prompt_echo(token: str) -> bool:
    t = re.sub(r"[^a-z0-9_]", "", (token or "").strip().lower())
    if not t:
        return False
    if t in _VISION_PROMPT_ECHO_HANDLES:
        return True
    return "nayxua" in t and t.startswith("y_")


def _clamp_box(box: tuple[int, int, int, int], w: int, h: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = box
    return (max(0, min(x0, w - 2)), max(0, min(y0, h - 2)), max(1, min(x1, w)), max(1, min(y1, h)))


def _ensure_min_crop_box(
    box: tuple[int, int, int, int],
    w: int,
    h: int,
    *,
    min_h: int = 72,
    min_w: int = 280,
) -> tuple[int, int, int, int]:
    """Telegram 扁图裁切过小时，扩到右下角足够区域供 OCR/视觉识别。"""
    x0, y0, x1, y1 = _clamp_box(box, w, h)
    cw, ch = x1 - x0, y1 - y0
    if cw >= min_w and ch >= min_h:
        return (x0, y0, x1, y1)
    x1 = w
    y1 = h
    x0 = min(x0, max(0, w - min_w))
    y0 = min(y0, max(0, h - min_h))
    if y1 - y0 < min_h:
        y0 = max(0, h - min_h)
    if x1 - x0 < min_w:
        x0 = max(0, w - min_w)
    return _clamp_box((x0, y0, x1, y1), w, h)


def _slack_name_panel_box(
    w: int,
    h: int,
    panel: Optional[tuple[int, int, int, int]] = None,
    *,
    right_frac: float = 0.30,
) -> tuple[int, int, int, int]:
    """
    Slack 个人浮窗在 TIME.IS 截图右下角窄条，避开中部节日/城市文案。
    right_frac: 取全图最右侧比例宽度（默认 30%）。
    """
    rx = max(0.22, min(0.40, float(right_frac)))
    x0 = int(w * (1.0 - rx))
    x1 = w
    short = h < 420 or (w > h * 2.0 and h < 500)
    if panel and not short:
        px0, py0, px1, py1 = _clamp_box(panel, w, h)
        ph = max(py1 - py0, 1)
        y0 = max(py0 + int(ph * 0.50), int(h * 0.46))
        y1 = min(h, py1 + max(int(h * 0.16), int(ph * 0.42)))
    elif short:
        # Telegram 横条/压扁图：浮窗贴底右角，勿用 panel 下半段（易只剩几条像素）
        x0 = int(w * 0.48)
        y0 = int(h * 0.42) if h < 320 else int(h * 0.50)
        y1 = h
    else:
        y0 = int(h * 0.48)
        y1 = h
    pad = max(2, int(w * 0.008))
    box = (max(0, x0 - pad), max(0, y0), min(w, x1), min(h, y1))
    return _ensure_min_crop_box(box, w, h)


def _time_main_clock_box(w: int, h: int) -> tuple[int, int, int, int]:
    """TIME.IS 大号主钟区域（上部），避免 time_panel 只裁到页脚节日文案。"""
    y1 = int(h * 0.58) if h >= 360 else int(h * 0.65)
    return (max(0, int(w * 0.02)), 0, w, max(y1, int(h * 0.45)))


def _time_center_clock_box(w: int, h: int) -> tuple[int, int, int, int]:
    """扁图左侧大号主钟（避开右上 Slack 与页脚城市小字）。"""
    return (
        max(0, int(w * 0.02)),
        0,
        int(w * 0.72),
        max(int(h * 0.42), int(h * 0.35)),
    )


def _slack_name_overlay_box(w: int, h: int) -> tuple[int, int, int, int]:
    """扁图 TIME.IS：Slack 浮窗叠在钟面右上（非页脚右下）。"""
    aspect = w / max(h, 1)
    if aspect >= 2.4 and h < 520:
        x0 = int(w * 0.50)
        y0 = int(h * 0.02)
        y1 = int(h * 0.72)
    else:
        x0 = int(w * 0.52)
        y0 = int(h * 0.06)
        y1 = int(h * 0.62)
    return _ensure_min_crop_box((x0, y0, w, y1), w, h, min_h=72, min_w=280)


def _slack_name_bottom_corner_box(w: int, h: int) -> tuple[int, int, int, int]:
    """整图右下角大块（扁图兜底）。"""
    x0 = int(w * 0.42)
    y0 = int(h * 0.38) if h < 350 else int(h * 0.48)
    return _ensure_min_crop_box((x0, y0, w, h), w, h, min_h=80, min_w=320)


def _slack_name_panel_tight_box(w: int, h: int) -> tuple[int, int, int, int]:
    """更窄的右下角条，对准 Slack 浮窗姓名行（避开 Set Emoji Status 等副文案）。"""
    if h < 420:
        x0 = int(w * 0.55)
        y0 = int(h * 0.48)
    else:
        x0 = int(w * 0.74)
        y0 = int(h * 0.58)
    y1 = min(h, int(h * 0.94))
    pad = max(2, int(w * 0.006))
    box = (max(0, x0 - pad), max(0, y0), w, min(h, y1 + pad))
    return _ensure_min_crop_box(box, w, h, min_h=56, min_w=240)


def _slack_name_row_box(
    w: int, h: int, panel: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    """Slack 浮窗第一行 display name（避开 Set Emoji Status）。"""
    x0, y0, x1, y1 = _clamp_box(panel, w, h)
    pw, ph = max(x1 - x0, 1), max(y1 - y0, 1)
    if ph < 80 or h < 420:
        box = (int(w * 0.52), int(h * 0.45), w, min(h, int(h * 0.88)))
        return _ensure_min_crop_box(box, w, h, min_h=64, min_w=260)
    rx0 = x0 + int(pw * 0.55)
    ry0 = y0 + int(ph * 0.58)
    ry1 = y0 + int(ph * 0.82)
    box = (max(0, rx0), max(0, ry0), min(w, x1), min(h, max(ry1, ry0 + 8)))
    return _ensure_min_crop_box(box, w, h, min_h=48, min_w=220)


def _upscale_bytes_for_vision(crop_bytes: bytes, *, min_side: int = 384) -> bytes:
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(crop_bytes)).convert("RGB")
        w, h = img.size
        scale = max(float(min_side) / max(w, 1), float(min_side) / max(h, 1), 1.0)
        if scale <= 1.05:
            return crop_bytes
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
        return _image_to_jpeg_bytes(img)
    except Exception:
        return crop_bytes


def _isolate_timeis_canvas(image_bytes: bytes) -> bytes:
    """裁出 TIME.IS 白底区（含 Slack 浮窗），去掉 Telegram 对话下方 Bot 气泡。"""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        aspect = w / max(h, 1)
        # 典型 TIME.IS 相册横图（如 1280×430~520）：整图即打卡内容，勿裁短
        if 360 <= h <= 580 and 2.15 <= aspect < 3.6:
            return image_bytes
        panel = _detect_bright_panel_box(img)
        if not panel:
            return image_bytes
        _, py0, _, py1 = panel
        ph = max(py1 - py0, 1)
        y0e = max(0, py0 - int(ph * 0.04))
        y1e = min(h, py1 + max(int(ph * 0.38), int(h * 0.12)))
        if y1e - y0e < int(h * 0.25):
            return image_bytes
        return _image_to_jpeg_bytes(img.crop((0, y0e, w, y1e)))
    except Exception:
        log.warning("checkin_ai: isolate time.is canvas failed", exc_info=True)
        return image_bytes


def _parse_normalized_bbox(text: str) -> Optional[tuple[float, float, float, float]]:
    m = _NORMALIZED_BBOX_RE.search(text)
    if not m:
        return None
    try:
        vals = tuple(float(m.group(i)) for i in range(1, 5))
    except ValueError:
        return None
    if not all(0.0 <= v <= 1.0 for v in vals):
        return None
    x0, y0, x1, y1 = vals
    if x1 <= x0 or y1 <= y0:
        return None
    return vals


def _crop_by_normalized_bbox(image_bytes: bytes, bbox: tuple[float, float, float, float]) -> bytes:
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    w, h = img.size
    x0, y0, x1, y1 = bbox
    crop = img.crop((int(x0 * w), int(y0 * h), int(x1 * w), int(y1 * h)))
    return _image_to_jpeg_bytes(crop)


def _crop_checkin_regions(image_bytes: bytes) -> dict[str, bytes]:
    """裁剪时钟区 / Slack 浮窗区，减轻 Telegram 对话长截图干扰。"""
    regions: dict[str, bytes] = {"full": image_bytes}
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        w, h = img.size
        wide_strip = w > h * 1.8 and h < 600
        if w < 200 or (h < 120 and not wide_strip):
            return regions
        if wide_strip:
            # Telegram 横条图（高往往 <320）：只取上部 TIME.IS，避免下部 Bot「打卡时间：…」
            top_h = max(int(h * 0.72), min(h, 200))
            regions["time_top"] = _image_to_jpeg_bytes(img.crop((0, 0, w, top_h)))
            # 仅上部主钟数字，勿含页脚「14时29分」等日照文案
            regions["time_digits"] = _image_to_jpeg_bytes(
                img.crop((int(w * 0.06), int(h * 0.02), int(w * 0.94), int(h * 0.40)))
            )
            regions["time_clock"] = _image_to_jpeg_bytes(img.crop((int(w * 0.03), 0, int(w * 0.97), top_h)))
            regions["time_center"] = _image_to_jpeg_bytes(
                img.crop(_time_center_clock_box(w, h))
            )
        panel = _detect_bright_panel_box(img)
        regions["time_main"] = _image_to_jpeg_bytes(img.crop(_time_main_clock_box(w, h)))
        if panel:
            panel = _clamp_box(panel, w, h)
            _, py0, _, py1 = panel
            ph = max(py1 - py0, 1)
            # 亮面板若在下半部且较矮，多半是页脚区，主钟用 time_main/time_clock
            if py0 > int(h * 0.32) and ph < int(h * 0.45):
                regions["time_panel"] = regions["time_main"]
            else:
                regions["time_panel"] = _image_to_jpeg_bytes(img.crop(panel))
            name_box = _slack_name_panel_box(w, h, panel)
            regions["name_panel"] = _image_to_jpeg_bytes(img.crop(name_box))
            # 略宽备选，浮窗略靠左时 OCR 仍可命中
            alt_box = _slack_name_panel_box(w, h, panel, right_frac=0.38)
            if alt_box != name_box:
                regions["name_panel_alt"] = _image_to_jpeg_bytes(img.crop(alt_box))
            tight_box = _slack_name_panel_tight_box(w, h)
            if tight_box not in (name_box, alt_box):
                regions["name_panel_tight"] = _image_to_jpeg_bytes(img.crop(tight_box))
            row_box = _slack_name_row_box(w, h, panel)
            if row_box not in (name_box, alt_box, tight_box):
                regions["name_panel_row"] = _image_to_jpeg_bytes(img.crop(row_box))
            bottom_box = _slack_name_bottom_corner_box(w, h)
            if wide_strip or h < 500 or bottom_box not in (name_box, alt_box, tight_box, row_box):
                regions["name_panel_bottom"] = _image_to_jpeg_bytes(img.crop(bottom_box))
            overlay_box = None
            if wide_strip or (w > h * 2.0 and h < 550):
                overlay_box = _slack_name_overlay_box(w, h)
                regions["name_panel_overlay"] = _image_to_jpeg_bytes(img.crop(overlay_box))
            log.info(
                "checkin_ai: detected time.is panel box=%s name_panel box=%s tight=%s row=%s bottom=%s overlay=%s",
                panel,
                name_box,
                tight_box,
                row_box,
                bottom_box,
                overlay_box,
            )
        else:
            if "time_main" not in regions:
                regions["time_main"] = _image_to_jpeg_bytes(img.crop(_time_main_clock_box(w, h)))
            name_box = _slack_name_panel_box(w, h, None)
            regions["name_panel"] = _image_to_jpeg_bytes(img.crop(name_box))
            tight_box = _slack_name_panel_tight_box(w, h)
            regions["name_panel_tight"] = _image_to_jpeg_bytes(img.crop(tight_box))
            bottom_box = _slack_name_bottom_corner_box(w, h)
            regions["name_panel_bottom"] = _image_to_jpeg_bytes(img.crop(bottom_box))
            if wide_strip or (w > h * 2.0 and h < 550):
                overlay_box = _slack_name_overlay_box(w, h)
                regions["name_panel_overlay"] = _image_to_jpeg_bytes(img.crop(overlay_box))
            log.info(
                "checkin_ai: name_panel box=%s tight=%s bottom=%s (no bright panel)",
                name_box,
                tight_box,
                bottom_box,
            )
        if not wide_strip:
            # 主钟数字区（仅大号 HH:MM:SS，尽量不含页脚城市行）
            regions["time_digits"] = _image_to_jpeg_bytes(
                img.crop((int(w * 0.10), int(h * 0.06), int(w * 0.90), int(h * 0.42)))
            )
            # 主时钟区（排除页脚城市小字时间）
            regions["time_clock"] = _image_to_jpeg_bytes(
                img.crop((int(w * 0.04), 0, int(w * 0.96), int(h * 0.50)))
            )
        regions["time"] = _image_to_jpeg_bytes(img.crop((0, 0, w, int(h * 0.62))))
        if h < 720 and not wide_strip:
            # Telegram 短截图（上图打卡 + 下方 Bot 回复）：只保留上半部分打卡图
            regions["time_top"] = _image_to_jpeg_bytes(img.crop((0, 0, w, int(h * 0.50))))
        if h / max(w, 1) > 1.2:
            # Telegram 对话长截图：中间嵌入的打卡图
            regions["time_embedded"] = _image_to_jpeg_bytes(
                img.crop((int(w * 0.04), int(h * 0.10), int(w * 0.96), int(h * 0.72)))
            )
        regions["name"] = _image_to_jpeg_bytes(img.crop((int(w * 0.35), int(h * 0.42), w, h)))
    except Exception:
        log.warning("checkin_ai: crop regions skipped", exc_info=True)
    return regions


def _is_tall_chat_screenshot(image_bytes: bytes) -> bool:
    """Telegram 长对话截图（竖长），TIME.IS 横图不算。"""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
        if h >= 360 and w / max(h, 1) < 3.2:
            return False
        return h > w * 1.15
    except Exception:
        return False


def _is_wide_telegram_strip(image_bytes: bytes) -> bool:
    """Telegram 群里的极扁横条（高通常 <380px），易混入 Bot 回复。"""
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        w, h = img.size
        return w > h * 2.2 and h < 380
    except Exception:
        return False


def is_composite_telegram_screenshot(image_bytes: bytes) -> bool:
    """是否为 Telegram 对话/横条压缩图（非相册 TIME.IS 原图），不宜 trust_sender。"""
    if _is_wide_telegram_strip(image_bytes) or _is_tall_chat_screenshot(image_bytes):
        return True
    try:
        from PIL import Image

        w, h = Image.open(io.BytesIO(image_bytes)).size
        # 足够高的 TIME.IS 整页（如 1280×440）不算群聊压缩条
        if h >= 400 and w / max(h, 1) < 3.2:
            return False
        # 极扁横条：嵌入 TIME.IS + Bot 气泡
        return h < 400 and w > h * 1.45
    except Exception:
        return False


def is_composite_checkin_image(*, raw_bytes: bytes, prepared_bytes: bytes) -> bool:
    return is_composite_telegram_screenshot(raw_bytes) or is_composite_telegram_screenshot(
        prepared_bytes
    )


def is_slack_panel_likely_cropped_off(image_bytes: bytes) -> bool:
    """扁图且高度不足时，右下角 Slack 浮窗常被 Telegram 裁掉。"""
    try:
        from PIL import Image

        w, h = Image.open(io.BytesIO(image_bytes)).size
        # TIME.IS + Telegram 资料浮窗标准扁图（约 180～550px 高）姓名区仍完整
        if is_composite_telegram_screenshot(image_bytes) and w > h * 2 and h >= 180:
            return False
        return w > h * 2.4 and h < 360
    except Exception:
        return False


# 横条/对话截图只信任这些裁剪区的时间，避免 time_digits 读到 Bot「打卡时间」
_TRUSTED_TIME_CROPS_COMPOSITE = frozenset(
    {"time_panel", "time_top", "time_clock", "time_embedded", "time"}
    # 不含 time_digits / full：横条图里常混入 Bot「打卡时间：20:12:24」
)


def _is_flat_timeis_strip_bytes(prepared_bytes: bytes) -> bool:
    """Telegram 扁图 TIME.IS（如 1280×463）：主钟常落在 time_top，不在 time_main。"""
    try:
        from PIL import Image

        w, h = Image.open(io.BytesIO(prepared_bytes)).size
        return w > h * 2 and h < 550
    except Exception:
        return False


def _time_crop_keys_for_image(prepared_bytes: bytes, regions: dict[str, bytes]) -> tuple[str, ...]:
    """先裁 TIME.IS 面板/主钟区；扁图优先 time_top（复现：time_main 空、time_top 有 20:31）。"""
    if "time_main" in regions or "time_panel" in regions:
        if _is_flat_timeis_strip_bytes(prepared_bytes):
            order = (
                "time_center",
                "time_top",
                "time_main",
                "time_digits",
                "time_clock",
                "time_panel",
                "time",
            )
        else:
            order = ("time_main", "time_digits", "time_clock", "time", "time_panel")
        keys = [k for k in order if k in regions]
        if keys:
            return tuple(keys)
    panel_first = (
        "time_panel",
        "time_clock",
        "time_embedded",
        "time_digits",
        "time",
    )
    if _is_tall_chat_screenshot(prepared_bytes) or _is_wide_telegram_strip(prepared_bytes):
        keys = [k for k in panel_first if k in regions]
        return tuple(keys) if keys else ("time_panel", "time_clock")
    if "time_panel" in regions:
        return tuple(k for k in panel_first if k in regions)
    return _TIME_CROP_ORDER


def _response_looks_like_chat_ui(text: str) -> bool:
    low = text.lower()
    return any(m.lower() in low or m in text for m in _CHAT_SCREENSHOT_MARKERS)


async def _list_ollama_model_names(*, root: str, timeout: float) -> set[str]:
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.get(f"{root}/api/tags")
        resp.raise_for_status()
        payload = resp.json()
    names: set[str] = set()
    for item in payload.get("models") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            names.add(name)
            names.add(name.split(":")[0])
    return names


def _model_installed(model: str, available: set[str]) -> bool:
    if model in available:
        return True
    base = model.split(":")[0]
    return base in available


def _ollama_payload_to_text(payload: dict[str, Any]) -> Optional[str]:
    """从 Ollama /api/chat 响应中提取文本（兼容 content / response / thinking）。"""
    if not isinstance(payload, dict):
        return None
    top = payload.get("response")
    if isinstance(top, str) and top.strip():
        return top.strip()

    msg = payload.get("message")
    if isinstance(msg, dict):
        for key in ("content", "thinking"):
            part = msg.get(key)
            if isinstance(part, str) and part.strip():
                return part.strip()
            if isinstance(part, list):
                bits = [str(p).strip() for p in part if p and str(p).strip()]
                if bits:
                    return "\n".join(bits)
    return None


async def _post_ollama_vision(
    *,
    client: httpx.AsyncClient,
    root: str,
    model: str,
    image_b64: str,
    prompt: str,
    use_generate: bool,
    ollama_options: dict[str, Any],
) -> dict[str, Any]:
    if use_generate:
        body: dict[str, Any] = {
            "model": model,
            "stream": False,
            "prompt": prompt,
            "images": [image_b64],
            "options": ollama_options,
        }
        resp = await client.post(f"{root}/api/generate", json=body)
    else:
        body = {
            "model": model,
            "stream": False,
            "options": ollama_options,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_b64],
                }
            ],
        }
        resp = await client.post(f"{root}/api/chat", json=body)
    if resp.status_code == 404:
        raise httpx.HTTPStatusError(
            "model not found",
            request=resp.request,
            response=resp,
        )
    resp.raise_for_status()
    return resp.json()


async def _call_ollama_vision(
    *,
    root: str,
    model: str,
    image_b64: str,
    image_digest: str,
    config: CheckinAiConfig,
    prompt: str | None = None,
    allow_empty: bool = False,
    num_predict: int | None = None,
    max_attempts: int = 2,
    skip_chat_fallback: bool = False,
) -> Optional[str]:
    """调用 Ollama 视觉；优先无状态 /api/generate，并按图片哈希隔离每次推理。"""
    text_prompt = prompt or _EXTRACT_PROMPT
    timeout = httpx.Timeout(config.timeout_seconds, connect=30.0)
    last_payload: dict[str, Any] | None = None
    attempts = max(1, min(max_attempts, 2))
    async with httpx.AsyncClient(timeout=timeout) as client:
        # 优先 generate（无对话上下文），避免连续打卡时 chat 沿用上一次结果
        for attempt in range(attempts):
            opts = _ollama_options_for_image(image_digest, attempt=attempt)
            if num_predict is not None:
                opts["num_predict"] = int(num_predict)
            t0 = time.perf_counter()
            last_payload = await _post_ollama_vision(
                client=client,
                root=root,
                model=model,
                image_b64=image_b64,
                prompt=text_prompt,
                use_generate=True,
                ollama_options=opts,
            )
            elapsed = time.perf_counter() - t0
            eval_count = last_payload.get("eval_count")
            log.info(
                "checkin_ai: ollama generate done model=%s sec=%.1f attempt=%s eval=%s digest=%s",
                model,
                elapsed,
                attempt + 1,
                eval_count,
                image_digest[:12],
            )
            content = _ollama_payload_to_text(last_payload)
            if content and not _response_looks_like_chat_ui(content):
                return content
            if content and _response_looks_like_chat_ui(content):
                log.warning("checkin_ai: chat ui noise in vision reply, retrying")
            else:
                log.warning(
                    "checkin_ai: empty ollama generate attempt=%s eval=%s reason=%s",
                    attempt + 1,
                    eval_count,
                    last_payload.get("done_reason"),
                )
            if attempts > 1:
                await asyncio.sleep(0.4)

        if not skip_chat_fallback:
            opts = _ollama_options_for_image(image_digest, attempt=99)
            if num_predict is not None:
                opts["num_predict"] = int(num_predict)
            t0 = time.perf_counter()
            last_payload = await _post_ollama_vision(
                client=client,
                root=root,
                model=model,
                image_b64=image_b64,
                prompt=text_prompt,
                use_generate=False,
                ollama_options=opts,
            )
            log.info(
                "checkin_ai: ollama chat fallback model=%s sec=%.1f eval=%s digest=%s",
                model,
                time.perf_counter() - t0,
                last_payload.get("eval_count"),
                image_digest[:12],
            )
    content = _ollama_payload_to_text(last_payload or {})
    if content and not _response_looks_like_chat_ui(content):
        return content
    if allow_empty:
        return None
    raise ValueError("empty ollama response")


async def _call_openai_vision(
    *,
    base_url: str,
    model: str,
    image_b64: str,
    config: CheckinAiConfig,
) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    body = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": _EXTRACT_PROMPT},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                ],
            }
        ],
    }
    async with httpx.AsyncClient(timeout=config.timeout_seconds) as client:
        resp = await client.post(url, headers=headers, json=body)
        resp.raise_for_status()
        payload = resp.json()
    content = payload["choices"][0]["message"]["content"]
    if isinstance(content, list):
        text_parts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
        content = "\n".join(text_parts)
    if not isinstance(content, str) or not content.strip():
        raise ValueError("empty openai response")
    return content


_CLOCK_IN_TEXT_RE = re.compile(r"(?<![0-9])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![0-9])")
_NORMALIZED_BBOX_RE = re.compile(
    r"\[\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*([0-9.]+)\s*\]"
)


def _strip_bot_reply_text(text: str) -> str:
    """截掉 Telegram 对话里 Bot 回复段落，避免误读历史打卡时间。"""
    earliest = len(text)
    for marker in _BOT_REPLY_CUT_MARKERS:
        idx = text.find(marker)
        if 0 < idx < earliest:
            earliest = idx
    return text[:earliest] if earliest < len(text) else text


def _clock_candidates_from_text(text: str) -> list[tuple[str, bool]]:
    """从文本收集全部 HH:MM(:SS) 候选；has_sec 表示模型明确给出了秒。"""
    text = _strip_bot_reply_text(text)
    found: list[tuple[str, bool]] = []
    seen: set[str] = set()
    for line in re.split(r"[\r\n]+", text):
        if any(m in line for m in _BOT_REPLY_LINE_MARKERS):
            continue
        for m in _CLOCK_IN_TEXT_RE.finditer(line):
            h, mi = int(m.group(1)), int(m.group(2))
            sec_g = m.group(3)
            if h > 23 or mi > 59:
                continue
            if sec_g is None:
                cand = f"{h:02d}:{mi:02d}:00"
                has_sec = False
            else:
                sec = int(sec_g)
                if sec > 59:
                    continue
                cand = f"{h:02d}:{mi:02d}:{sec:02d}"
                has_sec = True
            if cand not in seen:
                seen.add(cand)
                found.append((cand, has_sec))
    return found


def _minutes_from_reference(*, clock_str: str, reference_utc: datetime, tz_name: str) -> float:
    parts = clock_str.split(":")
    if len(parts) != 3:
        return 1e9
    try:
        t = dt_time(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return 1e9
    tz = ZoneInfo(tz_name)
    ref_local = reference_utc.astimezone(tz)
    base_date = ref_local.date()
    best_sec = 1e18
    for offset in (-1, 0, 1):
        d = base_date + timedelta(days=offset)
        local_dt = datetime.combine(d, t, tzinfo=tz)
        best_sec = min(best_sec, abs((local_dt.astimezone(timezone.utc) - reference_utc).total_seconds()))
    return best_sec / 60.0


def _is_prompt_echo_clock(clock_str: str) -> bool:
    t = (clock_str or "").strip()
    if t in _VISION_PROMPT_ECHO_CLOCKS:
        return True
    return t.startswith("20:12:24")


def _clock_inclusion_skew_limit(max_skew_minutes: int) -> int:
    """多时钟候选时：与当前时间相差不超过 1 小时即认可。"""
    return min(max(1, max_skew_minutes), 60)


def _detect_clock_timezone_hint(text: str) -> Optional[str]:
    low = (text or "").lower()
    if not low:
        return None
    if "北京时间" in text or "beijing" in low:
        return "Asia/Shanghai"
    if "曼谷" in text or "bangkok" in low:
        return "Asia/Bangkok"
    return None


def _ocr_plain_text_from_bytes(crop_bytes: bytes, *, fast: bool = True) -> str:
    """宽松 OCR 拉取区域全文（用于时钟包含法）。"""
    try:
        from PIL import Image, ImageEnhance, ImageOps

        from services.checkin_ocr_engine import ocr_backend_available, ocr_engine_name, ocr_image_to_string
    except ImportError:
        return ""

    if not ocr_backend_available():
        return ""
    try:
        img = Image.open(io.BytesIO(crop_bytes)).convert("RGB")
    except Exception:
        return ""

    w, h = img.size
    scale = max(2, min(4 if fast else 5, 2000 // max(w, h, 1)))
    if scale > 1:
        img = img.resize((w * scale, h * scale), Image.Resampling.LANCZOS)
    gray = ImageEnhance.Contrast(ImageOps.autocontrast(img.convert("L"))).enhance(2.2)
    inv = ImageOps.invert(gray)
    cfgs = (
        ["--oem 3 --psm 6", "--oem 3 --psm 11"]
        if fast
        else ["--oem 3 --psm 6", "--oem 3 --psm 11", "--oem 3 -c tessedit_char_whitelist=0123456789: --psm 6"]
    )
    parts: list[str] = []
    for variant in (gray, inv):
        if ocr_engine_name() == "easyocr":
            try:
                t = ocr_image_to_string(variant, fast=fast)
            except Exception:
                continue
            if t and t.strip():
                parts.append(t)
            continue
        for cfg in cfgs:
            try:
                t = ocr_image_to_string(variant, lang="eng", config=cfg, fast=fast)
            except Exception:
                continue
            if t and t.strip():
                parts.append(t)
    return "\n".join(parts)


_CLOCK_INCLUSION_FAST_KEYS = frozenset({"full", "time_center", "time_top"})
_CLOCK_INCLUSION_DIGIT_KEYS = frozenset(
    {"time_center", "time_top", "time_main", "time_clock", "time_digits", "full"}
)


def _add_clock_candidate(found: dict[str, bool], cand: str, has_sec: bool) -> None:
    if _is_prompt_echo_clock(cand):
        return
    if cand not in found or (has_sec and not found[cand]):
        found[cand] = has_sec


def _collect_clock_candidates_from_regions(
    regions: dict[str, bytes],
    *,
    prepared_bytes: bytes | None,
    fast: bool,
    tz_name: str = "Asia/Shanghai",
) -> tuple[dict[str, bool], Optional[str]]:
    """合并多区 OCR 文本 + 数字钟专扫，收集全部 HH:MM(:SS) 候选（包含法）。"""
    if prepared_bytes and _is_flat_timeis_strip_bytes(prepared_bytes):
        keys = (
            "full",
            "time_center",
            "time_top",
            "time_main",
            "time_clock",
            "time_panel",
            "time_digits",
        )
    else:
        keys = (
            "full",
            "time_center",
            "time_top",
            "time_main",
            "time_clock",
            "time_panel",
            "time_digits",
            "time",
        )
    if fast:
        keys = tuple(k for k in keys if k in _CLOCK_INCLUSION_FAST_KEYS)
    found: dict[str, bool] = {}
    tz_hint: Optional[str] = None
    digit_keys = _CLOCK_INCLUSION_DIGIT_KEYS if not fast else _CLOCK_INCLUSION_FAST_KEYS
    for key in keys:
        chunk = regions.get(key)
        if not chunk:
            continue
        text = _ocr_plain_text_from_bytes(chunk, fast=fast)
        if text and not tz_hint:
            tz_hint = _detect_clock_timezone_hint(text)
        for cand, has_sec in _clock_candidates_from_text(text):
            _add_clock_candidate(found, cand, has_sec)
        if key in digit_keys:
            t = _ocr_clock_from_crop_bytes(
                chunk, reference_utc=None, tz_name=tz_name, fast=fast
            )
            if t:
                parts = t.split(":")
                has_sec = len(parts) == 3 and parts[2] != "00"
                _add_clock_candidate(found, t, has_sec)
    return found, tz_hint


def _pick_clock_by_inclusion(
    candidates: dict[str, bool],
    *,
    reference_utc: datetime | None,
    tz_name: str,
    max_skew_minutes: int,
) -> tuple[Optional[str], bool]:
    """多个时钟字符串时，取与 reference 最接近且 skew 在窗口内的一个。

    返回 (选中时间, 是否曾出现超窗候选)。
    """
    if not candidates:
        return None, False
    window = _clock_inclusion_skew_limit(max_skew_minutes)
    if reference_utc is None:
        with_sec = [c for c, hs in candidates.items() if hs]
        return (with_sec or list(candidates.keys()))[0], False

    pool: list[tuple[float, int, str]] = []
    rejected: list[str] = []
    for clock, has_sec in candidates.items():
        skew = _minutes_from_reference(
            clock_str=clock, reference_utc=reference_utc, tz_name=tz_name
        )
        # OCR/时区换算存在秒级抖动，给 60 分钟边界留少量容差。
        if skew <= (window + 0.5):
            pool.append((skew, 0 if has_sec else 1, clock))
        else:
            rejected.append(f"{clock}({skew:.0f}m)")
    if not pool:
        if rejected:
            log.warning(
                "checkin_ai: clock inclusion: no time within %s min, saw %s",
                window,
                ", ".join(rejected[:6]),
            )
        return None, bool(rejected)
    pool.sort()
    pick = pool[0][2]
    log.info(
        "checkin_ai: clock inclusion pick %s skew_min=%.1f (window<=%s, %d candidates)",
        pick,
        pool[0][0],
        window,
        len(pool),
    )
    return pick, False


def ocr_clock_by_global_inclusion(
    regions: dict[str, bytes],
    *,
    reference_utc: datetime | None,
    tz_name: str,
    max_skew_minutes: int = 60,
    prepared_bytes: bytes | None = None,
    fast: bool = True,
) -> tuple[Optional[str], bool]:
    cands, tz_hint = _collect_clock_candidates_from_regions(
        regions,
        prepared_bytes=prepared_bytes,
        fast=fast,
        tz_name=tz_name,
    )
    effective_tz = tz_hint or tz_name
    if tz_hint and tz_hint != tz_name:
        log.info(
            "checkin_ai: clock inclusion timezone override %s -> %s",
            tz_name,
            tz_hint,
        )
    return _pick_clock_by_inclusion(
        cands,
        reference_utc=reference_utc,
        tz_name=effective_tz,
        max_skew_minutes=max_skew_minutes,
    )


def _choose_clock_from_crop_hits(
    clock_hits: list[tuple[int, str, str]],
    *,
    reference_utc: datetime | None,
    tz_name: str,
) -> tuple[Optional[str], str]:
    """多裁剪区投票；丢弃 prompt 复读时间与不可信裁剪。"""
    if not clock_hits:
        return None, ""
    hits = [h for h in clock_hits if h[1] not in {"full", "time_top", "time"}]
    if not hits:
        hits = [h for h in clock_hits if not _is_prompt_echo_clock(h[2])]
    if not hits:
        hits = list(clock_hits)
    non_echo = [h for h in hits if not _is_prompt_echo_clock(h[2])]
    if non_echo:
        hits = non_echo
    if reference_utc:
        hits.sort(
            key=lambda x: (
                _minutes_from_reference(
                    clock_str=x[2], reference_utc=reference_utc, tz_name=tz_name
                ),
                x[0],
            )
        )
        return hits[0][2], hits[0][1]
    from collections import Counter

    counts = Counter(t for _, _, t in hits)
    best_time, vote = counts.most_common(1)[0]
    if vote >= 2:
        for pri, ck, t in sorted(hits, key=lambda x: x[0]):
            if t == best_time:
                return t, ck
    hits.sort(key=lambda x: x[0])
    return hits[0][2], hits[0][1]


def _ocr_clock_from_crop_bytes(
    crop_bytes: bytes,
    *,
    reference_utc: datetime | None,
    tz_name: str,
    fast: bool = False,
) -> Optional[str]:
    """OCR 读取 TIME.IS 主钟 HH:MM:SS（moondream 空回时兜底）。"""
    try:
        from PIL import Image, ImageEnhance, ImageOps

        from services.checkin_ocr_engine import ocr_backend_available, ocr_engine_name, ocr_image_to_string
    except ImportError:
        return None

    if not ocr_backend_available():
        return None
    try:
        img = Image.open(io.BytesIO(crop_bytes)).convert("RGB")
    except Exception:
        return None

    w, h = img.size
    aspect = w / max(h, 1)
    # 扁图右上常有 Slack 浮窗，主钟在左侧
    if aspect >= 2.0 and h < 560:
        crops = [
            img.crop((0, 0, int(w * 0.56), int(h * 0.62))),
            img.crop((int(w * 0.02), 0, int(w * 0.58), int(h * 0.58))),
        ]
    else:
        crops = [img.crop((int(w * 0.04), 0, int(w * 0.96), int(h * 0.52)))]
    cfg = "--oem 3 -c tessedit_char_whitelist=0123456789:"
    best: Optional[str] = None
    best_dist = 1e18
    for sub in crops:
        sw, sh = sub.size
        scale = max(4, min(8, 2800 // max(sw, sh, 1)))
        if scale > 1:
            sub = sub.resize((sw * scale, sh * scale), Image.Resampling.LANCZOS)
        base_gray = ImageOps.autocontrast(sub.convert("L"))
        inverted = ImageOps.invert(base_gray)
        if fast:
            variants = [
                ImageEnhance.Contrast(base_gray).enhance(2.6),
                ImageEnhance.Contrast(inverted).enhance(2.4),
            ]
            psms = (7, 8)
        else:
            variants = [
                ImageEnhance.Contrast(base_gray).enhance(2.4),
                ImageEnhance.Contrast(base_gray).enhance(3.2),
                ImageEnhance.Contrast(inverted).enhance(2.6),
                base_gray.point(lambda p: 255 if p > 155 else 0),
                inverted.point(lambda p: 255 if p > 140 else 0),
            ]
            psms = (7, 8, 6, 13)
        for gray in variants:
            psm_list = (0,) if ocr_engine_name() == "easyocr" else psms
            for psm in psm_list:
                try:
                    if ocr_engine_name() == "easyocr":
                        text = ocr_image_to_string(
                            gray, fast=fast, whitelist="0123456789:"
                        )
                    else:
                        text = ocr_image_to_string(
                            gray, lang="eng", config=f"{cfg} --psm {psm}", fast=fast
                        )
                except Exception:
                    continue
                cands = _clock_candidates_from_text(text or "")
                if not cands:
                    continue
                pick = _pick_best_clock_time(
                    cands, reference_utc=reference_utc, tz_name=tz_name
                )
                if not pick:
                    continue
                if reference_utc is None:
                    return pick
                dist = _minutes_from_reference(
                    clock_str=pick, reference_utc=reference_utc, tz_name=tz_name
                )
                if dist < best_dist:
                    best_dist = dist
                    best = pick
                    if dist <= 3:
                        return best
    return best


_PRIMARY_CLOCK_REGIONS = frozenset(
    {
        "time_center",
        "time_top",
        "time_main",
        "time_digits",
        "time_clock",
        "time_panel",
    }
)


def _clock_skew_minutes(
    clock_str: str, *, reference_utc: datetime | None, tz_name: str
) -> float:
    if reference_utc is None:
        return 0.0
    return _minutes_from_reference(
        clock_str=clock_str, reference_utc=reference_utc, tz_name=tz_name
    )


def ocr_clock_from_regions(
    regions: dict[str, bytes],
    *,
    reference_utc: datetime | None,
    tz_name: str,
    prepared_bytes: bytes | None = None,
    max_skew_minutes: int = 60,
    fast: bool = False,
) -> tuple[Optional[str], bool]:
    """全局 OCR + 包含法：收集全部 HH:MM(:SS)，取与发送时间最接近且在 1 小时内者。"""
    pick, skew1 = ocr_clock_by_global_inclusion(
        regions,
        reference_utc=reference_utc,
        tz_name=tz_name,
        max_skew_minutes=max_skew_minutes,
        prepared_bytes=prepared_bytes,
        fast=True,
    )
    if pick:
        return pick, skew1
    if fast:
        return None, skew1
    pick2, skew2 = ocr_clock_by_global_inclusion(
        regions,
        reference_utc=reference_utc,
        tz_name=tz_name,
        max_skew_minutes=max_skew_minutes,
        prepared_bytes=prepared_bytes,
        fast=False,
    )
    return pick2, skew1 or skew2


def ocr_date_from_regions(
    regions: dict[str, bytes],
    *,
    prepared_bytes: bytes | None = None,
    fast: bool = True,
) -> Optional[str]:
    """从 TIME.IS 左侧日期区 OCR 解析 YYYY-MM-DD（如 2026年5月29日）。"""
    from services.checkin_clock_time_service import extract_clock_date_from_text

    keys = ("full", "time_top", "time_center", "time_main", "time_panel", "time_clock")
    for key in keys:
        chunk = regions.get(key)
        if not chunk and key == "full" and prepared_bytes:
            chunk = prepared_bytes
        if not chunk:
            continue
        text = _ocr_plain_text_from_bytes(chunk, fast=fast)
        found = extract_clock_date_from_text(text or "")
        if found:
            log.info("checkin_ai: date from ocr region=%s value=%s", key, found)
            return found
    if not fast:
        return None
    return ocr_date_from_regions(regions, prepared_bytes=prepared_bytes, fast=False)


def _pick_best_clock_time(
    candidates: list[tuple[str, bool]],
    *,
    reference_utc: datetime | None,
    tz_name: str = "Asia/Shanghai",
) -> Optional[str]:
    if not candidates:
        return None
    with_sec = [c for c, has_sec in candidates if has_sec]
    pool = with_sec if with_sec else [c for c, _ in candidates]
    if reference_utc is None or len(pool) == 1:
        return pool[0]
    return min(pool, key=lambda c: _minutes_from_reference(clock_str=c, reference_utc=reference_utc, tz_name=tz_name))


def _extract_clock_time_from_text(
    text: str,
    *,
    reference_utc: datetime | None = None,
    tz_name: str = "Asia/Shanghai",
) -> Optional[str]:
    """从模型回复中提取时间；多候选时取最接近 reference 的时刻（避免误读页脚城市时间）。"""
    return _pick_best_clock_time(
        _clock_candidates_from_text(text),
        reference_utc=reference_utc,
        tz_name=tz_name,
    )


def _extract_identity_from_text(text: str, *, expected_username: str | None) -> tuple[Optional[str], Optional[str]]:
    if expected_username:
        eu = re.escape(expected_username.strip())
        full = re.search(rf"\b({eu}\s*[A-Za-z]?)\b", text, flags=re.IGNORECASE)
        if full:
            disp = full.group(1).strip()
            return disp, expected_username.strip()
        if re.search(rf"\b{eu}\b", text, flags=re.IGNORECASE):
            return expected_username.strip(), expected_username.strip()

    for pat in (
        r'"display_name"\s*:\s*"([^"]+)"',
        r'"username_hint"\s*:\s*"([^"]+)"',
        r"\b(Y_(?:UX|TC)_[A-Za-z0-9]+(?:\s+[\u4e00-\u9fff]+)?)\b",
        r"\b(Y_(?:UX|TC)_[A-Za-z0-9]+)\b",
        r"\b([A-Za-z][A-Za-z0-9_]{3,31})\s+[A-Z]\b",
    ):
        um = re.search(pat, text, flags=re.IGNORECASE)
        if um:
            val = re.sub(r"^[^A-Za-z0-9_\u4e00-\u9fff]+|[^A-Za-z0-9_\u4e00-\u9fff]+$", "", um.group(1).strip())
            if val.lower() not in {"null", "the", "image", "clock", "time", "profile"}:
                hint = _sanitize_field(val, field="username_hint")
                if hint:
                    return val, hint
    return None, None


def _merge_extractions(base: CheckinImageExtraction, extra: CheckinImageExtraction) -> CheckinImageExtraction:
    return CheckinImageExtraction(
        display_name=base.display_name or extra.display_name,
        username_hint=base.username_hint or extra.username_hint,
        clock_time=base.clock_time or extra.clock_time,
        clock_date=base.clock_date or extra.clock_date,
        timezone_iana=base.timezone_iana or extra.timezone_iana,
        confidence=base.confidence or extra.confidence,
        clock_skew_rejected=base.clock_skew_rejected or extra.clock_skew_rejected,
    )


def _fallback_extraction_from_text(
    text: str,
    *,
    expected_username: str | None = None,
    reference_utc: datetime | None = None,
    tz_name: str = "Asia/Shanghai",
) -> CheckinImageExtraction:
    """模型未返回合法 JSON 时，从原文尽量抽取时间与用户名。"""
    clock_time = _extract_clock_time_from_text(text, reference_utc=reference_utc, tz_name=tz_name)
    from services.checkin_clock_time_service import extract_clock_date_from_text

    clock_date = extract_clock_date_from_text(text)

    display_name, username_hint = _extract_identity_from_text(text, expected_username=expected_username)

    raw = CheckinImageExtraction(
        display_name=display_name,
        username_hint=username_hint,
        clock_time=clock_time,
        clock_date=clock_date,
        timezone_iana=None,
        confidence=None,
    )
    cleaned = CheckinImageExtraction(
        display_name=_sanitize_field(raw.display_name, field="display_name"),
        username_hint=_sanitize_field(raw.username_hint, field="username_hint"),
        clock_time=_sanitize_field(raw.clock_time, field="clock_time"),
        clock_date=_sanitize_field(raw.clock_date, field="clock_date"),
        timezone_iana=_sanitize_field(raw.timezone_iana, field="timezone_iana"),
        confidence=None,
    )
    return _enrich_identity_from_display(cleaned)


def _enrich_identity_from_display(extraction: CheckinImageExtraction) -> CheckinImageExtraction:
    """仅有 display_name（如 benrenxing Z）时，补全 username_hint。"""
    if extraction.username_hint or not extraction.display_name:
        return extraction
    m = _SLACK_HANDLE_RE.match(extraction.display_name.strip())
    if not m:
        return extraction
    hint = _sanitize_field(m.group(1), field="username_hint")
    if not hint:
        return extraction
    return CheckinImageExtraction(
        display_name=extraction.display_name,
        username_hint=hint,
        clock_time=extraction.clock_time,
        clock_date=extraction.clock_date,
        timezone_iana=extraction.timezone_iana,
        confidence=extraction.confidence,
    )


def _parse_model_content(content: str, *, expected_username: str | None = None) -> CheckinImageExtraction:
    try:
        parsed = json.loads(_strip_json_payload(content))
    except json.JSONDecodeError:
        log.warning("checkin_ai: invalid json from model, trying fallback: %s", content[:500])
        return _fallback_extraction_from_text(content, expected_username=expected_username)
    if not isinstance(parsed, dict):
        return _fallback_extraction_from_text(content, expected_username=expected_username)
    return _parse_extraction_payload(parsed)


def _region_b64(regions: dict[str, bytes], key: str, *, fallback_b64: str) -> str:
    chunk = regions.get(key)
    if not chunk:
        return fallback_b64
    return base64.standard_b64encode(_prepare_image_bytes(chunk)).decode("ascii")


async def _supplement_extraction_ollama(
    *,
    root: str,
    model: str,
    image_b64: str,
    prepared_bytes: bytes,
    config: CheckinAiConfig,
    extraction: CheckinImageExtraction,
    expected_username: str | None,
    expected_english_name: str | None = None,
    reference_utc: datetime | None = None,
    shift_timezone: str = "Asia/Shanghai",
    skip_name_verify: bool = False,
    vision_enabled: bool = True,
) -> tuple[CheckinImageExtraction, Optional[CheckinAiExtractError]]:
    """区域裁剪 + OCR；vision_enabled 时再用 moondream 读 Slack 浮窗。"""
    texts: list[str] = []
    name_texts: list[str] = []
    pre_isolate_bytes = prepared_bytes
    isolated = _isolate_timeis_canvas(prepared_bytes)
    time_canvas_bytes = pre_isolate_bytes
    name_source_bytes = pre_isolate_bytes
    composite = is_composite_telegram_screenshot(pre_isolate_bytes)
    if isolated is not prepared_bytes and composite:
        try:
            from PIL import Image

            o_sz = Image.open(io.BytesIO(pre_isolate_bytes)).size
            n_sz = Image.open(io.BytesIO(isolated)).size
            log.info("checkin_ai: isolated time.is canvas %sx%s -> %sx%s", *o_sz, *n_sz)
            time_canvas_bytes = isolated
            prepared_bytes = isolated
            image_b64 = base64.standard_b64encode(_prepare_image_bytes(prepared_bytes)).decode(
                "ascii"
            )
            if n_sz[1] < 380 or is_slack_panel_likely_cropped_off(isolated):
                name_source_bytes = pre_isolate_bytes
                log.info(
                    "checkin_ai: name crops from pre-isolate canvas (isolated too short for slack)"
                )
        except Exception:
            log.info("checkin_ai: isolated time.is canvas for region crop")
            time_canvas_bytes = isolated
            prepared_bytes = isolated
    regions = _crop_checkin_regions(time_canvas_bytes)
    if name_source_bytes is not time_canvas_bytes:
        for key, chunk in _crop_checkin_regions(name_source_bytes).items():
            if key.startswith("name_"):
                regions[key] = chunk
    from services.checkin_service import ALLOWED_TIMEZONES

    tz_name = shift_timezone if shift_timezone in ALLOWED_TIMEZONES else "Asia/Shanghai"
    from services.checkin_ocr_executor import run_ocr_cpu

    clock_ocr_task: Optional[asyncio.Task[tuple[Optional[str], bool]]] = None
    date_ocr_task: Optional[asyncio.Task[Optional[str]]] = None
    if not extraction.clock_time:
        clock_ocr_task = asyncio.create_task(
            run_ocr_cpu(
                ocr_clock_from_regions,
                regions,
                reference_utc=reference_utc,
                tz_name=tz_name,
                prepared_bytes=time_canvas_bytes,
                max_skew_minutes=config.max_clock_skew_minutes,
                fast=True,
            )
        )
    if not extraction.clock_date:
        date_ocr_task = asyncio.create_task(
            run_ocr_cpu(
                ocr_date_from_regions,
                regions,
                prepared_bytes=time_canvas_bytes,
                fast=True,
            )
        )

    name_panel_keys = (
        "name_panel_overlay",
        "name_panel_bottom",
        "name_panel_row",
        "name_panel_tight",
        "name_panel",
        "name_panel_alt",
    )
    name_panel_crops: list[bytes] = []
    for key in name_panel_keys:
        b = regions.get(key)
        if b and b not in name_panel_crops:
            name_panel_crops.append(b)
    panel_bytes = name_panel_crops[0] if name_panel_crops else None
    try:
        from PIL import Image as _PILImage

        _img_w, _img_h = _PILImage.open(io.BytesIO(time_canvas_bytes)).size
    except Exception:
        _img_w, _img_h = 1280, 800
    _flat_timeis = _img_w > _img_h * 2 and _img_h < 550
    _thorough_key = "name_panel_bottom"
    if _flat_timeis:
        # 扁图 Telegram：bottom/overlay 比单 overlay 更易 OCR 到 benrenxing（日志与复现一致）
        flat_pref = (
            "name_panel_bottom",
            "name_panel_overlay",
            "name_panel_row",
            "name_panel_tight",
            "name_panel",
            "name_panel_alt",
        )
        flat_crops: list[bytes] = []
        for key in flat_pref:
            b = regions.get(key)
            if b and b not in flat_crops:
                flat_crops.append(b)
        if flat_crops:
            name_panel_crops = flat_crops
            panel_bytes = flat_crops[0]
    verify_mode = config.name_verify_mode
    identity_done = skip_name_verify or has_valid_identity_fields(extraction)
    if (
        panel_bytes
        and verify_mode in ("both", "ocr", "vision")
        and not identity_done
        and is_slack_panel_likely_cropped_off(name_source_bytes)
        and not is_composite_telegram_screenshot(name_source_bytes)
    ):
        from services.checkin_user_message import MSG_NAME_MISMATCH

        return extraction, CheckinAiExtractError("AI_IMAGE_CROPPED", MSG_NAME_MISMATCH)
    if panel_bytes and verify_mode in ("both", "ocr", "vision") and not identity_done:
        from services.checkin_name_verify_service import (
            SlackNameRead,
            _blob_shows_other_person,
            _channel_includes_registered,
            _read_identity_blob,
            ocr_hunt_regions_parallel,
            ocr_quick_other_person_parallel,
            ocr_thorough_best_panel,
            ocr_hunt_username_in_image,
            ocr_slack_name_from_panel,
            verify_slack_name_dual,
            vision_read_from_raw,
        )

        vision_panel = _upscale_bytes_for_vision(panel_bytes, min_side=512)
        panel_b64 = base64.standard_b64encode(_prepare_image_bytes(vision_panel)).decode(
            "ascii"
        )
        panel_digest = _digest_from_b64(panel_b64)
        vision_read = SlackNameRead(None, None, "vision")
        ocr_read = SlackNameRead(None, None, "ocr")
        ocr_avail = True

        async def _vision_name_task() -> SlackNameRead:
            if not vision_enabled or verify_mode not in ("both", "vision"):
                return SlackNameRead(None, None, "vision")
            try:
                n_raw = await _call_ollama_vision(
                    root=root,
                    model=model,
                    image_b64=panel_b64,
                    image_digest=panel_digest,
                    config=config,
                    prompt=_name_focus_prompt(expected_username=expected_username),
                    allow_empty=True,
                    num_predict=64,
                    max_attempts=1,
                    skip_chat_fallback=True,
                )
                if n_raw:
                    name_texts.append(n_raw)
                read = vision_read_from_raw(n_raw or "")
                exp = (expected_username or "").strip()
                if exp and n_raw and exp.lower() in (n_raw or "").lower():
                    read = SlackNameRead(exp, exp, "vision", raw_text=(n_raw or "")[:120])
                v_tok = (read.username_hint or read.display_name or "").strip()
                log.info(
                    "checkin_name: vision panel raw=%r -> token=%s",
                    (n_raw or "")[:100],
                    v_tok or None,
                )
                if v_tok and _is_vision_prompt_echo(v_tok):
                    return SlackNameRead(None, None, "vision")
                return read
            except Exception:
                log.warning("checkin_ai: vision name_panel failed", exc_info=True)
                return SlackNameRead(None, None, "vision")

        async def _ocr_fast_task() -> tuple[SlackNameRead, bool]:
            if verify_mode not in ("both", "ocr"):
                return SlackNameRead(None, None, "ocr"), True
            extra = name_panel_crops[1:4] if len(name_panel_crops) > 1 else None
            return await run_ocr_cpu(
                ocr_slack_name_from_panel,
                panel_bytes,
                extra_panels=extra,
                expected_username=expected_username,
                fast=True,
            )

        hunt_prefetch_task: Optional[asyncio.Task[Optional[SlackNameRead]]] = None
        if verify_mode in ("both", "ocr") and expected_username:
            hunt_prefetch_task = asyncio.create_task(
                run_ocr_cpu(
                    ocr_hunt_regions_parallel,
                    regions,
                    expected_username or "",
                )
            )

        t_name0 = time.perf_counter()
        vision_read, (ocr_read, ocr_avail) = await asyncio.gather(
            _vision_name_task(),
            _ocr_fast_task(),
        )
        log.info("checkin_name: vision+ocr fast parallel %.1fs", time.perf_counter() - t_name0)

        if vision_enabled and verify_mode == "both" and expected_username:
            other = _blob_shows_other_person(
                _read_identity_blob(vision_read),
                expected_username=expected_username,
                expected_english_name=expected_english_name,
            )
            if other:
                log.info("checkin_name: vision shows other person clue=%s", other)
                from services.checkin_user_message import MSG_NAME_MISMATCH

                return extraction, CheckinAiExtractError(
                    "AI_USER_OTHER_PERSON", MSG_NAME_MISMATCH
                )

        if verify_mode == "both":
            vision_included = _channel_includes_registered(
                vision_read,
                expected_username=expected_username,
                expected_english_name=expected_english_name,
            )
            ocr_included = _channel_includes_registered(
                ocr_read,
                expected_username=expected_username,
                expected_english_name=expected_english_name,
            )
            if vision_included:
                log.info("checkin_name: skip ocr fallback (vision inclusion pass)")
                if hunt_prefetch_task is not None and not hunt_prefetch_task.done():
                    hunt_prefetch_task.cancel()
            elif not ocr_included:
                t_fb0 = time.perf_counter()
                hunted: Optional[SlackNameRead] = None
                if hunt_prefetch_task is not None:
                    hunted = await hunt_prefetch_task
                else:
                    hunted = await run_ocr_cpu(
                        ocr_hunt_regions_parallel,
                        regions,
                        expected_username or "",
                    )
                if hunted:
                    ocr_read = hunted
                if not _channel_includes_registered(
                    ocr_read,
                    expected_username=expected_username,
                    expected_english_name=expected_english_name,
                ):
                    other = await run_ocr_cpu(
                        ocr_quick_other_person_parallel,
                        regions,
                        expected_username=expected_username,
                        expected_english_name=expected_english_name,
                    )
                    if other:
                        from services.checkin_user_message import MSG_NAME_MISMATCH

                        return extraction, CheckinAiExtractError(
                            "AI_USER_OTHER_PERSON", MSG_NAME_MISMATCH
                        )
                if not _channel_includes_registered(
                    ocr_read,
                    expected_username=expected_username,
                    expected_english_name=expected_english_name,
                ):
                    thorough = await asyncio.to_thread(
                        ocr_thorough_best_panel,
                        regions,
                        expected_username or "",
                        keys=(_thorough_key,),
                    )
                    if thorough:
                        ocr_read = thorough
                    elif _flat_timeis:
                        wide_read, _ = await run_ocr_cpu(
                            ocr_hunt_username_in_image,
                            name_source_bytes,
                            expected_username or "",
                        )
                        if _channel_includes_registered(
                            wide_read,
                            expected_username=expected_username,
                            expected_english_name=expected_english_name,
                        ):
                            ocr_read = wide_read
                log.info(
                    "checkin_name: ocr fallback %.1fs included=%s",
                    time.perf_counter() - t_fb0,
                    _channel_includes_registered(
                        ocr_read,
                        expected_username=expected_username,
                        expected_english_name=expected_english_name,
                    ),
                )
            if not ocr_avail:
                from services.checkin_user_message import MSG_NAME_MISMATCH

                return extraction, CheckinAiExtractError(
                    "AI_NAME_OCR_UNAVAILABLE", MSG_NAME_MISMATCH
                )
            dual = verify_slack_name_dual(
                vision=vision_read,
                ocr=ocr_read,
                mode="both",
                expected_username=expected_username,
                expected_english_name=expected_english_name,
            )
            if not dual.ok:
                from services.checkin_user_message import user_message_for_checkin_error

                code = dual.error_code or "AI_NAME_DUAL_MISMATCH"
                return extraction, CheckinAiExtractError(
                    code, user_message_for_checkin_error(code)
                )
            extraction = CheckinImageExtraction(
                display_name=dual.display_name,
                username_hint=dual.username_hint,
                clock_time=extraction.clock_time,
                clock_date=extraction.clock_date,
                timezone_iana=extraction.timezone_iana,
                confidence=extraction.confidence,
            )
            log.info(
                "checkin_name: dual ok vision=%s ocr=%s -> %s",
                dual.vision.username_hint if dual.vision else None,
                dual.ocr.username_hint if dual.ocr else None,
                dual.username_hint,
            )
        elif verify_mode == "ocr":
            if not ocr_avail:
                from services.checkin_user_message import MSG_NAME_MISMATCH

                return extraction, CheckinAiExtractError(
                    "AI_NAME_OCR_UNAVAILABLE", MSG_NAME_MISMATCH
                )
            ocr_included = _channel_includes_registered(
                ocr_read,
                expected_username=expected_username,
                expected_english_name=expected_english_name,
            )
            if not ocr_included:
                t_fb0 = time.perf_counter()
                hunted: Optional[SlackNameRead] = None
                if hunt_prefetch_task is not None:
                    hunted = await hunt_prefetch_task
                else:
                    hunted = await run_ocr_cpu(
                        ocr_hunt_regions_parallel,
                        regions,
                        expected_username or "",
                    )
                if hunted:
                    ocr_read = hunted
                if not _channel_includes_registered(
                    ocr_read,
                    expected_username=expected_username,
                    expected_english_name=expected_english_name,
                ):
                    other = await run_ocr_cpu(
                        ocr_quick_other_person_parallel,
                        regions,
                        expected_username=expected_username,
                        expected_english_name=expected_english_name,
                    )
                    if other:
                        from services.checkin_user_message import MSG_NAME_MISMATCH

                        return extraction, CheckinAiExtractError(
                            "AI_USER_OTHER_PERSON", MSG_NAME_MISMATCH
                        )
                if not _channel_includes_registered(
                    ocr_read,
                    expected_username=expected_username,
                    expected_english_name=expected_english_name,
                ):
                    thorough = await run_ocr_cpu(
                        ocr_thorough_best_panel,
                        regions,
                        expected_username or "",
                        keys=(_thorough_key, "name_panel_overlay"),
                    )
                    if thorough:
                        ocr_read = thorough
                    elif _flat_timeis:
                        wide_read, _ = await run_ocr_cpu(
                            ocr_hunt_username_in_image,
                            name_source_bytes,
                            expected_username or "",
                        )
                        if _channel_includes_registered(
                            wide_read,
                            expected_username=expected_username,
                            expected_english_name=expected_english_name,
                        ):
                            ocr_read = wide_read
                log.info(
                    "checkin_name: ocr fallback %.1fs included=%s",
                    time.perf_counter() - t_fb0,
                    _channel_includes_registered(
                        ocr_read,
                        expected_username=expected_username,
                        expected_english_name=expected_english_name,
                    ),
                )
            elif hunt_prefetch_task is not None and not hunt_prefetch_task.done():
                hunt_prefetch_task.cancel()
            dual = verify_slack_name_dual(
                vision=vision_read,
                ocr=ocr_read,
                mode="ocr",
                expected_username=expected_username,
                expected_english_name=expected_english_name,
            )
            if not dual.ok:
                from services.checkin_user_message import user_message_for_checkin_error

                code = dual.error_code or "AI_NAME_NOT_FOUND"
                return extraction, CheckinAiExtractError(
                    code, user_message_for_checkin_error(code)
                )
            extraction = CheckinImageExtraction(
                display_name=dual.display_name,
                username_hint=dual.username_hint,
                clock_time=extraction.clock_time,
                clock_date=extraction.clock_date,
                timezone_iana=extraction.timezone_iana,
                confidence=extraction.confidence,
            )
            log.info("checkin_name: ocr ok -> %s", dual.username_hint)
        elif vision_read.display_name or vision_read.username_hint:
            extraction = CheckinImageExtraction(
                display_name=vision_read.display_name,
                username_hint=vision_read.username_hint,
                clock_time=extraction.clock_time,
                clock_date=extraction.clock_date,
                timezone_iana=extraction.timezone_iana,
                confidence=extraction.confidence,
            )

    if clock_ocr_task is not None:
        try:
            ocr_clock, skew_rejected = await clock_ocr_task
        except Exception:
            log.warning("checkin_ai: parallel ocr clock failed", exc_info=True)
            ocr_clock, skew_rejected = None, False
        if skew_rejected:
            from dataclasses import replace

            extraction = replace(extraction, clock_skew_rejected=True)
        if ocr_clock and not extraction.clock_time:
            from dataclasses import replace

            extraction = replace(
                extraction,
                clock_time=ocr_clock,
                timezone_iana=extraction.timezone_iana or tz_name,
            )
            log.info("checkin_ai: clock from ocr (parallel) value=%s", ocr_clock)

    if date_ocr_task is not None:
        try:
            ocr_date = await date_ocr_task
        except Exception:
            log.warning("checkin_ai: parallel ocr date failed", exc_info=True)
            ocr_date = None
        if ocr_date and not extraction.clock_date:
            extraction = replace(
                extraction,
                clock_date=ocr_date,
                timezone_iana=extraction.timezone_iana or tz_name,
            )
            log.info("checkin_ai: date from ocr (parallel) value=%s", ocr_date)

    return extraction, None


async def _retry_clock_extraction_only(
    *,
    root: str,
    model: str,
    prepared_bytes: bytes,
    config: CheckinAiConfig,
    extraction: CheckinImageExtraction,
    reference_utc: datetime,
    shift_timezone: str,
) -> CheckinImageExtraction:
    """姓名已通过后仅补时间；先快扫主钟区，避免全图慢 OCR（~40s）。"""
    from services.checkin_service import ALLOWED_TIMEZONES

    tz_name = shift_timezone if shift_timezone in ALLOWED_TIMEZONES else "Asia/Shanghai"
    regions = _crop_checkin_regions(prepared_bytes)
    if not extraction.clock_time:
        from dataclasses import replace

        ocr_clock, skew_rejected = ocr_clock_from_regions(
            regions,
            reference_utc=reference_utc,
            tz_name=tz_name,
            prepared_bytes=prepared_bytes,
            max_skew_minutes=config.max_clock_skew_minutes,
            fast=False,
        )
        if skew_rejected:
            extraction = replace(extraction, clock_skew_rejected=True)
        if ocr_clock:
            log.info("checkin_ai: clock from ocr (retry inclusion) value=%s", ocr_clock)
            return replace(
                extraction,
                clock_time=ocr_clock,
                timezone_iana=extraction.timezone_iana or tz_name,
            )
    return extraction


def _extraction_has_signal(extraction: CheckinImageExtraction) -> bool:
    return bool(extraction.display_name or extraction.username_hint or extraction.clock_time)


async def extract_checkin_from_image(
    *,
    image_bytes: bytes,
    config: CheckinAiConfig,
    expected_tg_username: str | None = None,
    expected_english_name: str | None = None,
    reference_utc: datetime | None = None,
    shift_timezone: str = "Asia/Shanghai",
) -> tuple[Optional[CheckinImageExtraction], Optional[CheckinAiExtractError]]:
    if not image_bytes:
        return None, CheckinAiExtractError("AI_EMPTY_IMAGE", "打卡失败，图片为空")

    prepared = _prepare_image_bytes(image_bytes)
    prepared_digest = _image_digest(prepared)
    log.info(
        "checkin_ai: extract start sha256=%s size_kb=%s",
        prepared_digest[:16],
        len(prepared) // 1024,
    )
    image_b64 = base64.standard_b64encode(prepared).decode("ascii")
    model = config.model.strip()
    ocr_only = config.ocr_only
    ocr_text_llm = config.ocr_text_llm
    use_ollama = _is_ollama_base(config.base_url) and not ocr_only and not ocr_text_llm
    root = _ollama_root(config.base_url)

    if ocr_text_llm:
        from services.checkin_ocr_engine import ocr_engine_name

        log.info(
            "checkin_ai: extract_backend=ocr_text_llm (ocr=%s, text_model=%s)",
            ocr_engine_name(),
            config.text_model,
        )
    elif ocr_only:
        from services.checkin_ocr_engine import ocr_engine_name

        log.info(
            "checkin_ai: extract_backend=ocr_only (engine=%s, no Ollama)",
            ocr_engine_name(),
        )

    if use_ollama:
        try:
            available = await _list_ollama_model_names(root=root, timeout=min(config.timeout_seconds, 15.0))
        except Exception:
            log.exception("checkin_ai: cannot reach ollama at %s", root)
            return None, CheckinAiExtractError(
                "AI_SERVICE_DOWN",
                f"打卡失败，无法连接本地 AI（{root}）。\n请确认 Ollama 已启动。",
            )
        if not _model_installed(model, available):
            sample = ", ".join(sorted(available)[:6]) or "（无）"
            return None, CheckinAiExtractError(
                "AI_MODEL_NOT_FOUND",
                (
                    f"打卡失败，AI 模型「{model}」未安装。\n"
                    f"请运行：ollama pull {model}\n"
                    f"当前已安装：{sample}"
                ),
            )

    content: str | None = None
    ref_utc = reference_utc or datetime.now(timezone.utc)
    extraction = CheckinImageExtraction(
        display_name=None,
        username_hint=None,
        clock_time=None,
        clock_date=None,
        timezone_iana=None,
        confidence=None,
    )
    try:
        if ocr_text_llm:
            from services.checkin_ocr_executor import get_ocr_semaphore, ocr_max_concurrent
            from services.checkin_ocr_text_llm_service import extract_checkin_from_ocr_text_llm

            log.info(
                "checkin_ai: ocr slot (max_concurrent=%s)",
                ocr_max_concurrent(),
            )
            async with get_ocr_semaphore():
                extraction, ai_err = await extract_checkin_from_ocr_text_llm(
                    prepared_bytes=prepared,
                    config=config,
                    expected_tg_username=expected_tg_username,
                    expected_english_name=expected_english_name,
                    reference_utc=ref_utc,
                    shift_timezone=shift_timezone,
                )
            if ai_err is not None:
                return extraction, ai_err
        elif use_ollama or ocr_only:
            from services.checkin_ocr_executor import get_ocr_semaphore, ocr_max_concurrent

            log.info(
                "checkin_ai: ocr slot (max_concurrent=%s)",
                ocr_max_concurrent(),
            )
            async with get_ocr_semaphore():
                extraction, name_err = await _supplement_extraction_ollama(
                    root=root,
                    model=model,
                    image_b64=image_b64,
                    prepared_bytes=prepared,
                    config=config,
                    extraction=extraction,
                    expected_username=expected_tg_username,
                    expected_english_name=expected_english_name,
                    reference_utc=ref_utc,
                    shift_timezone=shift_timezone,
                    vision_enabled=not ocr_only,
                )
                if name_err is not None:
                    return extraction, name_err
                if not extraction.clock_time:
                    log.info("checkin_ai: retry clock only (skip name re-verify)")
                    extraction = await _retry_clock_extraction_only(
                        root=root,
                        model=model,
                        prepared_bytes=prepared,
                        config=config,
                        extraction=extraction,
                        reference_utc=ref_utc,
                        shift_timezone=shift_timezone,
                    )
                if not extraction.clock_time and extraction.clock_skew_rejected:
                    from services.checkin_user_message import MSG_SCREENSHOT_TIME_ABNORMAL

                    log.warning(
                        "checkin_ai: screenshot clock skew rejected, no valid time after retry"
                    )
                    return extraction, CheckinAiExtractError(
                        "AI_TIME_SCREENSHOT_SKEW",
                        MSG_SCREENSHOT_TIME_ABNORMAL,
                    )
            if (
                not extraction.clock_time
                and has_valid_identity_fields(extraction)
                and config.clock_fallback_send_time
            ):
                from services.checkin_service import ALLOWED_TIMEZONES

                tz_name = (
                    shift_timezone
                    if shift_timezone in ALLOWED_TIMEZONES
                    else "Asia/Shanghai"
                )
                local = ref_utc.astimezone(ZoneInfo(tz_name))
                srv_clock = local.strftime("%H:%M:%S")
                extraction = CheckinImageExtraction(
                    display_name=extraction.display_name,
                    username_hint=extraction.username_hint,
                    clock_time=srv_clock,
                    clock_date=local.strftime("%Y-%m-%d"),
                    timezone_iana=tz_name,
                    confidence=extraction.confidence,
                )
                log.warning(
                    "checkin_ai: clock fallback to send-time %s (identity verified, clock unreadable)",
                    srv_clock,
                )
        else:
            content = await _call_openai_vision(
                base_url=config.base_url,
                model=model,
                image_b64=image_b64,
                config=config,
            )
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else 0
        log.exception("checkin_ai: http %s model=%s", status, model)
        if status == 404:
            return None, CheckinAiExtractError(
                "AI_MODEL_NOT_FOUND",
                f"打卡失败，AI 模型「{model}」不可用。请执行：ollama pull {model}",
            )
        return None, CheckinAiExtractError(
            "AI_HTTP_ERROR",
            f"打卡失败，AI 服务返回错误（HTTP {status}）。请检查 Ollama 与模型配置。",
        )
    except httpx.TimeoutException:
        log.exception("checkin_ai: timeout model=%s limit=%ss", model, config.timeout_seconds)
        return None, CheckinAiExtractError(
            "AI_TIMEOUT",
            (
                f"打卡失败，AI 识别超时（已等待 {int(config.timeout_seconds)} 秒）。\n"
                "请确认 Ollama 已启动且未卡住；首次识别较慢，可在 .env 调大 CHECKIN_AI_TIMEOUT_SECONDS。"
            ),
        )
    except httpx.ConnectError:
        log.exception("checkin_ai: connect failed model=%s root=%s", model, root)
        return None, CheckinAiExtractError(
            "AI_SERVICE_DOWN",
            "打卡失败，无法连接 Ollama。请打开 Ollama 应用或运行 ollama serve。",
        )
    except httpx.RequestError:
        log.exception("checkin_ai: request failed model=%s", model)
        return None, CheckinAiExtractError(
            "AI_SERVICE_DOWN",
            "打卡失败，访问本地 AI 时网络异常。请确认 Ollama 正在运行后重试。",
        )
    except Exception:
        log.exception("checkin_ai: vision request failed model=%s", model)
        return None, CheckinAiExtractError(
            "AI_EXTRACT_FAILED",
            "打卡失败，AI 识别异常。请换一张更清晰的截图重试。",
        )

    if not use_ollama and content and content.strip():
        extraction = _parse_model_content(content, expected_username=expected_tg_username)
        combined_fb = _fallback_extraction_from_text(
            content,
            expected_username=expected_tg_username,
            reference_utc=ref_utc,
            tz_name=shift_timezone,
        )
        extraction = _merge_extractions(extraction, _enrich_identity_from_display(combined_fb))

    if not _extraction_has_signal(extraction):
        return None, CheckinAiExtractError(
            "AI_PARSE_FAILED",
            (
                "打卡失败：无法从截图识别用户姓名与打卡时间。\n"
                "请按以下方式重试：\n"
                "1. 打开 time.is，截含大号时钟 + 右下角 Slack 浮窗的图\n"
                "2. 在 Telegram 点「附件 → 相册」选这张图发送（不要截屏整个对话）"
            ),
        )
    return extraction, None
