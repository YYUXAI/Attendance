from __future__ import annotations

from pathlib import Path
import sys

from dotenv import load_dotenv


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from infra.db import get_connection

    load_dotenv(".env", override=True, encoding="utf-8")
    reg_id = 25

    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT employee_id, tg_id FROM registrations WHERE id=%s",
            (reg_id,),
        )
        row = cur.fetchone()
        if not row:
            print("registration_not_found")
            conn.rollback()
            return

        employee_id, tg_id = row
        print(f"target id={reg_id} employee_id={employee_id} tg_id={tg_id}")

        # 先删除所有含 employee_id 的业务表数据（除 registrations）
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.columns
            WHERE table_schema='public'
              AND column_name='employee_id'
              AND table_name <> 'registrations'
            ORDER BY table_name
            """
        )
        employee_tables = [r[0] for r in cur.fetchall()]
        for table in employee_tables:
            cur.execute(f"DELETE FROM {table} WHERE employee_id=%s", (employee_id,))
            print(f"deleted {table}: {cur.rowcount}")

        # 再删审批任务中非 employee_id 命名的关联列
        cur.execute(
            "DELETE FROM approval_task_queue WHERE approver_employee_id=%s OR applicant_employee_id=%s",
            (employee_id, employee_id),
        )
        print(f"deleted approval_task_queue(by approver/applicant): {cur.rowcount}")

        # 再删除注册记录
        cur.execute("DELETE FROM registrations WHERE id=%s", (reg_id,))
        print(f"deleted registrations: {cur.rowcount}")

        conn.commit()
        print("done")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
