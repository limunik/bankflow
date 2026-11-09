import logging
try:
    from airflow.sdk import get_current_context, task
except ImportError:
    from airflow.decorators import task
    from airflow.operators.python import get_current_context
try:
    from airflow.sdk.exceptions import AirflowFailException, AirflowSkipException
except ImportError:
    from airflow.exceptions import AirflowFailException, AirflowSkipException
try:
    from airflow.providers.standard.sensors.python import PythonSensor
except ImportError:
    from airflow.sensors.python import PythonSensor
from bankflow_lib import clickhouse_copy, datamart_loader, dds_loader, loader, ods_loader, pipeline, quality
from bankflow_lib.config import CLICKHOUSE_CONN_ID, POSTGRES_CONN_ID, SENSOR_POKE_SECONDS, SENSOR_TIMEOUT_SECONDS
LOG = logging.getLogger(__name__)

def open_connection():
    from airflow.providers.postgres.hooks.postgres import PostgresHook
    return PostgresHook(postgres_conn_id=POSTGRES_CONN_ID).get_conn()

@task()
def resolve_date():
    context = get_current_context()
    run = context['dag_run']
    conf = run.conf or {}
    override = conf.get('load_date') or context['params'].get('load_date')
    logical_date = context.get('logical_date')
    LOG.info('Тип запуска: %s', getattr(run, 'run_type', '?'))
    LOG.info('logical_date: %s', logical_date)
    LOG.info('data_interval_start: %s', context.get('data_interval_start'))
    LOG.info('data_interval_end: %s', context.get('data_interval_end'))
    LOG.info('Параметр load_date: %s', override)
    try:
        ds = pipeline.resolve_load_date(override, logical_date)
    except ValueError as error:
        raise AirflowFailException(str(error)) from error
    LOG.info('Дата загрузки ds = %s', ds)
    return {'load_date': ds.isoformat()}

@task()
def check_files(batch):
    missing = pipeline.check_files(batch['load_date'])
    if missing:
        raise AirflowFailException(f"Нет файлов за {batch['load_date']}: {', '.join(missing)}")
    return {'missing': 0}

@task()
def check_stg(batch):
    counts = pipeline.stg_report(open_connection, batch['load_date'])
    if counts['transactions'] == 0:
        raise AirflowFailException(f"В stg нет операций за {batch['load_date']}: сначала загрузите данные")
    return counts

@task()
def summary(batch, files, stg):
    LOG.info('Готово за %s: файлы на месте, в stg операций %s', batch['load_date'], stg['transactions'])

def wait_for_files(batch):
    return PythonSensor(task_id='wait_for_files', python_callable=_files_ready, op_kwargs={'batch': batch}, poke_interval=SENSOR_POKE_SECONDS, timeout=SENSOR_TIMEOUT_SECONDS, mode='reschedule')

def _files_ready(batch):
    return pipeline.files_ready(batch['load_date'])

@task(map_index_template='{{ source_name }}')
def load_stg(batch, source):
    context = get_current_context()
    context['source_name'] = source
    ti = context['ti']
    attempt = getattr(ti, 'try_number', 1)
    try:
        rows = loader.load_source(open_connection, source, batch['load_date'], run_id=context['run_id'], attempt=attempt)
    except (FileNotFoundError, ValueError) as error:
        raise AirflowFailException(str(error)) from error
    return {'source': source, 'rows': rows}

@task()
def stg_summary(batch, loads):
    problems = pipeline.verify_loaded(open_connection, batch['load_date'], list(loads))
    if problems:
        raise AirflowFailException('Расхождения: ' + '; '.join(problems))
    LOG.info('stg за %s готов: %s', batch['load_date'], {item['source']: item['rows'] for item in loads})

@task()
def guard_period(batch):
    run_type = str(getattr(get_current_context()['dag_run'], 'run_type', '')).lower()
    if 'scheduled' in run_type and pipeline.is_outside_data_period(batch['load_date']):
        raise AirflowSkipException(f"За {batch['load_date']} данных нет (вне периода генерации): запуск пропущен")
    return batch

@task()
def load_ods(batch, source):
    context = get_current_context()
    attempt = getattr(context['ti'], 'try_number', 1)
    try:
        counts = ods_loader.load_table(open_connection, source, batch['load_date'], run_id=context['run_id'], attempt=attempt)
    except ValueError as error:
        raise AirflowFailException(str(error)) from error
    return {'source': source, **counts}

@task()
def ods_summary(batch, loads):
    problems = pipeline.verify_ods(open_connection, batch['load_date'], list(loads))
    if problems:
        raise AirflowFailException('Расхождения в ods: ' + '; '.join(problems))
    LOG.info('ods за %s готов: %s', batch['load_date'], {item['source']: item['loaded'] for item in loads})

@task()
def load_dds(batch, source):
    context = get_current_context()
    attempt = getattr(context['ti'], 'try_number', 1)
    counts = dds_loader.load_table(open_connection, source, batch['load_date'], run_id=context['run_id'], attempt=attempt)
    return {'source': source, **counts}

@task()
def quality_check(batch, loads, layers=None):
    context = get_current_context()
    attempt = getattr(context["ti"], "try_number", 1)
    try:
        result = quality.run(open_connection, batch["load_date"], run_id=context["run_id"],
                             attempt=attempt, layers=layers)
    except quality.QualityError as error:
        raise AirflowFailException(str(error)) from error
    LOG.info("Проверки %s за %s: %s", layers or "всех слоёв", batch["load_date"], result)
    return result


@task()
def load_datamart(batch, source):
    context = get_current_context()
    attempt = getattr(context["ti"], "try_number", 1)
    counts = datamart_loader.load_table(open_connection, source, batch["load_date"],
                                        run_id=context["run_id"], attempt=attempt)
    return {"source": source, **counts}


def clickhouse_client():
    try:
        from airflow.sdk import Connection
        connection = Connection.get(CLICKHOUSE_CONN_ID)
    except ImportError:
        from airflow.hooks.base import BaseHook
        connection = BaseHook.get_connection(CLICKHOUSE_CONN_ID)
    scheme = connection.conn_type or "http"
    url = f"{scheme}://{connection.host}:{connection.port or 8123}"
    return clickhouse_copy.ClickHouse(url, connection.login, connection.password, connection.schema or "bankflow")


@task()
def copy_to_clickhouse(batch, upstream=None):
    context = get_current_context()
    attempt = getattr(context["ti"], "try_number", 1)
    try:
        return clickhouse_copy.load_day(open_connection, clickhouse_client(), batch["load_date"],
                                        run_id=context["run_id"], attempt=attempt)
    except ValueError as error:
        raise AirflowFailException(str(error)) from error
