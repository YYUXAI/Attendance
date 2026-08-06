from __future__ import annotations

import hashlib
from typing import Any


def redacted_ref(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    return f"sha256:{digest}"


def text_summary(value: Any) -> str:
    text = "" if value is None else str(value)
    return f"len={len(text)}"


def presence(value: Any) -> str:
    return "present" if value not in (None, "") else "absent"
