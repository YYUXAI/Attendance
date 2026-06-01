from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from aiogram import Bot
from aiogram.types import BufferedInputFile

from domain.shared.result import ServiceResult
from repositories.registrations_repo import get_by_tg_id
from repositories.shifts_repo import get_by_id as get_shift_by_id
from services import checkin_ai_orchestrator, checkin_service

log = logging.getLogger(__name__)

_MAX_BYTES = 12 * 1024 * 1024


@dataclass(frozen=True)
class CheckinWebContext:
    english_name: str
    employee_id: str
    action: str
    shift_time_range: str
    shift_checkin: str
    shift_checkout: str
    group_id: int


@dataclass(frozen=True)
class CheckinWebSubmitResult:
    ok: bool
    message: str


def build_context(*, tg_id: int, action: str) -> ServiceResult | CheckinWebContext:
    reg = get_by_tg_id(int(tg_id))
    if not reg:
        return ServiceResult(ok=False, message="请先完成注册", error_code="NOT_REGISTERED")
    if reg.shift_id is None:
        return ServiceResult(ok=False, message="尚未分配班次，请联系管理员", error_code="NOT_CONFIGURED")
    shift = get_shift_by_id(int(reg.shift_id))
    if not shift or shift.attendance_group_id is None:
        return ServiceResult(ok=False, message="考勤群未配置", error_code="NOT_CONFIGURED")

    cin = shift.checkin_time
    cout = shift.checkout_time
    cin_s = cin.strftime("%H:%M") if hasattr(cin, "strftime") else str(cin)
    cout_s = cout.strftime("%H:%M") if hasattr(cout, "strftime") else str(cout)

    return CheckinWebContext(
        english_name=(reg.english_name or "").strip() or "未命名",
        employee_id=str(reg.employee_id),
        action=action,
        shift_time_range=f"{cin_s}~{cout_s}",
        shift_checkin=cin_s,
        shift_checkout=cout_s,
        group_id=int(shift.attendance_group_id),
    )


async def submit_checkin_from_web(
    *,
    bot: Bot,
    tg_id: int,
    action: str,
    image_bytes: bytes,
    filename: str = "checkin.jpg",
) -> CheckinWebSubmitResult:
    if action not in {"签到", "签退"}:
        return CheckinWebSubmitResult(ok=False, message="无效事项")
    if not image_bytes:
        return CheckinWebSubmitResult(ok=False, message="请先粘贴或选择打卡截图")
    if len(image_bytes) > _MAX_BYTES:
        return CheckinWebSubmitResult(ok=False, message="图片过大，请压缩后重试")

    ctx_or_err = build_context(tg_id=tg_id, action=action)
    if isinstance(ctx_or_err, ServiceResult):
        return CheckinWebSubmitResult(ok=False, message=ctx_or_err.message)

    ctx = ctx_or_err
    prepared = checkin_service.validate_and_prepare(
        tg_id=int(tg_id),
        chat_id=int(ctx.group_id),
        file_id="web-upload",
    )
    if not isinstance(prepared, tuple):
        return CheckinWebSubmitResult(ok=False, message=prepared.message)

    employee_id, shift_id, english_name, _dept, _cin, _cout, _tz = prepared
    now_utc = datetime.now(timezone.utc)
    caption = f"#打卡\n英文名：{english_name}\n工号：{employee_id}\n事项：{action}"

    ai_out = await checkin_ai_orchestrator.resolve_clock_time_with_ai_from_bytes(
        image_bytes=image_bytes,
        tg_id=int(tg_id),
        shift_timezone="Asia/Shanghai",
        message_sent_utc=now_utc,
        caption=caption,
    )
    if not isinstance(ai_out, checkin_ai_orchestrator.CheckinAiResolveResult):
        msg = ai_out.message if isinstance(ai_out, ServiceResult) else "打卡识别失败"
        try:
            await bot.send_message(chat_id=int(tg_id), text=msg)
        except Exception:
            log.exception("checkin_web: notify user failed tg_id=%s", tg_id)
        return CheckinWebSubmitResult(ok=False, message=msg)

    try:
        sent = await bot.send_photo(
            chat_id=int(ctx.group_id),
            photo=BufferedInputFile(image_bytes, filename=filename or "checkin.jpg"),
            caption=caption,
        )
    except Exception as e:
        log.exception("checkin_web: send_photo failed tg_id=%s group=%s", tg_id, ctx.group_id)
        return CheckinWebSubmitResult(ok=False, message=f"发送到考勤群失败：{e}")

    file_id = None
    if sent.photo:
        file_id = sent.photo[-1].file_id
    elif sent.document:
        file_id = sent.document.file_id
    if not file_id:
        return CheckinWebSubmitResult(ok=False, message="发送成功但无法获取文件ID")

    checkin_service.persist_clock_record(
        tg_id=int(tg_id),
        chat_id=int(ctx.group_id),
        file_id=file_id,
        employee_id=employee_id,
        shift_id=shift_id,
        clock_time_utc=ai_out.clock_time_utc,
        clock_action=action,
    )
    log.info(
        "checkin_web: success tg_id=%s action=%s group=%s clock=%s",
        tg_id,
        action,
        ctx.group_id,
        ai_out.clock_time_utc,
    )
    return CheckinWebSubmitResult(ok=True, message="打卡成功，已发送到考勤群")
