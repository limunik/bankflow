"""Основной DAG BankFlow: за дату ds проверяет файлы и грузит три-пять источников в stg.

Порядок:
    resolve_date -> guard_period -> wait_for_files -> load_stg (по задаче на источник, параллельно) -> stg_summary

Дальше в него добавятся ods (дни 9-10), dds (день 13) и запуск DAG витрин (день 17).

Дата ds берётся так: параметр load_date, а если его нет, логическая дата запуска.
Для запуска по расписанию и для Backfill логическая дата это начало обрабатываемых суток,
то есть сама дата ds. Для ручного запуска укажите load_date, а логическую дату не меняйте.

Пока DAG на паузе, НИКАКОЙ запуск (ручной и Backfill тоже) не стартует: его нужно включить.
При включении Airflow создаёт плановый запуск за последние сутки. Данные у нас с 31 июля по
29 октября 2026, поэтому guard_period такие запуски пропускает (Skipped), а не роняет.
max_active_runs=1: два запуска не должны одновременно заменять общие справочники.
"""
import sys
from datetime import timedelta
from pathlib import Path

import pendulum

try:                                  # Airflow 3
    from airflow.sdk import DAG
except ImportError:                   # Airflow 2
    from airflow import DAG

PROJECT_DIR = str(Path(__file__).resolve().parent)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from bankflow_lib.config import STG_LOAD_ORDER, TZ
from bankflow_lib.tasks import (guard_period, load_stg, resolve_date, stg_summary,
                                wait_for_files)

with DAG(
    dag_id="bankflow_pipeline",
    description="Загрузка источников за дату ds в слой stg (дальше ods, dds, витрины)",
    start_date=pendulum.datetime(2026, 7, 31, tz=TZ),
    schedule="@daily",
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=True,
    params={"load_date": None},
    default_args={
        "retries": 2,
        "retry_delay": timedelta(seconds=30),
        "execution_timeout": timedelta(minutes=10),
    },
    tags=["bankflow", "day8"],
) as dag:
    batch = resolve_date()
    guard = guard_period(batch)
    ready = wait_for_files(batch)
    loads = load_stg.partial(batch=batch).expand(source=STG_LOAD_ORDER)
    summary = stg_summary(batch, loads)

    batch >> guard >> ready >> loads
