from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CheckinImageExtraction:
    display_name: Optional[str]
    username_hint: Optional[str]
    clock_time: Optional[str]
    clock_date: Optional[str]
    timezone_iana: Optional[str]
    confidence: Optional[float]
    clock_skew_rejected: bool = False
    # OCR.space 调试原文（默认空，正式展示可不使用）
    ocr_debug_text: Optional[str] = None
