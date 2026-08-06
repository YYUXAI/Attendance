# -*- coding: utf-8 -*-
"""批量重放指定日期的打卡截图，统计当前识别成功率。"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")


async def _download_telegram(file_id: str) -> bytes | None:
    import httpx

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN 未配置")
    async with httpx.AsyncClient(timeout=90) as client:
        try:
            r = await client.get(
                f"https://api.telegram.org/bot{token}/getFile",
                params={"file_id": file_id},
            )
            r.raise_for_status()
            path = r.json()["result"]["file_path"]
            r2 = await client.get(f"https://api.telegram.org/file/bot{token}/{path}")
            r2.raise_for_status()
            return r2.content
        except Exception:
            return None


def _load_rows(work_date: str) -> list[dict]:
    import psycopg2
    from psycopg2.extras import RealDictCursor

    conn = psycopg2.connect(
        host=os.getenv("DB_HOST", "127.0.0.1"),
        port=int(os.getenv("DB_PORT", "5433")),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    )
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                """
                SELECT cr.id, cr.chat_id, cr.tg_id, cr.employee_id, cr.file_id,
                       cr.clock_time, cr.clock_action,
                       r.tg_username, r.english_name
                FROM clock_records cr
                LEFT JOIN registrations r ON r.tg_id = cr.tg_id
                WHERE (cr.clock_time AT TIME ZONE %s)::date = %s
                ORDER BY cr.id
                """,
                ("Asia/Shanghai", work_date),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


async def _replay_one(row: dict, *, shift_timezone: str) -> dict:
    from infra.checkin_ai_config import load_checkin_ai_config
    from repositories.registrations_repo import get_by_tg_id
    from services.checkin_ai_orchestrator import resolve_clock_time_with_ai_from_bytes

    cfg = load_checkin_ai_config()
    reg = get_by_tg_id(int(row["tg_id"]))
    if not reg:
        return {
            "id": row["id"],
            "employee_id": row["employee_id"],
            "tg_id": row["tg_id"],
            "ok": False,
            "error_code": "NOT_REGISTERED",
            "message": "未注册",
        }

    image_bytes = await _download_telegram(str(row["file_id"]))
    if not image_bytes:
        return {
            "id": row["id"],
            "employee_id": row["employee_id"],
            "tg_id": row["tg_id"],
            "ok": False,
            "error_code": "DOWNLOAD_FAILED",
            "message": "图片下载失败",
        }

    clock_time = row["clock_time"]
    if isinstance(clock_time, datetime) and clock_time.tzinfo is None:
        ref_utc = clock_time.replace(tzinfo=timezone.utc)
    else:
        ref_utc = clock_time

    result = await resolve_clock_time_with_ai_from_bytes(
        image_bytes=image_bytes,
        tg_id=int(row["tg_id"]),
        shift_timezone=shift_timezone,
        config=cfg,
        message_sent_utc=ref_utc,
        chat_id=int(row["chat_id"]) if row.get("chat_id") is not None else None,
    )

    if hasattr(result, "ok"):
        return {
            "id": row["id"],
            "employee_id": row["employee_id"],
            "tg_id": row["tg_id"],
            "english_name": row.get("english_name"),
            "clock_action": row.get("clock_action"),
            "ok": bool(result.ok),
            "error_code": getattr(result, "error_code", None),
            "message": getattr(result, "message", None),
        }

    return {
        "id": row["id"],
        "employee_id": row["employee_id"],
        "tg_id": row["tg_id"],
        "english_name": row.get("english_name"),
        "clock_action": row.get("clock_action"),
        "ok": True,
        "error_code": None,
        "message": "success",
        "clock_time_utc": result.clock_time_utc.isoformat() if result.clock_time_utc else None,
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat(), help="Asia/Shanghai 工作日 YYYY-MM-DD")
    parser.add_argument("--timezone", default="Asia/Shanghai")
    parser.add_argument("--out", type=Path, default=ROOT / "scripts" / "batch_replay_today_result.json")
    args = parser.parse_args()

    rows = _load_rows(args.date)
    if not rows:
        print(f"no records for {args.date}")
        return 1

    print(f"replaying {len(rows)} checkins for {args.date} ...")
    results: list[dict] = []
    for idx, row in enumerate(rows, start=1):
        print(f"[{idx}/{len(rows)}] employee_id={row['employee_id']} tg_id={row['tg_id']}")
        item = await _replay_one(row, shift_timezone=args.timezone)
        results.append(item)
        status = "OK" if item.get("ok") else f"FAIL {item.get('error_code')}"
        print(f"  -> {status}")
        await asyncio.sleep(0.5)

    ok_count = sum(1 for r in results if r.get("ok"))
    fail_count = len(results) - ok_count
    summary = {
        "date": args.date,
        "total": len(results),
        "success": ok_count,
        "failed": fail_count,
        "success_rate": round(ok_count / len(results) * 100, 1) if results else 0.0,
        "results": results,
    }
    args.out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print("---")
    print(f"total={summary['total']} success={summary['success']} failed={summary['failed']}")
    print(f"success_rate={summary['success_rate']}%")
    print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
