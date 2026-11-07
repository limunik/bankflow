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


def log_start(get_connection, source, ds, layer, run_id, attempt):
    """Добавляет в журнал etl_load_log строку «running» и возвращает её id.

    Отдельное соединение с autocommit: запись остаётся в журнале, даже если
    основная загрузка упадёт и откатит свою транзакцию. Каждая попытка задачи
    (включая повторы Airflow) пишет свою строку, как требует ФТ-6.
    """
    with closing(get_connection()) as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO stg.etl_load_log (source, ds, started_at, status, layer, run_id, attempt) "
                "VALUES (%s, %s, now(), 'running', %s, %s, %s) RETURNING id",
                (source, ds, layer, run_id, attempt))
            return cursor.fetchone()[0]


def log_finish(get_connection, log_id, status, rows, error):
    """Дописывает в журнал итог: статус, число строк, время конца, текст ошибки."""
    with closing(get_connection()) as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE stg.etl_load_log "
                "SET finished_at = now(), status = %s, rows_loaded = %s, error_message = %s "
                "WHERE id = %s",
                (status, rows, error, log_id))
