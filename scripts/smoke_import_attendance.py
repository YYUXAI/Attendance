#!/usr/bin/env python3
"""Attendance 部署前 import 冒烟：不连库、不读 secrets，只验证关键模块能 import。

用法（在 Attendance 源码根目录）::

    PYTHONPATH=. python3 scripts/smoke_import_attendance.py

推荐在 UX 测试机对 **即将 bake 的 shared 树** 跑（用当前 attendance 镜像的 Python/依赖）::

    IMG=uxassistant-test/attendance:${UX_IMAGE_ATTENDANCE}
    ux docker run --rm \\
      -v /srv/ux/workspaces/shared/Attendance:/app:ro \\
      -w /app --entrypoint python \"$IMG\" \\
      scripts/smoke_import_attendance.py

失败则不要执行 ``ux test restart attendance``。
"""

from __future__ import annotations

import importlib
import sys

# 覆盖启动链路与近期常改的打卡路径；顶层 from-import 缺符号会在这里炸掉。
MODULES: tuple[str, ...] = (
    "infra.checkin_ai_config",
    "infra.leave_return_keyboard_only_config",
    "infra.checkin_ocrspace_config",
    "services.checkin_ai_orchestrator",
    "services.checkin_extraction_validate_service",
    "services.checkin_image_ai_service",
    "services.checkin_ocrspace_service",
    "services.checkin_clock_time_service",
    "gateway_provider.contracts",
    "gateway_provider.event_module",
    "gateway_provider.checkin_module",
)


def main() -> int:
    failed = 0
    for name in MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:  # noqa: BLE001 — 冒烟要暴露任意导入失败
            failed += 1
            print(
                f"FAIL {name}: {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
        else:
            print(f"PASS {name}")
    if failed:
        print(f"SMOKE_FAIL count={failed}", file=sys.stderr)
        return 1
    print("SMOKE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
