"""Функции этапов. Обычный Python: Airflow здесь не импортируется.

Из-за этого логику можно запускать и проверять без Airflow, а задачи Airflow
(tasks.py) остаются тонкими обёртками.
"""
import logging
from datetime import date, datetime
from pathlib import Path

from bankflow_lib import repository
from bankflow_lib.config import DATA_DIR, SOURCE_FILES, STG_TABLES

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
