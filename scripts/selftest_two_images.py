"""自测两张对比图 + 两张相册 TIME.IS（OCR 快测 + 完整 extract）。"""
from __future__ import annotations

import asyncio
import io
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

from PIL import Image

from domain.shared.result import ServiceResult
from infra.checkin_ai_config import load_checkin_ai_config
from repositories.registrations_repo import get_by_tg_id
from services import checkin_extraction_validate_service
from services.checkin_image_ai_service import (
    _crop_checkin_regions,
    _isolate_timeis_canvas,
    _prepare_image_bytes,
    extract_checkin_from_image,
    pick_single_identity,
)
from services.checkin_name_verify_service import ocr_slack_name_from_panel

ASSETS = Path(r"C:\Users\test\.cursor\projects\d\assets")
BENREN_TG_ID = 1302377984

CASES = [
    ("图A_群聊_考勤群错误", "9f52e412"),
    ("图B_群聊_benrenxing发Nayxua", "36d0f56b"),
    ("图C_相册_benrenxing", "5feeb0e5"),
    ("图D_相册_Nayxua", "photo_2026-05-15"),
]


def find_asset(key: str) -> Path | None:
    if not ASSETS.is_dir():
        return None
    for p in ASSETS.iterdir():
        if p.suffix.lower() == ".png" and key in p.name:
            return p
    return None


def merge_name_regions(prep: bytes) -> dict[str, bytes]:
    iso = _isolate_timeis_canvas(prep)
    time_bytes = iso if iso is not prep else prep
    regions = _crop_checkin_regions(time_bytes)
    name_src = prep
    if iso is not prep:
        _, ih = Image.open(io.BytesIO(iso)).size
        if ih < 380:
            for k, v in _crop_checkin_regions(prep).items():
                if k.startswith("name_"):
                    regions[k] = v
    return regions


def run_ocr(label: str, path: Path) -> dict:
    prep = _prepare_image_bytes(path.read_bytes())
    w, h = Image.open(io.BytesIO(prep)).size
    regions = merge_name_regions(prep)
    keys = ("name_panel_bottom", "name_panel_row", "name_panel", "name_panel_tight")
    crops = [regions[k] for k in keys if k in regions]
    t0 = time.perf_counter()
    read, ok = ocr_slack_name_from_panel(
        crops[0] if crops else prep,
        extra_panels=crops[1:3],
        expected_username="benrenxing",
    )
    sec = time.perf_counter() - t0
    sizes = {k: Image.open(io.BytesIO(regions[k])).size for k in keys if k in regions}
    return {
        "label": label,
        "size": f"{w}x{h}",
        "crops": sizes,
        "ocr_sec": round(sec, 1),
        "ocr_ok": ok,
        "hint": read.username_hint,
        "display": read.display_name,
    }


async def run_full(label: str, path: Path, cfg, reg) -> dict:
    t0 = time.perf_counter()
    ext, err = await extract_checkin_from_image(
        image_bytes=path.read_bytes(),
        config=cfg,
        expected_tg_username="benrenxing",
        shift_timezone="Asia/Bangkok",
    )
    sec = round(time.perf_counter() - t0, 1)
    if err:
        return {"label": label, "extract": "FAIL", "code": err.error_code, "msg": err.message.split("\n")[0], "sec": sec}
    identity = pick_single_identity(ext)
    val = checkin_extraction_validate_service.validate_extraction_for_checkin(
        extraction=ext,
        reg=reg,
        shift_timezone="Asia/Bangkok",
        now_utc=datetime.now(timezone.utc),
        max_skew_minutes=cfg.max_clock_skew_minutes,
        trust_sender_when_name_unreadable=cfg.trust_sender_when_name_unreadable,
    )
    if isinstance(val, ServiceResult):
        return {
            "label": label,
            "extract": "OK",
            "identity": identity,
            "clock": ext.clock_time,
            "validate": "FAIL",
            "code": val.error_code,
            "msg": val.message.split("\n")[0],
            "sec": sec,
        }
    return {
        "label": label,
        "extract": "OK",
        "identity": identity,
        "clock": ext.clock_time,
        "validate": "PASS",
        "sec": sec,
    }


async def main() -> None:
    cfg = load_checkin_ai_config()
    reg = get_by_tg_id(BENREN_TG_ID)
    out = ROOT / "scripts" / "selftest_two_images_result.txt"
    lines: list[str] = []
    lines.append(f"config: name_verify={cfg.name_verify_mode} trust_sender={cfg.trust_sender_when_name_unreadable}")
    lines.append(f"account: {reg.tg_username if reg else 'N/A'}")
    lines.append("")
    lines.append("=== OCR 快测 ===")
    for label, key in CASES:
        p = find_asset(key)
        if not p:
            lines.append(f"{label}: 文件缺失 ({key})")
            continue
        r = run_ocr(label, p)
        lines.append(
            f"{r['label']}: {r['size']} crops={r['crops']} "
            f"ocr={r['ocr_sec']}s ok={r['ocr_ok']} hint={r['hint']!r} display={r['display']!r}"
        )
    lines.append("")
    lines.append("=== 完整 AI extract + validate ===")
    if not reg:
        lines.append("SKIP: 无 benrenxing 注册")
    else:
        for label, key in CASES:
            p = find_asset(key)
            if not p:
                continue
            lines.append(f"--- {label} 开始 ---")
            out.write_text("\n".join(lines), encoding="utf-8")
            r = await run_full(label, p, cfg, reg)
            if r.get("extract") == "FAIL":
                lines.append(f"{r['label']}: extract FAIL [{r['code']}] {r['msg']} ({r['sec']}s)")
            else:
                lines.append(
                    f"{r['label']}: extract OK identity={r['identity']!r} clock={r['clock']!r} "
                    f"validate={r['validate']} [{r.get('code','')}] {r.get('msg','')} ({r['sec']}s)"
                )
    lines.append("")
    lines.append("完成")
    out.write_text("\n".join(lines), encoding="utf-8")
    print(out.read_text(encoding="utf-8"))


if __name__ == "__main__":
    asyncio.run(main())
