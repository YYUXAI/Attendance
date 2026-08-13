"""Fail-closed Docker secret file entrypoint for Attendance runtime processes."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from urllib.parse import quote


def _fail(name: str, reason: str) -> None:
    raise RuntimeError(f"{name} {reason}")


def _read_file_variable(file_variable: str) -> None:
    target_variable = file_variable[: -len("_FILE")]
    if target_variable in os.environ:
        _fail(target_variable, f"conflicts with {file_variable}")
    path_value = os.environ.get(file_variable)
    if not path_value:
        _fail(file_variable, "must name a secret file")
    path = Path(path_value)
    try:
        metadata = path.lstat()
    except OSError:
        _fail(file_variable, "is unreadable")
    if not stat.S_ISREG(metadata.st_mode):
        _fail(file_variable, "must reference a regular file")
    try:
        value = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        _fail(file_variable, "is unreadable")
    if value.endswith("\n"):
        value = value[:-1]
    if not value:
        _fail(file_variable, "must not be empty")
    os.environ[target_variable] = value
    del os.environ[file_variable]


def _required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        _fail(name, "is required")
    return value


def _build_attendance_database_url() -> None:
    password_variable = "ATTENDANCE_DATABASE_PASSWORD"
    if password_variable not in os.environ:
        return
    if "ATTENDANCE_DATABASE_URL" in os.environ:
        _fail("ATTENDANCE_DATABASE_URL", f"conflicts with {password_variable}_FILE")
    user = _required("ATTENDANCE_DATABASE_USER")
    host = _required("ATTENDANCE_DATABASE_HOST")
    port = _required("ATTENDANCE_DATABASE_PORT")
    name = _required("ATTENDANCE_DATABASE_NAME")
    password = _required(password_variable)
    os.environ["ATTENDANCE_DATABASE_URL"] = (
        f"postgresql://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}/{quote(name, safe='')}"
    )
    del os.environ[password_variable]


def main() -> int:
    if len(sys.argv) < 2:
        raise RuntimeError("runtime command is required")
    for file_variable in sorted(name for name in os.environ if name.endswith("_FILE")):
        _read_file_variable(file_variable)
    _build_attendance_database_url()
    os.execvp(sys.argv[1], sys.argv[1:])
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
