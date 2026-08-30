import os, asyncio
from datetime import datetime, timezone
from pathlib import Path

for name in list(os.environ):
    if name.endswith('_FILE'):
        try: os.environ[name[:-5]]=Path(os.environ[name]).read_text().strip()
        except Exception: pass
for dst,src in {'DB_HOST':'ATTENDANCE_DATABASE_HOST','DB_PORT':'ATTENDANCE_DATABASE_PORT','DB_NAME':'ATTENDANCE_DATABASE_NAME','DB_USER':'ATTENDANCE_DATABASE_USER','DB_PASSWORD':'ATTENDANCE_DATABASE_PASSWORD'}.items():
    if src in os.environ and dst not in os.environ: os.environ[dst]=os.environ[src]

async def main():
    from infra.checkin_ai_config import load_checkin_ai_config, resolve_checkin_ai_config_for_chat
    from services.checkin_ai_orchestrator import resolve_clock_time_with_ai_from_bytes
    from domain.shared.result import ServiceResult
    from infra.checkin_ocrspace_config import ocrspace_api_key_count

    img = Path('/tmp/subtoyok_checkin_crop.png').read_bytes()
    chat_id = -1004373351741
    chat_title = 'QDYYZ 打卡报备群'
    tg_id = 6398009481
    ref = datetime(2026, 8, 29, 13, 19, 26, tzinfo=timezone.utc)
    caption = '@yyux_helper_bot #打卡\n英文名: Subtoyok\n工号: 70620\n事项: 签退'

    cfg = resolve_checkin_ai_config_for_chat(load_checkin_ai_config(), chat_id=chat_id, chat_title=chat_title)
    print('backend', cfg.extract_backend, 'ocrspace_keys', ocrspace_api_key_count(), flush=True)

    result = await resolve_clock_time_with_ai_from_bytes(
        image_bytes=img,
        tg_id=tg_id,
        shift_timezone='Asia/Shanghai',
        message_sent_utc=ref,
        caption=caption,
        chat_id=chat_id,
        chat_title=chat_title,
    )
    if isinstance(result, ServiceResult):
        print('RESULT FAIL', result.error_code, result.message, flush=True)
        return
    ext = result.extraction
    print('RESULT OK', flush=True)
    print('clock_time', ext.clock_time if ext else None, flush=True)
    print('clock_date', ext.clock_date if ext else None, flush=True)
    print('clock_time_utc', result.clock_time_utc, flush=True)
    if ext and ext.clock_time:
        from services.checkin_image_ai_service import _minutes_from_reference
        skew = _minutes_from_reference(clock_str=ext.clock_time, reference_utc=ref, tz_name='Asia/Shanghai')
        print('skew_min', round(skew, 2) if skew is not None else None, flush=True)
        print('PASS' if skew is not None and skew <= 30 else 'SKEW_FAIL', flush=True)

asyncio.run(main())
