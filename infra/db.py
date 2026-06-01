from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2.extensions import connection as Connection
from psycopg2.extensions import cursor as Cursor


def _get_env(name: str) -> str | None:
    val = os.getenv(name)
    if val is None:
        return None
    if isinstance(val, bytes):
        val = val.decode("utf-8", errors="strict")
    return val.strip()


def _raise_friendly_connect_error(
    exc: BaseException,
    *,
    host: str,
    port: int,
    name: str,
    user: str,
) -> None:
    if isinstance(exc, UnicodeDecodeError) and sys.platform == "win32":
        msg = (
            "PostgreSQL 连接失败（中文系统下常见原因：密码错误或数据库不存在，"
            "驱动无法显示原始报错）。\n"
            f"请检查 .env：DB_HOST={host} DB_PORT={port} DB_NAME={name} DB_USER={user}\n"
            "1) 确认 postgres 密码与 DB_PASSWORD 一致\n"
            "2) 在 pgAdmin / SQL Shell 执行：\n"
            "   ALTER USER postgres PASSWORD '你的密码';\n"
            "   CREATE DATABASE attendance_bd;"
        )
        raise RuntimeError(msg) from exc
    raise exc


def get_connection() -> Connection:
    host = _get_env("DB_HOST")
    port = _get_env("DB_PORT")
    name = _get_env("DB_NAME")
    user = _get_env("DB_USER")
    password = _get_env("DB_PASSWORD")

    missing: list[str] = []
    if not host:
        missing.append("DB_HOST")
    if not port:
        missing.append("DB_PORT")
    if not name:
        missing.append("DB_NAME")
    if not user:
        missing.append("DB_USER")
    if not password:
        missing.append("DB_PASSWORD")
    if missing:
        raise RuntimeError("Missing " + " / ".join(missing))

    try:
        return psycopg2.connect(
            host=host,
            port=int(port),
            dbname=name,
            user=user,
            password=password,
            connect_timeout=10,
        )
    except UnicodeDecodeError as exc:
        _raise_friendly_connect_error(
            exc,
            host=host,
            port=int(port),
            name=name,
            user=user,
        )


@contextmanager
def get_cursor() -> Iterator[Cursor]:
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        finally:
            cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def transaction() -> Iterator[Cursor]:
    """同事务多语句：成功 commit，异常 rollback。休假提交 leave + approval 用。"""
    conn = get_connection()
    try:
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        finally:
            cur.close()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
