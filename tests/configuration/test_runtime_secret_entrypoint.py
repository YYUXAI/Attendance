from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "attendance_runtime_secret_entrypoint",
    ROOT / "runtime-secret-entrypoint.py",
)
assert SPEC is not None and SPEC.loader is not None
ENTRYPOINT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ENTRYPOINT)


def test_file_variable_is_resolved_without_leaving_the_path_in_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "binding"
    secret.write_text("fake-test-value\n", encoding="utf-8")
    secret.chmod(0o600)
    monkeypatch.setenv("CHECKIN_AI_API_KEY_FILE", str(secret))
    monkeypatch.delenv("CHECKIN_AI_API_KEY", raising=False)

    ENTRYPOINT._read_file_variable("CHECKIN_AI_API_KEY_FILE")

    assert os.environ["CHECKIN_AI_API_KEY"] == "fake-test-value"
    assert "CHECKIN_AI_API_KEY_FILE" not in os.environ


def test_file_variable_conflict_symlink_and_empty_binding_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = tmp_path / "binding"
    secret.write_text("fake-test-value", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(secret)
    monkeypatch.setenv("CHECKIN_AI_API_KEY", "already-present")
    monkeypatch.setenv("CHECKIN_AI_API_KEY_FILE", str(secret))
    with pytest.raises(RuntimeError, match="conflicts"):
        ENTRYPOINT._read_file_variable("CHECKIN_AI_API_KEY_FILE")

    monkeypatch.delenv("CHECKIN_AI_API_KEY")
    monkeypatch.setenv("CHECKIN_AI_API_KEY_FILE", str(link))
    with pytest.raises(RuntimeError, match="regular file"):
        ENTRYPOINT._read_file_variable("CHECKIN_AI_API_KEY_FILE")

    empty = tmp_path / "empty"
    empty.write_text("", encoding="utf-8")
    monkeypatch.setenv("CHECKIN_AI_API_KEY_FILE", str(empty))
    with pytest.raises(RuntimeError, match="must not be empty"):
        ENTRYPOINT._read_file_variable("CHECKIN_AI_API_KEY_FILE")


def test_database_password_file_builds_url_without_retaining_password_variable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATTENDANCE_DATABASE_PASSWORD", "fake password")
    monkeypatch.setenv("ATTENDANCE_DATABASE_USER", "ux_attendance_app")
    monkeypatch.setenv("ATTENDANCE_DATABASE_HOST", "postgres")
    monkeypatch.setenv("ATTENDANCE_DATABASE_PORT", "5432")
    monkeypatch.setenv("ATTENDANCE_DATABASE_NAME", "attendance_v1")
    monkeypatch.delenv("ATTENDANCE_DATABASE_URL", raising=False)

    ENTRYPOINT._build_attendance_database_url()

    assert os.environ["ATTENDANCE_DATABASE_URL"].startswith(
        "postgresql://ux_attendance_app:fake%20password@postgres:5432/"
    )
    assert "ATTENDANCE_DATABASE_PASSWORD" not in os.environ
