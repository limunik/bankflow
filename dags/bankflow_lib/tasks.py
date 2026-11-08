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
    from airflow.sdk.exceptions import AirflowFailException, AirflowSkipException
except ImportError:                             # Airflow 2
    from airflow.exceptions import AirflowFailException, AirflowSkipException

try:                                            # Airflow 3 (провайдер standard)
    from airflow.providers.standard.sensors.python import PythonSensor
except ImportError:                             # Airflow 2
    from airflow.sensors.python import PythonSensor

from bankflow_lib import loader, ods_loader, pipeline
from bankflow_lib.config import (POSTGRES_CONN_ID, SENSOR_POKE_SECONDS,
                                 SENSOR_TIMEOUT_SECONDS)

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


def wait_for_files(batch):
    """Сенсор: ждёт, пока появятся ВСЕ файлы за дату.

    Генератор пишет файл во временное имя и переименовывает его в конце, поэтому
    сенсор никогда не увидит наполовину записанный файл. Если файлов нет после
    SENSOR_TIMEOUT_SECONDS, задача падает без повторов (аналог проверки с повторами
    для внешнего источника).
    """
    return PythonSensor(
        task_id="wait_for_files",
        python_callable=_files_ready,
        op_kwargs={"batch": batch},
        poke_interval=SENSOR_POKE_SECONDS,
        timeout=SENSOR_TIMEOUT_SECONDS,
        mode="reschedule",
    )


def _files_ready(batch):
    return pipeline.files_ready(batch["load_date"])


@task(map_index_template="{{ source_name }}")
def load_stg(batch, source):
    """Загружает один источник в stg. Задача размножается по списку источников и
    все копии идут параллельно. Каждая попытка пишет строку в etl_load_log."""
    context = get_current_context()
    context["source_name"] = source                     # подпись копии задачи в интерфейсе
    ti = context["ti"]
    attempt = getattr(ti, "try_number", 1)
    try:
        rows = loader.load_source(open_connection, source, batch["load_date"],
                                  run_id=context["run_id"], attempt=attempt)
    except (FileNotFoundError, ValueError) as error:
        # нет файла или не тот заголовок: повтор не исправит
        raise AirflowFailException(str(error)) from error
    return {"source": source, "rows": rows}


@task()
def stg_summary(batch, loads):
    """Итог слоя stg: сверяет число загруженных строк с таблицей."""
    problems = pipeline.verify_loaded(open_connection, batch["load_date"], list(loads))
    if problems:
        raise AirflowFailException("Расхождения: " + "; ".join(problems))
    LOG.info("stg за %s готов: %s", batch["load_date"],
             {item["source"]: item["rows"] for item in loads})


@task()
def guard_period(batch):
    """Запуск по расписанию за дату без данных пропускаем (Skipped), а не роняем.

    Ручные запуски и Backfill проходят всегда: если файла нет, это настоящая ошибка,
    и её должен показать сенсор.
    """
    run_type = str(getattr(get_current_context()["dag_run"], "run_type", "")).lower()
    if "scheduled" in run_type and pipeline.is_outside_data_period(batch["load_date"]):
        raise AirflowSkipException(
            f"За {batch['load_date']} данных нет (вне периода генерации): запуск пропущен")
    return batch


@task()
def load_ods(batch, source):
    """Переносит один источник из stg в ods (SQL-функция ods.load_<источник>).
    Одна и та же задача используется для каждого источника под своим именем (task_id),
    чтобы порядок загрузки (родители раньше детей) был виден на графе DAG."""
    context = get_current_context()
    attempt = getattr(context["ti"], "try_number", 1)
    try:
        counts = ods_loader.load_table(open_connection, source, batch["load_date"],
                                       run_id=context["run_id"], attempt=attempt)
    except ValueError as error:
        # слишком много брака: повтор не поможет, нужно смотреть файл
        raise AirflowFailException(str(error)) from error
    return {"source": source, **counts}


@task()
def ods_summary(batch, loads):
    """Итог слоя ods: сверяет обработанное число строк с таблицами ods."""
    problems = pipeline.verify_ods(open_connection, batch["load_date"], list(loads))
    if problems:
        raise AirflowFailException("Расхождения в ods: " + "; ".join(problems))
    LOG.info("ods за %s готов: %s", batch["load_date"],
             {item["source"]: item["loaded"] for item in loads})
