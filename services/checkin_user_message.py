"""打卡失败时对用户展示的简短文案（姓名 / 时间 / 日期）。"""
from __future__ import annotations

MSG_NAME_MISMATCH = "打卡失败：姓名不一致。"
MSG_CAPTION_NOT_SELF = "打卡失败：配文不是本人，请使用自己的签到/签退模板。"
MSG_TIME_MISMATCH = "打卡失败：时间不一致。"
MSG_DATE_MISMATCH = "打卡失败：日期不一致。"
MSG_NAME_AND_TIME_MISMATCH = "打卡失败：姓名不一致，时间不一致。"
MSG_AI_SERVICE_DOWN = "打卡失败：识别服务不可用，请稍后重试。"
MSG_AI_BALANCE_EXHAUSTED = "打卡失败：智谱账户余额不足，请充值后重试。"
MSG_AI_AUTH_FAILED = "打卡失败：智谱 API Key 无效或已过期，请联系管理员。"
# 与 MSG_TIME_MISMATCH 相同；保留别名供旧引用
MSG_SCREENSHOT_TIME_ABNORMAL = MSG_TIME_MISMATCH

_NAME_ERROR_CODES = frozenset(
    {
        "CAPTION_IDENTITY_MISMATCH",
        "AI_NAME_NOT_FOUND",
        "AI_NAME_DUAL_MISMATCH",
        "AI_NAME_OCR_UNAVAILABLE",
        "AI_USER_MISMATCH",
        "AI_USER_HALLUCINATION",
        "AI_NOT_GROUNDED",
        "AI_USER_NOT_FOUND",
        "AI_USER_OTHER_PERSON",
        "AI_IMAGE_CROPPED",
        "AI_EMPTY_IMAGE",
    }
)

_EXTRACT_FAILED_CODES = frozenset({"AI_EXTRACT_FAILED"})

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

_SERVICE_ERROR_CODES = frozenset(
    {
        "AI_SERVICE_DOWN",
        "AI_TIMEOUT",
        "AI_DOWNLOAD_FAILED",
        "AI_HTTP_ERROR",
        "AI_RATE_LIMIT",
        "AI_CONFIG_MISSING",
    }
)

_BALANCE_ERROR_CODES = frozenset({"AI_BALANCE_EXHAUSTED"})
_AUTH_ERROR_CODES = frozenset({"AI_AUTH_FAILED"})


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
    if code in _BALANCE_ERROR_CODES:
        return MSG_AI_BALANCE_EXHAUSTED
    if code in _AUTH_ERROR_CODES:
        return MSG_AI_AUTH_FAILED
    if code in _EXTRACT_FAILED_CODES:
        return MSG_AI_SERVICE_DOWN
    if code in _SERVICE_ERROR_CODES:
        return MSG_AI_SERVICE_DOWN
    if code in _BOTH_ERROR_CODES:
        return MSG_NAME_AND_TIME_MISMATCH
    if code in _DATE_ERROR_CODES or code.startswith("AI_DATE"):
        return MSG_DATE_MISMATCH
    if code in _TIME_ERROR_CODES or code in ("AI_TIMEOUT",):
        return MSG_TIME_MISMATCH
    if code == "CAPTION_IDENTITY_MISMATCH":
        return MSG_CAPTION_NOT_SELF
    if is_name_related_checkin_error(code):
        return MSG_NAME_MISMATCH
    return MSG_NAME_MISMATCH
