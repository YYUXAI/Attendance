# -*- coding: utf-8 -*-
"""从统筹部排班模板复制表格，仅保留指定员工（WG 13:00-01:00）。"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SHIFT_CODE = "WG"  # 13:00-01:00
REST_DAYS = frozenset({6, 13, 20, 27})  # 4 天月休


def _build_employee_row(
    *,
    seq: int,
    english_name: str,
    employee_id: str,
    chinese_name: str = "",
    join_date: str = "2026-6-1",
) -> list[str]:
    row = [""] * 40
    row[0] = str(seq)
    row[1] = "UX设计师"
    row[2] = english_name
    row[3] = employee_id
    row[4] = chinese_name
    row[5] = join_date
    for day in range(1, 31):
        col = 5 + day
        row[col] = "▲" if day in REST_DAYS else SHIFT_CODE
    row[36] = ""
    row[37] = "0"
    row[38] = str(len(REST_DAYS))
    return row


def create_shift_sheet_from_template(
    *,
    target_spreadsheet_id: str,
    template_spreadsheet_id: str,
    template_sheet_gid: int,
    sheet_title: str,
    credentials_json: str,
    employees: list[tuple[str, str, str]],
) -> tuple[int, str]:
    """
    employees: [(english_name, employee_id, chinese_name), ...]
    返回 (sheet_id, sheet_title)
    """
    from services.google_sheets_client import (
        copy_sheet_to_spreadsheet,
        delete_sheet_by_title,
        delete_sheet_rows,
        update_sheet_range,
    )

    delete_sheet_by_title(
        spreadsheet_id=target_spreadsheet_id,
        credentials_json=credentials_json,
        sheet_title=sheet_title,
    )

    sheet_id, title = copy_sheet_to_spreadsheet(
        source_spreadsheet_id=template_spreadsheet_id,
        source_sheet_gid=template_sheet_gid,
        destination_spreadsheet_id=target_spreadsheet_id,
        credentials_json=credentials_json,
        new_title=sheet_title,
    )

    emp_rows = [
        _build_employee_row(
            seq=i + 1,
            english_name=name,
            employee_id=eid,
            chinese_name=cn,
        )
        for i, (name, eid, cn) in enumerate(employees)
    ]
    # 模板：第 13 行 UX设计组，第 14 行起为员工（1-based）
    update_sheet_range(
        spreadsheet_id=target_spreadsheet_id,
        credentials_json=credentials_json,
        range_a1=f"'{title}'!A14",
        values=emp_rows,
    )

    # 删除员工行之后的所有内容（含原模板汇总行 UX设计组 / 夏荷组 / 统筹部总计）
    first_delete_row = 13 + len(emp_rows)
    delete_sheet_rows(
        spreadsheet_id=target_spreadsheet_id,
        credentials_json=credentials_json,
        sheet_id=sheet_id,
        start_index=first_delete_row,
        end_index=200,
    )
    return sheet_id, title


def main() -> int:
    from infra.remote_diff_google_sheets_config import load_remote_diff_google_sheets_config

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--employee",
        action="append",
        required=True,
        metavar="EMPLOYEE_ID:ENGLISH_NAME[:CHINESE_NAME]",
    )
    args = parser.parse_args()

    cfg = load_remote_diff_google_sheets_config()
    template_spreadsheet_id = (
        os.environ.get("REMOTE_DIFF_TEMPLATE_SPREADSHEET_ID") or ""
    ).strip()
    template_gid_raw = (os.environ.get("REMOTE_DIFF_TEMPLATE_SHEET_GID") or "").strip()
    sheet_title = (os.environ.get("REMOTE_DIFF_OUTPUT_SHEET_TITLE") or "").strip()
    if not cfg.spreadsheet_id or not cfg.credentials_json:
        raise RuntimeError("remote-diff Sheet private bindings are required")
    if not template_spreadsheet_id or not template_gid_raw or not sheet_title:
        raise RuntimeError("remote-diff template private bindings are required")
    try:
        template_sheet_gid = int(template_gid_raw)
    except ValueError as error:
        raise RuntimeError("remote-diff template Sheet binding is invalid") from error
    employees: list[tuple[str, str, str]] = []
    for raw in args.employee:
        parts = [part.strip() for part in raw.split(":", 2)]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise RuntimeError("--employee must be EMPLOYEE_ID:ENGLISH_NAME[:CHINESE_NAME]")
        employees.append((parts[1], parts[0], parts[2] if len(parts) == 3 else ""))
    _sheet_id, title = create_shift_sheet_from_template(
        target_spreadsheet_id=cfg.spreadsheet_id,
        template_spreadsheet_id=template_spreadsheet_id,
        template_sheet_gid=template_sheet_gid,
        sheet_title=sheet_title,
        credentials_json=cfg.credentials_json,
        employees=employees,
    )
    print(
        f"OK title={title!r} employees="
        + ",".join(f"{eid}/{name}" for name, eid, _ in employees)
        + f" shift={SHIFT_CODE}(13:00-01:00)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
