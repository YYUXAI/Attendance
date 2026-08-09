from __future__ import annotations

import psycopg2

from infra.db import database_url_scope
from services import register_service


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
