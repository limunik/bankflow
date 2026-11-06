"""Тонкие обёртки Airflow: контекст запуска, подключение и декораторы задач.

Бизнес-логики здесь нет, она в pipeline.py. Ошибки, которые не исправятся повтором
(нет файла, нет данных, неверная дата), превращаются в AirflowFailException: Airflow
не делает для них retry. Временные сбои (например, база недоступна) повторяются.
"""
import logging

try:                                            # Airflow 3
    from airflow.sdk import get_current_context, task
except ImportError:                             # Airflow 2
    from airflow.decorators import task
    from airflow.operators.python import get_current_context

try:                                            # Airflow 3
    from airflow.sdk.exceptions import AirflowFailException
except ImportError:                             # Airflow 2
    from airflow.exceptions import AirflowFailException

from bankflow_lib import pipeline
from bankflow_lib.config import POSTGRES_CONN_ID

LOG = logging.getLogger(__name__)


def open_connection():
    """Соединение с dwh. Подключение читается из Airflow Connection в момент вызова,
    а не при разборе DAG; пароля в коде нет."""
    from airflow.providers.postgres.hooks.postgres import PostgresHook

    return PostgresHook(postgres_conn_id=POSTGRES_CONN_ID).get_conn()


@task()
def resolve_date():
    """Определяет дату загрузки и печатает всё, что Airflow знает о запуске."""
    context = get_current_context()
    run = context["dag_run"]
    conf = run.conf or {}
    override = conf.get("load_date") or context["params"].get("load_date")
    logical_date = context.get("logical_date")

    LOG.info("Тип запуска: %s", getattr(run, "run_type", "?"))
    LOG.info("logical_date: %s", logical_date)
    LOG.info("data_interval_start: %s", context.get("data_interval_start"))
    LOG.info("data_interval_end: %s", context.get("data_interval_end"))
    LOG.info("Параметр load_date: %s", override)

    try:
        ds = pipeline.resolve_load_date(override, logical_date)
    except ValueError as error:
        raise AirflowFailException(str(error)) from error
    LOG.info("Дата загрузки ds = %s", ds)
    return {"load_date": ds.isoformat()}


@task()
def check_files(batch):
    """Проверяет, что файлы за дату на месте."""
    missing = pipeline.check_files(batch["load_date"])
    if missing:
        raise AirflowFailException(
            f"Нет файлов за {batch['load_date']}: {', '.join(missing)}")
    return {"missing": 0}


@task()
def check_stg(batch):
    """Читает хранилище через Airflow Connection и считает строки за дату."""
    counts = pipeline.stg_report(open_connection, batch["load_date"])
    if counts["transactions"] == 0:
        raise AirflowFailException(
            f"В stg нет операций за {batch['load_date']}: сначала загрузите данные")
    return counts


@task()
def summary(batch, files, stg):
    """Итог проверки: что нашли за дату."""
    LOG.info("Готово за %s: файлы на месте, в stg операций %s",
             batch["load_date"], stg["transactions"])
