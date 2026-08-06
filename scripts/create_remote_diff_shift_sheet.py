# -*- coding: utf-8 -*-
"""从统筹部排班模板复制表格，仅保留指定员工（WG 13:00-01:00）。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv

load_dotenv(ROOT / ".env", override=True, encoding="utf-8")

# 统筹部 6 月排班模板
TEMPLATE_SPREADSHEET_ID = "1BD6PeaCdiavNiynK8Dp2e5kqYSHT-tPle5brn-2LSiU"
TEMPLATE_SHEET_GID = 757170338

# 工号打卡群班表（默认目标）
DEFAULT_TARGET_SPREADSHEET_ID = "10RTURqDJqSEmaTQxl6dQU_Sc5zZlH-Wg92zrdDy9xsw"
DEFAULT_SHEET_TITLE = "排班 2026-06"

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
        source_spreadsheet_id=TEMPLATE_SPREADSHEET_ID,
        source_sheet_gid=TEMPLATE_SHEET_GID,
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
    parser.add_argument("--spreadsheet-id", default=DEFAULT_TARGET_SPREADSHEET_ID)
    parser.add_argument("--sheet-title", default=DEFAULT_SHEET_TITLE)
    args = parser.parse_args()

    cfg = load_remote_diff_google_sheets_config()
    creds = cfg.credentials_json
    employees = [
        ("nliliii", "99999", ""),
        ("bodyhh", "102", ""),
        ("Brucewillis", "17025", ""),
    ]
    sheet_id, title = create_shift_sheet_from_template(
        target_spreadsheet_id=args.spreadsheet_id.strip(),
        sheet_title=args.sheet_title.strip(),
        credentials_json=creds,
        employees=employees,
    )
    print(
        f"OK sheet_id={sheet_id} title={title!r} employees="
        + ",".join(f"{eid}/{name}" for name, eid, _ in employees)
        + f" shift={SHIFT_CODE}(13:00-01:00)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
