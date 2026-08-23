#!/usr/bin/env python3
from pathlib import Path

path = Path("/srv/ux/workspaces/shared/Attendance/test_gateway_provider_event.py")
text = path.read_text()

helper = '''

def _insert_admin_export_scope(
    cursor,
    *,
    employee_id: str,
    chat_id: int,
) -> None:
    cursor.execute(
        """
        INSERT INTO public.attendance_business_facts (
            fact_kind, subject_key, value_text
        ) VALUES (%s, %s, %s)
        ON CONFLICT (fact_kind, subject_key) DO UPDATE
        SET value_text = EXCLUDED.value_text,
            updated_at = clock_timestamp()
        """,
        ("admin_export_chat_scope", str(employee_id), str(int(chat_id))),
    )


def _seed_admin_with_export_scope(
    cursor,
    *,
    employee_id: str = "74808",
    english_name: str = "GRANDFOR",
    tg_id: int = 81002,
    registered_chat_id: int = 81002,
    export_chat_id: int = -10081002,
) -> None:
    cursor.execute(
        """
        INSERT INTO registrations (
            employee_id, english_name, tg_id, registered_chat_id
        ) VALUES (%s, %s, %s, %s)
        """,
        (employee_id, english_name, tg_id, registered_chat_id),
    )
    cursor.execute(
        "INSERT INTO admin_list (admin_employee_id) VALUES (%s)",
        (employee_id,),
    )
    _insert_admin_export_scope(
        cursor,
        employee_id=employee_id,
        chat_id=export_chat_id,
    )

'''

if "_insert_admin_export_scope" not in text:
    text = text.replace("def _database_url() -> str:\n", helper + "def _database_url() -> str:\n", 1)

if "DELETE FROM attendance_business_facts" not in text:
    text = text.replace(
        '            cursor.execute("DELETE FROM attendance_admin_export_sessions")\n',
        '            cursor.execute("DELETE FROM attendance_admin_export_sessions")\n'
        '            cursor.execute(\n'
        '                "DELETE FROM attendance_business_facts "\n'
        '                "WHERE fact_kind = %s",\n'
        '                ("admin_export_chat_scope",),\n'
        '            )\n',
        1,
    )

old = """            cursor.execute(
                \"\"\"
                INSERT INTO registrations (
                    employee_id, english_name, tg_id, registered_chat_id
                ) VALUES (%s, %s, %s, %s)
                \"\"\",
                (\"74808\", \"GRANDFOR\", 81002, 81002),
            )
            cursor.execute(
                \"INSERT INTO admin_list (admin_employee_id) VALUES (%s)\",
                (\"74808\",),
            )"""

for func_name in (
    "test_admin_export_callback_returns_deterministic_gateway_document_bytes",
    "test_admin_export_preserves_old_progress_document_delete_trace",
    "test_terminal_progress_receipt_fails_deferred_run_without_business_work",
    "test_admin_export_failure_preserves_old_error_and_progress_cleanup",
):
    marker = f"def {func_name}"
    idx = text.find(marker)
    if idx == -1:
        raise SystemExit(f"missing {func_name}")
    sub = text[idx:]
    if old not in sub:
        if "_seed_admin_with_export_scope(cursor)" in sub:
            continue
        raise SystemExit(f"seed block missing in {func_name}")
    sub = sub.replace(old, "            _seed_admin_with_export_scope(cursor)", 1)
    text = text[:idx] + sub

text = text.replace(
    '        "collect_rows_for_range",\n        must_not_collect,',
    '        "collect_rows_for_single_group",\n        must_not_collect,',
)
text = text.replace(
    '        "collect_rows_for_range",\n        fail_export,',
    '        "collect_rows_for_single_group",\n        fail_export,',
)

path.write_text(text)
print("patched", path)
