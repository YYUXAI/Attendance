from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path


ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
REQUIRED_VALUES = {
    "ATTENDANCE_BOT_OWNER": "ux_assistant",
    "ATTENDANCE_RUN_MODE": "webhook",
    "ATTENDANCE_REGISTER_BOT_COMMANDS": "0",
    "ATTENDANCE_WEBHOOK_RUN_WORKERS": "0",
}


def _updated_lines(lines: list[str]) -> tuple[list[str], int]:
    remaining = dict(REQUIRED_VALUES)
    output: list[str] = []
    changed = 0
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key not in remaining:
            output.append(line)
            continue
        replacement = f"{key}={remaining.pop(key)}\n"
        changed += int(line != replacement)
        output.append(replacement)
    for key, value in remaining.items():
        output.append(f"{key}={value}\n")
        changed += 1
    return output, changed


def _write_atomic(lines: list[str]) -> None:
    fd, raw_path = tempfile.mkstemp(prefix=".env.unified.", dir=ENV_PATH.parent)
    temp_path = Path(raw_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.writelines(lines)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, ENV_PATH)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Configure the Attendance unified webhook owner/runtime safely."
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-unified-webhook", action="store_true")
    args = parser.parse_args()

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines(keepends=True)
    updated, changed = _updated_lines(lines)
    if args.apply:
        if not args.confirm_unified_webhook:
            raise SystemExit("--apply requires --confirm-unified-webhook")
        _write_atomic(updated)
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                "keys_managed": len(REQUIRED_VALUES),
                "keys_changed": changed,
                "file_mode": "0600" if args.apply else "unchanged",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
