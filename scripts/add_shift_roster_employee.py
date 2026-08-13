#!/usr/bin/env python3
"""向现有排班表追加员工行（复制指定工号的班次格，不重建整表）。"""
from __future__ import annotations

import argparse
import os
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _norm_row(row: list[str], width: int = 40) -> list[str]:
    out = [str(c) if c is not None else "" for c in row]
    if len(out) < width:
        out.extend([""] * (width - len(out)))
    return out[:width]


def _find_employee_row(rows: list[list[str]], employee_id: str) -> tuple[int, list[str]] | None:
    for idx, row in enumerate(rows):
        for cell in row:
            if str(cell).strip() == employee_id:
                return idx, _norm_row(row)
    return None


def _find_header_row(rows: list[list[str]]) -> int | None:
    for idx, row in enumerate(rows):
        joined = " ".join(str(c).strip() for c in row)
        if "工号" in joined and ("名字" in joined or "姓名" in joined):
            return idx
    return None


def _last_employee_row_index(rows: list[list[str]], *, header_idx: int) -> int:
    import re

    emp_re = re.compile(r"^\d{3,8}$")
    last = header_idx + 1
    for idx in range(header_idx + 2, len(rows)):
        row = rows[idx]
        emp_col = None
        header = rows[header_idx]
        for i, cell in enumerate(header):
            if "工号" in str(cell):
                emp_col = i
                break
        if emp_col is not None and emp_col < len(row):
            eid = str(row[emp_col]).strip()
            if emp_re.fullmatch(eid):
                last = idx
    return last


def append_employee_like(
    *,
    spreadsheet_id: str,
    sheet_title: str,
    credentials_json: str,
    template_employee_id: str,
    new_employee_id: str,
    new_english_name: str,
    new_seq: int | None = None,
) -> None:
    from services.google_sheets_client import (
        copy_row_format,
        fetch_sheet_values,
        sheet_id_for_title,
        update_sheet_range,
    )

    title, rows = fetch_sheet_values(
        spreadsheet_id=spreadsheet_id,
        credentials_json=credentials_json,
        sheet_title=sheet_title,
    )
    if title != sheet_title:
        sheet_title = title

    found = _find_employee_row(rows, new_employee_id)
    if found:
        idx, _ = found
        tmpl = _find_employee_row(rows, template_employee_id)
        if tmpl:
            tmpl_idx, _ = tmpl
            sheet_id = sheet_id_for_title(
                spreadsheet_id=spreadsheet_id,
                credentials_json=credentials_json,
                sheet_title=sheet_title,
            )
            if sheet_id is not None and idx != tmpl_idx:
                copy_row_format(
                    spreadsheet_id=spreadsheet_id,
                    credentials_json=credentials_json,
                    sheet_id=sheet_id,
                    source_row_index=tmpl_idx,
                    dest_row_index=idx,
                )
                print(f"fixed format {sheet_title}: {new_employee_id} row {idx + 1}")
                return
        print(f"skip {sheet_title}: {new_employee_id} 已存在（行 {idx + 1}）")
        return

    tmpl = _find_employee_row(rows, template_employee_id)
    if not tmpl:
        raise ValueError(f"{sheet_title} 未找到模板工号 {template_employee_id}")
    tmpl_idx, tmpl_row = tmpl
    header_idx = _find_header_row(rows)
    if header_idx is None:
        raise ValueError(f"{sheet_title} 未找到表头")
    last_idx = _last_employee_row_index(rows, header_idx=header_idx)
    new_row = deepcopy(tmpl_row)
    seq = new_seq if new_seq is not None else last_idx - header_idx
    new_row[0] = str(seq)
    new_row[2] = new_english_name
    new_row[3] = new_employee_id

    insert_row_1based = last_idx + 2
    dest_idx = insert_row_1based - 1
    update_sheet_range(
        spreadsheet_id=spreadsheet_id,
        credentials_json=credentials_json,
        range_a1=f"'{sheet_title}'!A{insert_row_1based}",
        values=[new_row],
    )
    sheet_id = sheet_id_for_title(
        spreadsheet_id=spreadsheet_id,
        credentials_json=credentials_json,
        sheet_title=sheet_title,
    )
    if sheet_id is not None:
        copy_row_format(
            spreadsheet_id=spreadsheet_id,
            credentials_json=credentials_json,
            sheet_id=sheet_id,
            source_row_index=tmpl_idx,
            dest_row_index=dest_idx,
        )
    print(f"OK {sheet_title}: 追加 {new_employee_id}/{new_english_name} @ row {insert_row_1based}")


def main() -> int:
    from infra.test_group_google_config import load_test_group_google_config

    parser = argparse.ArgumentParser()
    parser.add_argument("--template-id", required=True)
    parser.add_argument("--employee-id", required=True)
    parser.add_argument("--english-name", required=True)
    parser.add_argument("--seq", type=int)
    args = parser.parse_args()

    cfg = load_test_group_google_config()
    shift_sheet_title = (os.environ.get("TEST_GROUP_SHIFT_SHEET_TITLE") or "").strip()
    targets = [
        (cfg.shift_spreadsheet_id, shift_sheet_title),
        (cfg.attendance_spreadsheet_id, cfg.attendance_sheet_title),
    ]
    for sid, title in targets:
        if not sid or not title or not cfg.credentials_json:
            raise RuntimeError("test-group Sheet private bindings are required")
        append_employee_like(
            spreadsheet_id=sid,
            sheet_title=title,
            credentials_json=cfg.credentials_json,
            template_employee_id=args.template_id,
            new_employee_id=args.employee_id,
            new_english_name=args.english_name,
            new_seq=args.seq,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
