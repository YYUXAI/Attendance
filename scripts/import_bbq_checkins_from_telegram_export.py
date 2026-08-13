"""从 Telegram Desktop 导出的 JSON 补录 BBQ 群历史打卡。

不要求出现 @机器人名；只要命中「工号 + 事项(签到/签退)」即可导入。
按消息发送时间写入 clock_records；目标群必须通过 --chat-id 显式指定。
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from dotenv import load_dotenv

load_dotenv(override=True, encoding="utf-8")

from infra.db import get_cursor
from repositories.clock_records_repo import insert_clock_record

TZ_SHANGHAI = ZoneInfo("Asia/Shanghai")
_EMPLOYEE_RE = re.compile(r"工号\s*[：:]\s*(\d+)")
_ACTION_RE = re.compile(r"事项\s*[：:]\s*(签到|签退)")


@dataclass(frozen=True)
class RegistrationMeta:
    employee_id: str
    tg_id: int
    shift_id: int | None


@dataclass(frozen=True)
class ParsedCheckin:
    msg_id: str
    employee_id: str
    action: str
    sent_at: datetime
    text: str


def _flatten_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for x in value:
            if isinstance(x, str):
                parts.append(x)
            elif isinstance(x, dict):
                parts.append(str(x.get("text") or ""))
            else:
                parts.append(str(x))
        return "".join(parts)
    if isinstance(value, dict):
        return str(value.get("text") or "")
    return str(value)


def _parse_iso_datetime(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_SHANGHAI)
    return dt


def _parse_export_datetime(raw: str) -> datetime | None:
    text = (raw or "").strip()
    if not text:
        return None
    dt = _parse_iso_datetime(text)
    if dt is not None:
        return dt
    for fmt in (
        "%d.%m.%Y %H:%M:%S UTC%z",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ_SHANGHAI)
            return dt
        except ValueError:
            continue
    return None


def _extract_checkin(msg: dict[str, Any]) -> ParsedCheckin | None:
    content = "\n".join(
        x for x in (_flatten_text(msg.get("text")), _flatten_text(msg.get("caption"))) if x.strip()
    )
    # 兼容无 @机器人名、无 #打卡 的导出文本，只要有工号+事项就算有效打卡模板。
    if "工号" not in content:
        return None
    m = _EMPLOYEE_RE.search(content)
    if m is None:
        return None
    employee_id = m.group(1).strip()
    action_m = _ACTION_RE.search(content)
    if action_m is None:
        return None
    action = action_m.group(1)
    sent_at = _parse_export_datetime(str(msg.get("date") or ""))
    if sent_at is None:
        return None
    msg_id = str(msg.get("id") or "").strip() or f"noid_{employee_id}_{int(sent_at.timestamp())}"
    return ParsedCheckin(
        msg_id=msg_id,
        employee_id=employee_id,
        action=action,
        sent_at=sent_at,
        text=content,
    )


def _load_registrations() -> dict[str, RegistrationMeta]:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT employee_id, tg_id, shift_id
            FROM public.registrations
            WHERE employee_id IS NOT NULL
            """
        )
        rows = cur.fetchall() or []
    out: dict[str, RegistrationMeta] = {}
    for employee_id, tg_id, shift_id in rows:
        eid = str(employee_id).strip()
        if not eid:
            continue
        out[eid] = RegistrationMeta(
            employee_id=eid,
            tg_id=int(tg_id) if tg_id is not None else 0,
            shift_id=int(shift_id) if shift_id is not None else None,
        )
    return out


def _exists_record(*, chat_id: int, employee_id: str, clock_time_utc: datetime, action: str) -> bool:
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM public.clock_records
            WHERE chat_id = %s
              AND employee_id = %s
              AND clock_time = %s
              AND COALESCE(clock_action, '') = %s
            LIMIT 1
            """,
            (int(chat_id), str(employee_id), clock_time_utc, str(action)),
        )
        return cur.fetchone() is not None


def _iter_messages(payload: dict[str, Any]) -> list[dict[str, Any]]:
    msgs = payload.get("messages")
    if isinstance(msgs, list):
        return [m for m in msgs if isinstance(m, dict)]
    return []


def _strip_html_text(raw: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", raw, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)
    return text.strip()


def _iter_messages_from_html(content: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    marker = re.compile(r'<div class="message default clearfix" id="message(?P<id>\d+)">')
    points = list(marker.finditer(content))
    for i, m in enumerate(points):
        start = m.start()
        end = points[i + 1].start() if i + 1 < len(points) else len(content)
        block = content[start:end]
        date_m = re.search(r'class="pull_right date details" title="([^"]+)"', block)
        text_m = re.search(r'<div class="text">\s*(.*?)\s*</div>', block, flags=re.S)
        if date_m is None or text_m is None:
            continue
        out.append(
            {
                "id": m.group("id"),
                "date": date_m.group(1).strip(),
                "text": _strip_html_text(text_m.group(1)),
            }
        )
    return out


def _load_messages_from_export(export_file: Path) -> list[dict[str, Any]]:
    suffix = export_file.suffix.lower()
    if suffix == ".json":
        payload = json.loads(export_file.read_text(encoding="utf-8"))
        return _iter_messages(payload)
    if suffix in {".html", ".htm"}:
        content = export_file.read_text(encoding="utf-8", errors="ignore")
        return _iter_messages_from_html(content)
    raise ValueError(f"不支持的导出文件类型: {export_file.name}")


def run_import(
    *,
    export_file: Path,
    chat_id: int,
    start_date: datetime | None,
    end_date: datetime | None,
    dry_run: bool,
) -> None:
    messages = _load_messages_from_export(export_file)
    regs = _load_registrations()

    parsed = 0
    skipped_unregistered = 0
    skipped_dup = 0
    inserted = 0

    for msg in messages:
        c = _extract_checkin(msg)
        if c is None:
            continue
        parsed += 1
        sent_local = c.sent_at.astimezone(TZ_SHANGHAI)
        if start_date and sent_local < start_date:
            continue
        if end_date and sent_local >= end_date:
            continue
        reg = regs.get(c.employee_id)
        if reg is None:
            skipped_unregistered += 1
            continue
        clock_time_utc = c.sent_at.astimezone(ZoneInfo("UTC"))
        if _exists_record(
            chat_id=chat_id,
            employee_id=c.employee_id,
            clock_time_utc=clock_time_utc,
            action=c.action,
        ):
            skipped_dup += 1
            continue
        if not dry_run:
            insert_clock_record(
                chat_id=chat_id,
                file_id=f"tg_export_msg_{c.msg_id}",
                tg_id=reg.tg_id,
                employee_id=c.employee_id,
                shift_id=reg.shift_id,
                clock_time_utc=clock_time_utc,
                clock_action=c.action,
            )
        inserted += 1

    print(f"source_messages={len(messages)}")
    print(f"parsed_checkin_messages={parsed}")
    print(f"inserted={inserted}")
    print(f"skipped_duplicate={skipped_dup}")
    print(f"skipped_unregistered={skipped_unregistered}")
    print(f"dry_run={dry_run}")


def _parse_day(raw: str | None, *, end_exclusive: bool) -> datetime | None:
    if not raw:
        return None
    d = datetime.strptime(raw, "%Y-%m-%d")
    if end_exclusive:
        return d.replace(tzinfo=TZ_SHANGHAI)
    return d.replace(tzinfo=TZ_SHANGHAI)


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 Telegram 导出文件(JSON/HTML)为 BBQ 历史打卡")
    parser.add_argument("--export-file", help="Telegram 导出文件路径（result.json 或 messages.html）")
    parser.add_argument("--export-json", help="兼容旧参数，等价于 --export-file")
    parser.add_argument("--chat-id", type=int, required=True, help="目标群 chat_id")
    parser.add_argument("--start-date", help="开始日期(含)，格式 YYYY-MM-DD（按北京时间）")
    parser.add_argument("--end-date", help="结束日期(不含)，格式 YYYY-MM-DD（按北京时间）")
    parser.add_argument("--apply", action="store_true", help="真实写入数据库（默认 dry-run）")
    args = parser.parse_args()

    raw_path = args.export_file or args.export_json
    if not raw_path:
        raise ValueError("请提供 --export-file（或旧参数 --export-json）")
    if int(args.chat_id) == 0:
        raise ValueError("请提供 --chat-id")
    export_file = Path(raw_path).expanduser().resolve()
    if not export_file.exists():
        raise FileNotFoundError(f"找不到导出文件: {export_file}")

    start_date = _parse_day(args.start_date, end_exclusive=False)
    end_date = _parse_day(args.end_date, end_exclusive=True)
    run_import(
        export_file=export_file,
        chat_id=int(args.chat_id),
        start_date=start_date,
        end_date=end_date,
        dry_run=not args.apply,
    )


if __name__ == "__main__":
    main()
