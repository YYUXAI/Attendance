"""对两张典型测试图跑完整 extract + validate（benrenxing 账号）。"""
from __future__ import annotations

import asyncio
import io
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

from domain.shared.result import ServiceResult  # noqa: E402
from infra.checkin_ai_config import load_checkin_ai_config  # noqa: E402
from repositories.registrations_repo import get_by_tg_id  # noqa: E402
from services import checkin_extraction_validate_service  # noqa: E402
from services.checkin_image_ai_service import (  # noqa: E402
    _crop_checkin_regions,
    _prepare_image_bytes,
    extract_checkin_from_image,
    is_slack_panel_likely_cropped_off,
    pick_single_identity,
)

BENREN_TG_ID = 1302377984
ASSETS = Path(r"C:\Users\test\.cursor\projects\d\assets")

TESTS = [
    (
        "图A_群聊_考勤群错误提示",
        ASSETS
        / "c__Users_test_AppData_Roaming_Cursor_User_workspaceStorage_22ebd0a5343d9ee451e3cbfc25a6e09d_images_image-9f52e412-a183-4098-8bf1-2b7aa8cc5ad4.png",
    ),
    (
        "图B_群聊_benrenxing发Nayxua打卡图",
        ASSETS
        / "c__Users_test_AppData_Roaming_Cursor_User_workspaceStorage_22ebd0a5343d9ee451e3cbfc25a6e09d_images_image-36d0f56b-9c93-498a-9396-b0bedcb4b2d3.png",
    ),
    (
        "图C_TIME.IS相册_benrenxing",
        ASSETS
        / "c__Users_test_AppData_Roaming_Cursor_User_workspaceStorage_22ebd0a5343d9ee451e3cbfc25a6e09d_images_image-5feeb0e5-37bd-416b-ba40-76b5a6a87dd7.png",
    ),
    (
        "图D_TIME.IS相册_Nayxua",
        ASSETS
        / "c__Users_test_AppData_Roaming_Cursor_User_workspaceStorage_22ebd0a5343d9ee451e3cbfc25a6e09d_images_photo_2026-05-15_18-39-38-00b4c304-7131-459a-9f09-9bd42998bedd.png",
    ),
]


async def run_one(label: str, path: Path, expected_user: str) -> None:
    print(f"\n{'='*60}")
    print(f"【{label}】")
    print(f"文件: {path.name}")
    if not path.is_file():
        print("  SKIP 文件不存在")
        return
    raw = path.read_bytes()
    prep = _prepare_image_bytes(raw)
    img = Image.open(io.BytesIO(prep))
    w, h = img.size
    print(f"  尺寸: {w}x{h}  bytes={len(raw)}  cropped_off={is_slack_panel_likely_cropped_off(prep)}")
    regions = _crop_checkin_regions(prep)
    for k in sorted(regions):
        if k.startswith("name_"):
            im = Image.open(io.BytesIO(regions[k]))
            print(f"  裁切 {k}: {im.size[0]}x{im.size[1]}")

    cfg = load_checkin_ai_config()
    ext, err = await extract_checkin_from_image(
        image_bytes=raw,
        config=cfg,
        expected_tg_username=expected_user,
        shift_timezone="Asia/Bangkok",
    )
    if err:
        print(f"  提取: FAIL [{err.error_code}]")
        print(f"        {err.message[:200]}")
        return
    identity = pick_single_identity(ext) if ext else None
    print(f"  提取: OK  clock={ext.clock_time!r}  identity={identity!r}")
    print(f"        display={ext.display_name!r} hint={ext.username_hint!r}")

    reg = get_by_tg_id(BENREN_TG_ID)
    if not reg or not ext:
        return
    val = checkin_extraction_validate_service.validate_extraction_for_checkin(
        extraction=ext,
        reg=reg,
        shift_timezone="Asia/Bangkok",
        now_utc=datetime.now(timezone.utc),
        max_skew_minutes=cfg.max_clock_skew_minutes,
        trust_sender_when_name_unreadable=cfg.trust_sender_when_name_unreadable,
        composite_screenshot=False,
    )
    if isinstance(val, ServiceResult):
        print(f"  校验: FAIL [{val.error_code}] {val.message.split(chr(10))[0]}")
    else:
        print(f"  校验: PASS  clock_utc={val.isoformat()}")


async def main() -> int:
    cfg = load_checkin_ai_config()
    print("配置:", f"enabled={cfg.enabled}", f"model={cfg.model}", f"name_verify={cfg.name_verify_mode}")
    print(f"trust_sender={cfg.trust_sender_when_name_unreadable}")
    reg = get_by_tg_id(BENREN_TG_ID)
    print("账号:", reg.tg_username if reg else "无")
    for label, path in TESTS:
        await run_one(label, path, reg.tg_username if reg else "benrenxing")
    print(f"\n{'='*60}\n完成")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
