from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import BufferedInputFile

from domain.shared.result import ServiceResult
from repositories import clock_records_repo, employee_shift_config_repo, profile_repo
from repositories.registrations_repo import get_by_tg_id
from repositories.shifts_repo import list_all_shifts
from services import checkin_ai_orchestrator, checkin_service
from services.group_attendance_summary_service import _as_time

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


def _resolve_attendance_group_id(*, reg) -> int | None:
    if reg.registered_chat_id is not None:
        return int(reg.registered_chat_id)
    chat_id = clock_records_repo.get_latest_chat_id_for_employee(employee_id=str(reg.employee_id))
    if chat_id is not None:
        return chat_id
    for shift in list_all_shifts():
        if shift.attendance_group_id is not None:
            return int(shift.attendance_group_id)
    return None


def build_context(*, tg_id: int, action: str) -> ServiceResult | CheckinWebContext:
    reg = get_by_tg_id(int(tg_id))
    if not reg:
        return ServiceResult(ok=False, message="请先完成注册", error_code="NOT_REGISTERED")

    group_id = _resolve_attendance_group_id(reg=reg)
    if group_id is None:
        return ServiceResult(ok=False, message="考勤群未配置", error_code="NOT_CONFIGURED")

    tz_name = "Asia/Shanghai"
    ym = datetime.now(ZoneInfo(tz_name)).strftime("%Y-%m")
    employee_shift_config_repo.ensure_table()
    cfg = profile_repo.get_employee_shift_config_for_month(
        employee_id=str(reg.employee_id),
        year_month=ym,
    )
    if cfg:
        rng = (cfg.shift_time_range or "").strip()
        cin_t = _as_time(cfg.shift_checkin_time)
        cout_t = _as_time(cfg.shift_checkout_time)
        cin_s = cin_t.strftime("%H:%M")
        cout_s = cout_t.strftime("%H:%M")
        shift_time_range = rng if rng else f"{cin_s}~{cout_s}"
    else:
        return ServiceResult(
            ok=False,
            message="当月班表未配置，请管理员在班表 Web 中维护您的工号",
            error_code="NOT_CONFIGURED",
        )

    return CheckinWebContext(
        english_name=(reg.english_name or "").strip() or "未命名",
        employee_id=str(reg.employee_id),
        action=action,
        shift_time_range=shift_time_range,
        shift_checkin=cin_s,
        shift_checkout=cout_s,
        group_id=group_id,
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
