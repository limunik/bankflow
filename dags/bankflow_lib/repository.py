"""Работа с PostgreSQL: транзакции и SQL-запросы.

Модуль не импортирует Airflow. Соединение приходит аргументом `get_connection`
(функция, которая открывает соединение), поэтому код можно проверить и без Airflow.
Значения в SQL передаются через %s, а не склеиваются в текст запроса.
Имена таблиц берутся только из config.py, а не от пользователя.
"""
from contextlib import closing, contextmanager

from bankflow_lib.config import STG_TABLES


@contextmanager
def transaction(get_connection):
    """COMMIT при успехе, ROLLBACK при ошибке, соединение закрывается в обоих случаях."""
    with closing(get_connection()) as connection:
        connection.autocommit = False
        try:
            with connection.cursor() as cursor:
                yield cursor
            connection.commit()
        except Exception:
            connection.rollback()
            raise


def stg_rows(get_connection, source, ds):
    """Сколько строк источника лежит в stg (за дату ds, если источник по датам)."""
    meta = STG_TABLES[source]
    with transaction(get_connection) as cursor:
        if meta["by_ds"]:
            cursor.execute(f"SELECT count(*) FROM {meta['table']} WHERE _ds = %s", (ds,))
        else:
            cursor.execute(f"SELECT count(*) FROM {meta['table']}")
        return cursor.fetchone()[0]


def last_load_status(get_connection, ds):
    """Последние записи журнала etl_load_log за дату (источник, статус, строки)."""
    with transaction(get_connection) as cursor:
        cursor.execute(
            "SELECT source, status, rows_loaded FROM stg.etl_load_log "
            "WHERE ds = %s ORDER BY id DESC LIMIT 5", (ds,))
        return cursor.fetchall()
