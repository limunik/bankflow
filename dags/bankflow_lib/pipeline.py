"""Функции этапов. Обычный Python: Airflow здесь не импортируется.

Из-за этого логику можно запускать и проверять без Airflow, а задачи Airflow
(tasks.py) остаются тонкими обёртками.
"""
import logging
from datetime import date, datetime
from pathlib import Path

from bankflow_lib import repository
from bankflow_lib.config import (DATA_DIR, DATA_FIRST_DATE, DATA_LAST_DATE,
                                 SOURCE_FILES, STG_TABLES)

LOG = logging.getLogger(__name__)


def resolve_load_date(override, logical_date):
    """Дата загрузки ds.

    Приоритет: параметр запуска (ручной Trigger) -> логическая дата запуска Airflow.
    Логическая дата это НЕ «сегодня»: для запуска по расписанию она равна началу
    обрабатываемого интервала (запуск за 2026-10-27 стартует уже 28-го).
    """
    if override:
        return date.fromisoformat(str(override)[:10])
    if logical_date is not None:
        if isinstance(logical_date, datetime):
            return logical_date.date()
        return logical_date
    raise ValueError("Не задана дата: укажите load_date в параметрах запуска")


def files_for_date(ds, data_dir=DATA_DIR):
    """Какие файлы ожидаются за дату и существуют ли они: {источник: (путь, есть_ли)}."""
    result = {}
    for source, pattern in SOURCE_FILES.items():
        path = Path(data_dir) / pattern.format(ds=ds)
        result[source] = (str(path), path.exists())
    return result


def check_files(ds, data_dir=DATA_DIR):
    """Проверяет наличие файлов. Возвращает список отсутствующих источников."""
    report = files_for_date(ds, data_dir)
    missing = [source for source, (_, exists) in report.items() if not exists]
    for source, (path, exists) in report.items():
        LOG.info("%-12s %s %s", source, "есть   " if exists else "НЕТ    ", path)
    return missing


def stg_report(get_connection, ds):
    """Сколько строк каждого источника в stg за дату (справочники считаются целиком)."""
    counts = {source: repository.stg_rows(get_connection, source, ds) for source in STG_TABLES}
    for source, rows in counts.items():
        scope = "за дату" if STG_TABLES[source]["by_ds"] else "всего  "
        LOG.info("%-12s %s: %s строк", source, scope, rows)
    for source, status, rows in repository.last_load_status(get_connection, ds):
        LOG.info("журнал загрузок: %s %s %s", source, status, rows)
    return counts


def files_ready(ds, data_dir=DATA_DIR):
    """True, если все файлы за дату на месте. Её вызывает сенсор на каждой проверке."""
    missing = check_files(ds, data_dir)
    if missing:
        LOG.info("Файлов за %s ещё нет: %s. Проверю снова.", ds, ", ".join(missing))
    return not missing


def verify_loaded(get_connection, ds, loads):
    """Сверяет, что загружено столько же строк, сколько теперь лежит в stg.

    loads: список {"source": ..., "rows": ...} из задач загрузки. Возвращает список расхождений.
    """
    problems = []
    for item in loads:
        source, loaded = item["source"], item["rows"]
        in_table = repository.stg_rows(get_connection, source, ds)
        LOG.info("%-12s загружено %s, в таблице %s", source, loaded, in_table)
        if loaded != in_table:
            problems.append(f"{source}: загружено {loaded}, в таблице {in_table}")
    return problems


def is_outside_data_period(ds):
    """True, если за дату ds у нас не может быть данных (вне периода генерации)."""
    ds = date.fromisoformat(str(ds)[:10])
    return not (date.fromisoformat(DATA_FIRST_DATE) <= ds <= date.fromisoformat(DATA_LAST_DATE))


def verify_ods(get_connection, ds, loads):
    """Сверяет итог ods: загружено столько, сколько лежит в таблице ods.

    loads: список {"source", "loaded", ...} из задач ods. Для справочников в таблице их
    общее число (все даты), для событий строки за дату. Возвращает список расхождений.
    """
    problems = []
    for item in loads:
        source, loaded = item["source"], item["loaded"]
        in_table = repository.ods_rows(get_connection, source, ds)
        LOG.info("%-12s в ods обработано %s, в таблице %s", source, loaded, in_table)
        if loaded != in_table:
            problems.append(f"{source}: обработано {loaded}, в таблице {in_table}")
    return problems
