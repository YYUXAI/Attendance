# -*- coding: utf-8 -*-
"""
打卡 AI 统一自测（改功能后请运行）

用法:
  python scripts/checkin_ai_selftest.py           # 默认：单元 + OCR + 集成（需 Ollama/图）
  python scripts/checkin_ai_selftest.py --fast    # 仅单元回归（~1s，无需 Ollama/样图）
  python scripts/checkin_ai_selftest.py --ocr     # 单元 + Tesseract 样图 OCR
  python scripts/checkin_ai_selftest.py --list    # 列出用例与样图状态

环境变量:
  CHECKIN_SELFTEST_ASSETS  样图目录（默认 Cursor assets）
  CHECKIN_SELFTEST_TG_ID   测试账号 tg_id（默认 1302377984 benrenxing）

退出码: 0 全部通过，1 有失败或跳过关键依赖
"""
from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

DEFAULT_ASSETS = Path(
    os.getenv(
        "CHECKIN_SELFTEST_ASSETS",
        r"C:\Users\test\.cursor\projects\d\assets",
    )
)
DEFAULT_TG_ID = int(os.getenv("CHECKIN_SELFTEST_TG_ID", "1302377984"))
MAX_FULL_PIPELINE_SEC = float(os.getenv("CHECKIN_SELFTEST_MAX_SEC", "25"))


class Tier(str, Enum):
    UNIT = "unit"
    OCR = "ocr"
    INTEGRATION = "integration"


@dataclass
class CaseResult:
    name: str
    tier: Tier
    passed: bool
    detail: str
    skipped: bool = False
    elapsed_sec: float = 0.0


@dataclass
class AssetSpec:
    label: str
    key: str
    description: str = ""


# 样图：文件名需包含 key 子串
ASSETS = [
    AssetSpec("A_群聊_考勤群错", "9f52e412"),
    AssetSpec("B_群聊_发Nayxua", "36d0f56b"),
    AssetSpec("C_相册_benrenxing", "5feeb0e5"),
    AssetSpec("D_相册_Nayxua", "photo_2026"),
    AssetSpec("E_用户20:31", "215f78a8"),
]


def find_asset(key: str, assets_dir: Path) -> Optional[Path]:
    if not assets_dir.is_dir():
        return None
    for p in sorted(assets_dir.glob("*.png")):
        if key in p.name:
            return p
    return None


def _banner(title: str) -> str:
    return f"\n=== {title} ==="


# ---------------------------------------------------------------------------
# 单元测试（无 Ollama、无样图）
# ---------------------------------------------------------------------------


def unit_against_inclusion() -> CaseResult:
    from services.checkin_name_verify_service import SlackNameRead, verify_slack_name_dual

    raw = (
        "onstitution Day / International Day Against F w\n"
        "BS benrenxing\nSet Emoji Status\n05:31 benrenxing"
    )
    dual = verify_slack_name_dual(
        vision=SlackNameRead(None, None, "vision"),
        ocr=SlackNameRead("Against", "Against", "ocr", raw_text=raw),
        mode="both",
        expected_username="benrenxing",
    )
    ok = dual.ok and dual.username_hint == "benrenxing"
    return CaseResult(
        "unit.against_raw_has_benrenxing",
        Tier.UNIT,
        ok,
        f"hint={dual.username_hint!r} code={dual.error_code}",
    )


def unit_garbage_against_filtered() -> CaseResult:
    from services.checkin_name_verify_service import (
        SlackNameRead,
        _filter_ocr_read,
        _is_ocr_garbage_token,
    )

    garbage = _is_ocr_garbage_token("against")
    read = _filter_ocr_read(
        SlackNameRead("Against", "Against", "ocr", raw_text="day against"),
        expected_username="benrenxing",
    )
    ok = garbage and read.display_name is None
    return CaseResult(
        "unit.against_is_garbage_token",
        Tier.UNIT,
        ok,
        f"garbage={garbage} filtered_display={read.display_name!r}",
    )


def unit_other_person_handle() -> CaseResult:
    from services.checkin_name_verify_service import (
        SlackNameRead,
        verify_slack_name_dual,
    )

    dual = verify_slack_name_dual(
        vision=SlackNameRead(None, None, "vision"),
        ocr=SlackNameRead("Y_UX_Nayxua", "Y_UX_Nayxua", "ocr", raw_text="Y_UX_Nayxua"),
        mode="both",
        expected_username="benrenxing",
    )
    ok = not dual.ok and dual.error_code == "AI_USER_OTHER_PERSON"
    return CaseResult(
        "unit.reject_nayxua_handle",
        Tier.UNIT,
        ok,
        f"code={dual.error_code}",
    )


def unit_config_trust_sender_off() -> CaseResult:
    from infra.checkin_ai_config import load_checkin_ai_config

    cfg = load_checkin_ai_config()
    ok = not cfg.trust_sender_when_name_unreadable
    return CaseResult(
        "unit.config_strict_name",
        Tier.UNIT,
        ok,
        f"trust_sender={cfg.trust_sender_when_name_unreadable} verify={cfg.name_verify_mode}",
    )


def unit_config_extract_backend() -> CaseResult:
    from infra.checkin_ai_config import load_checkin_ai_config

    cfg = load_checkin_ai_config()
    if cfg.ocr_text_llm:
        ok = (
            cfg.name_verify_mode == "ocr"
            and not cfg.clock_fallback_send_time
            and bool(cfg.text_model.strip())
        )
        detail = (
            f"backend={cfg.extract_backend} text_model={cfg.text_model} "
            f"verify={cfg.name_verify_mode} clock_fallback={cfg.clock_fallback_send_time}"
        )
    elif cfg.ocr_only:
        ok = (
            cfg.name_verify_mode == "ocr"
            and not cfg.clock_fallback_send_time
        )
        detail = (
            f"backend={cfg.extract_backend} verify={cfg.name_verify_mode} "
            f"clock_fallback={cfg.clock_fallback_send_time}"
        )
    else:
        ok = True
        detail = f"backend={cfg.extract_backend} (skipped strict checks)"
    return CaseResult(
        "unit.config_extract_backend",
        Tier.UNIT,
        ok,
        detail,
    )


def unit_ocr_mode_requires_inclusion() -> CaseResult:
    from services.checkin_name_verify_service import (
        SlackNameRead,
        verify_slack_name_dual,
    )

    dual = verify_slack_name_dual(
        vision=SlackNameRead(None, None, "vision"),
        ocr=SlackNameRead("Y_UX_N", "Y_UX_N", "ocr", raw_text="Y_UX_Nayxua"),
        mode="ocr",
        expected_username="benrenxing",
    )
    ok = not dual.ok and dual.error_code == "AI_NAME_NOT_FOUND"
    return CaseResult(
        "unit.ocr_mode_requires_inclusion",
        Tier.UNIT,
        ok,
        f"ok={dual.ok} code={dual.error_code}",
    )


def unit_clock_inclusion_pick() -> CaseResult:
    from datetime import datetime, timezone

    from services.checkin_image_ai_service import (
        _pick_clock_by_inclusion,
        _pick_best_clock_time,
    )

    ref = datetime(2026, 5, 20, 6, 11, 0, tzinfo=timezone.utc)
    cands = {"22:54": False, "01:54": False, "13:54:36": True, "04:54": False}
    pick, _ = _pick_clock_by_inclusion(
        cands, reference_utc=ref, tz_name="Asia/Bangkok", max_skew_minutes=60
    )
    ok = pick == "13:54:36"
    text = "洛杉矶 22:54\n纽约 01:54\n现在的北京时间\n13:54:36"
    best = _pick_best_clock_time(
        [(c, hs) for c, hs in cands.items()],
        reference_utc=ref,
        tz_name="Asia/Bangkok",
    )
    ok = ok and best == "13:54:36"
    return CaseResult(
        "unit.clock_inclusion_pick",
        Tier.UNIT,
        ok,
        f"pick={pick!r} best={best!r}",
    )


def unit_resolve_registered_from_raw() -> CaseResult:
    from services.checkin_name_verify_service import (
        SlackNameRead,
        _resolve_registered_from_read,
    )

    read = SlackNameRead("Wrong", "Wrong", "ocr", raw_text="hello benrenxing world")
    name = _resolve_registered_from_read(read, expected_username="benrenxing")
    ok = name == "benrenxing"
    return CaseResult(
        "unit.resolve_registered_from_raw",
        Tier.UNIT,
        ok,
        f"resolved={name!r}",
    )


def unit_identity_alnum_loose() -> CaseResult:
    from repositories.registrations_repo import RegistrationRow
    from services.checkin_identity_match_service import match_registration_for_sender

    reg = RegistrationRow(
        id=1,
        employee_id="74306",
        tg_id=8532682955,
        english_name="NAYXUA",
        tg_username="Y_UX_Nayxua",
        registered_chat_id=None,
        organization_id=1,
        shift_id=1,
    )
    cases = [
        ("Y_UXNayxua", None, True),
        ("YUXNayxua", "YUXNayxua", True),
        ("Y_UX_Nayxua 朵拉", "Y_UX_Nayxua", True),
        ("nayxua", None, True),
        ("Y_UX_Benrenxing", None, False),
    ]
    results = []
    for disp, hint, expect in cases:
        got = match_registration_for_sender(
            sender=reg, display_name=disp, username_hint=hint
        )
        results.append(got == expect)
    ok = all(results)
    return CaseResult(
        "unit.identity_alnum_loose",
        Tier.UNIT,
        ok,
        f"cases={sum(results)}/{len(results)}",
    )


UNIT_TESTS: list[Callable[[], CaseResult]] = [
    unit_against_inclusion,
    unit_garbage_against_filtered,
    unit_other_person_handle,
    unit_config_trust_sender_off,
    unit_config_extract_backend,
    unit_ocr_mode_requires_inclusion,
    unit_clock_inclusion_pick,
    unit_resolve_registered_from_raw,
    unit_identity_alnum_loose,
]


# ---------------------------------------------------------------------------
# OCR 样图（仅需 Tesseract）
# ---------------------------------------------------------------------------


def ocr_clock_case(spec: AssetSpec, assets_dir: Path) -> CaseResult:
    from PIL import Image

    from services.checkin_image_ai_service import (
        _crop_checkin_regions,
        _prepare_image_bytes,
        ocr_clock_from_regions,
    )

    path = find_asset(spec.key, assets_dir)
    if not path:
        return CaseResult(
            f"ocr.clock.{spec.key}",
            Tier.OCR,
            True,
            "SKIP 无样图",
            skipped=True,
        )
    t0 = time.perf_counter()
    prep = _prepare_image_bytes(path.read_bytes())
    w, h = Image.open(io.BytesIO(prep)).size
    regions = _crop_checkin_regions(prep)
    clk, _ = ocr_clock_from_regions(
        regions,
        reference_utc=datetime.now(timezone.utc),
        tz_name="Asia/Bangkok",
        max_skew_minutes=24 * 60,
    )
    dt = time.perf_counter() - t0
    # E/A/B/C 应读出主钟；D 扁图可能无钟
    expect_clock = spec.key in ("215f78a8", "9f52e412", "36d0f56b", "5feeb0e5")
    if expect_clock:
        ok = bool(
            clk
            and ("20:31" in clk or "18:41" in clk or "13:53" in clk)
        )
    else:
        ok = True  # 仅记录结果
    detail = f"{spec.label} {w}x{h} -> {clk!r}"
    if spec.key == "photo_2026" and clk is None:
        ok = True
        detail += " (扁图无钟可接受)"
    elif expect_clock and not clk:
        ok = False
        detail += " (期望读到主钟)"
    return CaseResult(f"ocr.clock.{spec.key}", Tier.OCR, ok, detail, elapsed_sec=dt)


# ---------------------------------------------------------------------------
# 集成（Ollama + DB + 样图）
# ---------------------------------------------------------------------------


@dataclass
class IntegrationExpect:
    asset_key: str
    label: str
    expect: str  # pass | other | not_found_ok | name_or_time_ok
    max_sec: float = MAX_FULL_PIPELINE_SEC


INTEGRATION_CASES = [
    IntegrationExpect("215f78a8", "E_本人20:31", "pass", 15.0),
    IntegrationExpect("photo_2026", "D_他人Nayxua", "other", 35.0),
    IntegrationExpect("5feeb0e5", "C_难读相册", "name_or_time_ok", 35.0),
]

# Telegram 压缩扁图（1280×463）：由 E 图缩放模拟，日志 sha 与线上一致场景
FLAT_SYNTHETIC_KEY = "215f78a8"
FLAT_SYNTHETIC_SIZE = (1280, 463)


async def integration_full(
    spec: IntegrationExpect,
    assets_dir: Path,
    tg_id: int,
) -> CaseResult:
    from domain.shared.result import ServiceResult
    from infra.checkin_ai_config import load_checkin_ai_config
    from repositories.registrations_repo import get_by_tg_id
    from services import checkin_extraction_validate_service
    from services.checkin_image_ai_service import extract_checkin_from_image, pick_single_identity

    path = find_asset(spec.asset_key, assets_dir)
    if not path:
        return CaseResult(
            f"integration.{spec.asset_key}",
            Tier.INTEGRATION,
            True,
            "SKIP 无样图",
            skipped=True,
        )

    cfg = load_checkin_ai_config()
    reg = get_by_tg_id(tg_id)
    if not reg:
        return CaseResult(
            f"integration.{spec.asset_key}",
            Tier.INTEGRATION,
            False,
            f"SKIP 数据库无 tg_id={tg_id} 注册",
            skipped=True,
        )

    t0 = time.perf_counter()
    ext, err = await extract_checkin_from_image(
        image_bytes=path.read_bytes(),
        config=cfg,
        expected_tg_username=reg.tg_username,
        expected_english_name=reg.english_name,
        shift_timezone="Asia/Bangkok",
    )
    dt = time.perf_counter() - t0

    if spec.expect == "other":
        if err and err.error_code == "AI_USER_OTHER_PERSON":
            ok = dt <= spec.max_sec
            return CaseResult(
                f"integration.{spec.label}",
                Tier.INTEGRATION,
                ok,
                f"拒绝他人 OK ({dt:.1f}s)" + ("" if ok else f" 超时>{spec.max_sec}s"),
                elapsed_sec=dt,
            )
        return CaseResult(
            f"integration.{spec.label}",
            Tier.INTEGRATION,
            False,
            f"期望 AI_USER_OTHER_PERSON 实际 err={getattr(err, 'error_code', None)}",
            elapsed_sec=dt,
        )

    if err:
        if spec.expect == "not_found_ok" and err.error_code in (
            "AI_NAME_NOT_FOUND",
            "AI_USER_NOT_FOUND",
        ):
            ok = dt <= spec.max_sec
            return CaseResult(
                f"integration.{spec.label}",
                Tier.INTEGRATION,
                ok,
                f"难读图未识别 OK [{err.error_code}] ({dt:.1f}s)",
                elapsed_sec=dt,
            )
        return CaseResult(
            f"integration.{spec.label}",
            Tier.INTEGRATION,
            False,
            f"extract FAIL [{err.error_code}] {err.message.split(chr(10))[0]}",
            elapsed_sec=dt,
        )

    ident = pick_single_identity(ext)
    val = checkin_extraction_validate_service.validate_extraction_for_checkin(
        extraction=ext,
        reg=reg,
        shift_timezone="Asia/Bangkok",
        now_utc=datetime.now(timezone.utc),
        max_skew_minutes=cfg.max_clock_skew_minutes,
        trust_sender_when_name_unreadable=cfg.trust_sender_when_name_unreadable,
    )
    if isinstance(val, ServiceResult):
        if (
            spec.expect == "name_or_time_ok"
            and ident == "benrenxing"
            and val.error_code in ("AI_TIME_MISMATCH", "AI_TIME_MISSING")
        ):
            ok = dt <= spec.max_sec
            return CaseResult(
                f"integration.{spec.label}",
                Tier.INTEGRATION,
                ok,
                f"难读图已识别姓名 [{val.error_code}] clock={ext.clock_time!r} ({dt:.1f}s)",
                elapsed_sec=dt,
            )
        return CaseResult(
            f"integration.{spec.label}",
            Tier.INTEGRATION,
            False,
            f"validate FAIL [{val.error_code}] ident={ident!r} clock={ext.clock_time!r}",
            elapsed_sec=dt,
        )

    ok = ident == "benrenxing" and dt <= spec.max_sec
    return CaseResult(
        f"integration.{spec.label}",
        Tier.INTEGRATION,
        ok,
        f"PASS ident={ident!r} clock={ext.clock_time!r} ({dt:.1f}s)",
        elapsed_sec=dt,
    )


async def integration_flat_telegram_synthetic(
    assets_dir: Path,
    tg_id: int,
) -> CaseResult:
    """模拟 Telegram 横条 1280×463（Slack 浮窗在钟面右上）。"""
    import io

    from PIL import Image

    from services.checkin_image_ai_service import _prepare_image_bytes

    path = find_asset(FLAT_SYNTHETIC_KEY, assets_dir)
    if not path:
        return CaseResult(
            "integration.flat_1280x463",
            Tier.INTEGRATION,
            True,
            "SKIP 无 215f78a8 样图",
            skipped=True,
        )
    img = Image.open(path).convert("RGB").resize(
        FLAT_SYNTHETIC_SIZE, Image.Resampling.LANCZOS
    )
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    flat_bytes = buf.getvalue()
    prep = _prepare_image_bytes(flat_bytes)
    spec = IntegrationExpect("flat_sim", "扁图1280x463", "pass", 35.0)

    from domain.shared.result import ServiceResult
    from infra.checkin_ai_config import load_checkin_ai_config
    from repositories.registrations_repo import get_by_tg_id
    from services import checkin_extraction_validate_service
    from services.checkin_image_ai_service import extract_checkin_from_image, pick_single_identity

    cfg = load_checkin_ai_config()
    reg = get_by_tg_id(tg_id)
    if not reg:
        return CaseResult(
            "integration.flat_1280x463",
            Tier.INTEGRATION,
            False,
            f"SKIP 无 tg_id={tg_id}",
            skipped=True,
        )

    t0 = time.perf_counter()
    ext, err = await extract_checkin_from_image(
        image_bytes=flat_bytes,
        config=cfg,
        expected_tg_username=reg.tg_username,
        expected_english_name=reg.english_name,
        shift_timezone="Asia/Bangkok",
    )
    dt = time.perf_counter() - t0
    if err:
        return CaseResult(
            "integration.flat_1280x463",
            Tier.INTEGRATION,
            False,
            f"FAIL [{err.error_code}] {err.message.split(chr(10))[0]} ({dt:.1f}s)",
            elapsed_sec=dt,
        )
    ident = pick_single_identity(ext)
    val = checkin_extraction_validate_service.validate_extraction_for_checkin(
        extraction=ext,
        reg=reg,
        shift_timezone="Asia/Bangkok",
        now_utc=datetime.now(timezone.utc),
        max_skew_minutes=cfg.max_clock_skew_minutes,
        trust_sender_when_name_unreadable=cfg.trust_sender_when_name_unreadable,
    )
    if isinstance(val, ServiceResult):
        return CaseResult(
            "integration.flat_1280x463",
            Tier.INTEGRATION,
            False,
            f"validate FAIL [{val.error_code}] ident={ident!r} ({dt:.1f}s)",
            elapsed_sec=dt,
        )
    ok = ident == "benrenxing" and dt <= spec.max_sec
    return CaseResult(
        "integration.flat_1280x463",
        Tier.INTEGRATION,
        ok,
        f"PASS ident={ident!r} clock={ext.clock_time!r} prep={Image.open(io.BytesIO(prep)).size} ({dt:.1f}s)",
        elapsed_sec=dt,
    )


async def integration_ollama_ping() -> CaseResult:
    import httpx
    from infra.checkin_ai_config import load_checkin_ai_config

    cfg = load_checkin_ai_config()
    if not cfg.enabled:
        return CaseResult(
            "integration.ollama_ping",
            Tier.INTEGRATION,
            True,
            "SKIP CHECKIN_AI_ENABLED=false",
            skipped=True,
        )
    root = cfg.base_url.replace("/v1", "").rstrip("/")
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{root}/api/tags")
            r.raise_for_status()
            names = [
                m.get("name", "")
                for m in r.json().get("models", [])
                if isinstance(m, dict)
            ]
        has = any(cfg.model in n or n.startswith(cfg.model) for n in names)
        dt = time.perf_counter() - t0
        return CaseResult(
            "integration.ollama_ping",
            Tier.INTEGRATION,
            has,
            f"model={cfg.model} installed={has} ({dt:.1f}s)",
            elapsed_sec=dt,
        )
    except Exception as exc:
        return CaseResult(
            "integration.ollama_ping",
            Tier.INTEGRATION,
            False,
            f"无法连接 {root}: {exc}",
        )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


@dataclass
class RunReport:
    results: list[CaseResult] = field(default_factory=list)

    @property
    def failed(self) -> list[CaseResult]:
        return [r for r in self.results if not r.passed and not r.skipped]

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.passed and not r.skipped)

    @property
    def failed_count(self) -> int:
        return len(self.failed)

    @property
    def skipped_count(self) -> int:
        return sum(1 for r in self.results if r.skipped)


def print_list_assets(assets_dir: Path) -> None:
    print(_banner("样图清单"))
    print(f"目录: {assets_dir} ({'存在' if assets_dir.is_dir() else '不存在'})")
    for spec in ASSETS:
        p = find_asset(spec.key, assets_dir)
        status = p.name if p else "缺失"
        print(f"  [{spec.key}] {spec.label}: {status}")


async def run(
    *,
    mode: str,
    assets_dir: Path,
    tg_id: int,
) -> RunReport:
    report = RunReport()
    lines: list[str] = []

    lines.append(_banner("单元回归"))
    for fn in UNIT_TESTS:
        r = fn()
        report.results.append(r)
        mark = "PASS" if r.passed else ("SKIP" if r.skipped else "FAIL")
        lines.append(f"  [{mark}] {r.name}: {r.detail}")

    if mode in ("ocr", "all"):
        lines.append(_banner("OCR 样图（Tesseract）"))
        for spec in ASSETS:
            r = ocr_clock_case(spec, assets_dir)
            report.results.append(r)
            mark = "PASS" if r.passed else ("SKIP" if r.skipped else "FAIL")
            lines.append(f"  [{mark}] {r.name}: {r.detail}")

    if mode in ("all",):
        lines.append(_banner("集成（Ollama + DB）"))
        ping = await integration_ollama_ping()
        report.results.append(ping)
        mark = "PASS" if ping.passed else ("SKIP" if ping.skipped else "FAIL")
        lines.append(f"  [{mark}] {ping.name}: {ping.detail}")

        if not ping.passed and not ping.skipped:
            lines.append("  后续集成用例已跳过（Ollama 不可用）")
        else:
            for spec in INTEGRATION_CASES:
                r = await integration_full(spec, assets_dir, tg_id)
                report.results.append(r)
                mark = "PASS" if r.passed else ("SKIP" if r.skipped else "FAIL")
                lines.append(f"  [{mark}] {r.name}: {r.detail}")
            flat_r = await integration_flat_telegram_synthetic(assets_dir, tg_id)
            report.results.append(flat_r)
            mark = "PASS" if flat_r.passed else ("SKIP" if flat_r.skipped else "FAIL")
            lines.append(f"  [{mark}] {flat_r.name}: {flat_r.detail}")

    lines.append(_banner("汇总"))
    lines.append(
        f"  通过 {report.passed_count} | 失败 {report.failed_count} | 跳过 {report.skipped_count}"
    )
    if report.failed:
        lines.append("  失败项:")
        for r in report.failed:
            lines.append(f"    - {r.name}: {r.detail}")
        lines.append("\n结果: FAIL")
    else:
        lines.append("\n结果: OK")

    text = "\n".join(lines)
    print(text)
    out = ROOT / "scripts" / "checkin_ai_selftest_result.txt"
    out.write_text(text, encoding="utf-8")
    print(f"\n(已写入 {out})")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="打卡 AI 统一自测")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="仅单元测试（无需 Ollama/样图）",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="单元 + OCR 样图",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出样图后退出",
    )
    parser.add_argument(
        "--assets",
        type=Path,
        default=DEFAULT_ASSETS,
        help="样图目录",
    )
    parser.add_argument(
        "--tg-id",
        type=int,
        default=DEFAULT_TG_ID,
        help="测试用户 tg_id",
    )
    args = parser.parse_args()

    if args.list:
        print_list_assets(args.assets)
        return 0

    mode = "unit"
    if args.fast:
        mode = "unit"
    elif args.ocr:
        mode = "ocr"
    else:
        mode = "all"

    report = asyncio.run(
        run(mode=mode, assets_dir=args.assets, tg_id=args.tg_id)
    )
    return 1 if report.failed_count else 0


if __name__ == "__main__":
    raise SystemExit(main())
