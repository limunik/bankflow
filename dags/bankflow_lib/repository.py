"""Работа с PostgreSQL: транзакции и SQL-запросы.

Модуль не импортирует Airflow. Соединение приходит аргументом `get_connection`
(функция, которая открывает соединение), поэтому код можно проверить и без Airflow.
Значения в SQL передаются через %s, а не склеиваются в текст запроса.
Имена таблиц берутся только из config.py, а не от пользователя.
"""
from contextlib import closing, contextmanager

from bankflow_lib.config import ODS_FUNCTIONS, ODS_TABLES, STG_TABLES


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


def log_finish(get_connection, log_id, status, rows, error, rows_rejected=None):
    """Дописывает в журнал итог: статус, число строк, отбраковано, время конца, текст ошибки."""
    with closing(get_connection()) as connection:
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute(
                "UPDATE stg.etl_load_log "
                "SET finished_at = now(), status = %s, rows_loaded = %s, error_message = %s, "
                "    rows_rejected = %s "
                "WHERE id = %s",
                (status, rows, error, rows_rejected, log_id))


def call_ods_function(get_connection, source, ds, max_reject_share=None):
    """Вызывает SQL-функцию переноса stg -> ods за дату ds одной транзакцией.

    Функция сама берёт блокировку, чистит прежние отбраковки за дату и делает upsert,
    поэтому повторный вызов за ту же дату не меняет данные. Возвращает словарь счётчиков.

    Если задан max_reject_share и отбраковано больше этой доли, бросает ValueError ВНУТРИ
    транзакции: изменения откатываются, в ods остаётся прежнее состояние.
    """
    function = ODS_FUNCTIONS[source]
    with transaction(get_connection) as cursor:
        cursor.execute(f"SELECT * FROM {function}(%s::date)", (ds,))
        stg_rows, duplicates, rejected, inserted, updated = cursor.fetchone()
        share = rejected / stg_rows if stg_rows else 0
        if max_reject_share is not None and share > max_reject_share:
            raise ValueError(
                f"{source}: отбраковано {share:.1%} строк (порог {max_reject_share:.0%}), "
                f"загрузка отменена; смотрите ods.ods_reject за {ds}")
    return {"stg_rows": stg_rows, "duplicates": duplicates, "rejected": rejected,
            "inserted": inserted, "updated": updated}


def ods_rows(get_connection, source, ds):
    """Сколько строк источника лежит в ods (за дату, если у таблицы есть колонка даты)."""
    meta = ODS_TABLES[source]
    with transaction(get_connection) as cursor:
        if meta["date_column"]:
            cursor.execute(
                f"SELECT count(*) FROM {meta['table']} WHERE {meta['date_column']} = %s", (ds,))
        else:
            cursor.execute(f"SELECT count(*) FROM {meta['table']}")
        return cursor.fetchone()[0]
