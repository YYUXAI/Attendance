"""打卡失败时对用户展示的简短文案（姓名 / 时间 / 日期）。"""
from __future__ import annotations

MSG_NAME_MISMATCH = "打卡失败：姓名不一致。"
MSG_TIME_MISMATCH = "打卡失败：时间不一致。"
MSG_DATE_MISMATCH = "打卡失败：日期不一致。"
MSG_NAME_AND_TIME_MISMATCH = "打卡失败：姓名不一致，时间不一致。"
MSG_SCREENSHOT_TIME_ABNORMAL = "打卡失败：截图时间异常，请重新截图。"

_NAME_ERROR_CODES = frozenset(
    {
        "AI_NAME_NOT_FOUND",
        "AI_NAME_NOT_FOUND",
        "AI_NAME_DUAL_MISMATCH",
        "AI_NAME_OCR_UNAVAILABLE",
        "AI_USER_MISMATCH",
        "AI_USER_HALLUCINATION",
        "AI_USER_NOT_FOUND",
        "AI_USER_OTHER_PERSON",
        "AI_IMAGE_CROPPED",
        "AI_EXTRACT_FAILED",
        "AI_EMPTY_IMAGE",
    }
)

_TIME_ERROR_CODES = frozenset(
    {
        "AI_TIME_NOT_FOUND",
        "AI_TIME_INVALID_FORMAT",
        "AI_TIME_MISMATCH",
        "AI_TIME_SCREENSHOT_SKEW",
    }
)

_DATE_ERROR_CODES = frozenset(
    {
        "AI_DATE_NOT_FOUND",
        "AI_DATE_MISMATCH",
    }
)

_BOTH_ERROR_CODES = frozenset(
    {
        "AI_BOTH_MISSING",
        "AI_COMPOSITE_SCREENSHOT",
    }
)


def is_name_related_checkin_error(error_code: str | None) -> bool:
    code = (error_code or "").strip().upper()
    if code in _BOTH_ERROR_CODES:
        return True
    return (
        code in _NAME_ERROR_CODES
        or code.startswith("AI_NAME")
        or code.startswith("AI_USER")
    )


def user_message_for_checkin_error(error_code: str | None) -> str:
    code = (error_code or "").strip().upper()
    if code in _BOTH_ERROR_CODES:
        return MSG_NAME_AND_TIME_MISMATCH
    if code in _DATE_ERROR_CODES or code.startswith("AI_DATE"):
        return MSG_DATE_MISMATCH
    if code == "AI_TIME_SCREENSHOT_SKEW":
        return MSG_SCREENSHOT_TIME_ABNORMAL
    if code in _TIME_ERROR_CODES or code in ("AI_TIMEOUT",):
        return MSG_TIME_MISMATCH
    if is_name_related_checkin_error(code):
        return MSG_NAME_MISMATCH
    return MSG_NAME_MISMATCH
