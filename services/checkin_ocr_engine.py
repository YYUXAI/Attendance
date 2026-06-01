"""打卡 OCR 后端：tesseract（默认）或 easyocr。"""

from __future__ import annotations

import logging
import os

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import re
import threading
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from PIL import Image

log = logging.getLogger(__name__)

_engine_name: str | None = None
_easyocr_reader = None
_easyocr_lock = threading.Lock()


def ocr_engine_name() -> str:
    global _engine_name
    if _engine_name is None:
        raw = (os.getenv("CHECKIN_AI_OCR_ENGINE") or "tesseract").strip().lower()
        if raw not in {"tesseract", "easyocr"}:
            raw = "tesseract"
        _engine_name = raw
    return _engine_name


def configure_tesseract_cmd(pytesseract: object) -> None:
    cmd = (os.getenv("CHECKIN_AI_TESSERACT_CMD") or "").strip()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd  # type: ignore[attr-defined]


def ocr_backend_available() -> bool:
    if ocr_engine_name() == "easyocr":
        try:
            import easyocr  # noqa: F401
            return True
        except ImportError:
            return False
    try:
        import pytesseract

        configure_tesseract_cmd(pytesseract)
        return True
    except ImportError:
        return False


def is_ocr_runtime_missing(exc: BaseException) -> bool:
    if ocr_engine_name() == "easyocr":
        return isinstance(exc, ImportError)
    if isinstance(exc, FileNotFoundError):
        return True
    name = type(exc).__name__
    if name in {"TesseractNotFoundError", "TesseractNotFound"}:
        return True
    msg = str(exc).lower()
    return "tesseract" in msg and ("not installed" in msg or "not in your path" in msg)


def _pil_to_numpy(img: "Image.Image"):
    import numpy as np

    return np.array(img.convert("RGB"))


def _get_easyocr_reader():
    global _easyocr_reader
    with _easyocr_lock:
        if _easyocr_reader is None:
            import easyocr

            gpu = os.getenv("CHECKIN_AI_EASYOCR_GPU", "false").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
            log.info("checkin_ocr: initializing EasyOCR reader (gpu=%s)", gpu)
            _easyocr_reader = easyocr.Reader(["en", "ch_sim"], gpu=gpu, verbose=False)
        return _easyocr_reader


def _easyocr_read_text(img: "Image.Image", *, min_confidence: float = 0.25) -> str:
    reader = _get_easyocr_reader()
    try:
        results = reader.readtext(_pil_to_numpy(img))
    except Exception:
        log.warning("checkin_ocr: easyocr readtext failed", exc_info=True)
        return ""
    parts: list[str] = []
    for _bbox, text, conf in results:
        if conf >= min_confidence and text and text.strip():
            parts.append(text.strip())
    return "\n".join(parts)


def _easyocr_high_confidence_words(img: "Image.Image", *, min_confidence: float = 0.5) -> str:
    reader = _get_easyocr_reader()
    try:
        results = reader.readtext(_pil_to_numpy(img))
    except Exception:
        return ""
    words: list[str] = []
    for _bbox, text, conf in results:
        if conf < min_confidence:
            continue
        for w in re.split(r"\s+", text.strip()):
            if w and re.search(r"[A-Za-z]", w):
                words.append(w)
    return " ".join(words)


def _apply_whitelist(text: str, whitelist: str | None) -> str:
    if not whitelist or not text:
        return text
    allowed = set(whitelist)
    return "".join(c for c in text if c in allowed)


def _tesseract_image_to_string(
    img: "Image.Image",
    *,
    lang: str = "eng",
    config: str = "",
) -> str:
    import pytesseract

    configure_tesseract_cmd(pytesseract)
    return pytesseract.image_to_string(img, lang=lang, config=config) or ""


def _tesseract_high_confidence_words(img: "Image.Image") -> str:
    try:
        import pytesseract
        from pytesseract import Output

        configure_tesseract_cmd(pytesseract)
        data = pytesseract.image_to_data(img, lang="eng", config="--oem 3", output_type=Output.DICT)
    except Exception:
        return ""
    parts: list[str] = []
    texts = data.get("text") or []
    confs = data.get("conf") or []
    for w, c in zip(texts, confs):
        try:
            conf = float(c)
        except (TypeError, ValueError):
            continue
        if conf < 50:
            continue
        w = (w or "").strip()
        if not w or not re.search(r"[A-Za-z]", w):
            continue
        parts.append(w)
    return " ".join(parts)


def ocr_image_to_string(
    img: "Image.Image",
    *,
    lang: str = "eng",
    config: str = "",
    fast: bool = True,
    whitelist: str | None = None,
) -> str:
    if ocr_engine_name() == "easyocr":
        min_conf = 0.35 if fast else 0.25
        text = _easyocr_read_text(img, min_confidence=min_conf)
        if whitelist:
            lines = [_apply_whitelist(line, whitelist) for line in text.splitlines()]
            text = "\n".join(line for line in lines if line.strip())
            if not text.strip():
                text = _apply_whitelist(_easyocr_read_text(img, min_confidence=min_conf), whitelist)
        return text
    return _tesseract_image_to_string(img, lang=lang, config=config)


def ocr_full_image_text(image_bytes: bytes) -> str:
    """整图 OCR 一次（ocr_text_llm 用），不做多区域裁剪。"""
    try:
        import io

        from PIL import Image, ImageEnhance, ImageOps
    except ImportError:
        return ""
    if not ocr_backend_available():
        return ""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception:
        return ""
    w, h = img.size
    if max(w, h) > 1600:
        scale = 1600 / float(max(w, h))
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    gray = ImageEnhance.Contrast(ImageOps.autocontrast(img.convert("L"))).enhance(2.0)
    text = ocr_image_to_string(gray, fast=False)
    if text.strip():
        return text.strip()
    return ocr_image_to_string(img, fast=False).strip()


def ocr_high_confidence_words(img: "Image.Image") -> str:
    if ocr_engine_name() == "easyocr":
        return _easyocr_high_confidence_words(img)
    return _tesseract_high_confidence_words(img)
