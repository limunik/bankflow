"""Первый DAG BankFlow: проверка Airflow, подключения к dwh и логической даты.

Реальной загрузки здесь нет (она в день 8). DAG доказывает три вещи:
  1. Airflow видит наш код и умеет запускать задачи;
  2. Airflow подключается к хранилищу dwh через Connection, без пароля в коде;
  3. каждый запуск знает «свою» дату ds и находит файлы с данными за неё.

Запуск ручной (schedule=None). Дата ds берётся так: параметр load_date, а если его нет,
логическая дата запуска (в форме Trigger её можно выбрать). start_date равен началу наших
данных: Airflow не создаёт задачи для дат раньше start_date.
"""
import sys
from datetime import timedelta
from pathlib import Path

import pendulum

try:                                  # Airflow 3
    from airflow.sdk import DAG
except ImportError:                   # Airflow 2
    from airflow import DAG

# Папка с нашим пакетом bankflow_lib рядом с DAG
PROJECT_DIR = str(Path(__file__).resolve().parent)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from bankflow_lib.config import TZ
from bankflow_lib.tasks import check_files, check_stg, resolve_date, summary

with DAG(
    dag_id="bankflow_smoke",
    description="Проверка Airflow: логическая дата, файлы за дату, подключение к dwh",
    start_date=pendulum.datetime(2026, 7, 31, tz=TZ),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=True,
    params={"load_date": None},
    default_args={
        "retries": 2,
        "retry_delay": timedelta(seconds=30),
        "execution_timeout": timedelta(minutes=10),
    },
    tags=["bankflow", "day7"],
) as dag:
    batch = resolve_date()
    files = check_files(batch)
    stg = check_stg(batch)
    summary(batch, files, stg)
