from __future__ import annotations

import psycopg2

from infra.db import database_url_scope
from services import register_service


def read_private_registration_session_status(
    *,
    database_url: str,
    telegram_user_id: int,
    private_chat_id: int,
) -> bool:
    with database_url_scope(database_url):
        with psycopg2.connect(database_url) as connection:
            with connection.cursor() as cursor:
                return register_service.is_waiting_register_input(
                    cursor,
                    tg_id=telegram_user_id,
                    private_chat_id=private_chat_id,
                )


def end_private_registration_session(
    *,
    database_url: str,
    telegram_user_id: int,
) -> None:
    with database_url_scope(database_url):
        with psycopg2.connect(database_url) as connection:
            with connection.cursor() as cursor:
                register_service.clear_waiting_register_input(
                    cursor,
                    tg_id=telegram_user_id,
                )
