import sys
from datetime import timedelta
from pathlib import Path
import pendulum
try:
    from airflow.sdk import DAG
except ImportError:
    from airflow import DAG
PROJECT_DIR = str(Path(__file__).resolve().parent)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)
from bankflow_lib.config import TZ
from bankflow_lib.tasks import check_files, check_stg, resolve_date, summary
with DAG(dag_id='bankflow_smoke', description='Проверка Airflow: логическая дата, файлы за дату, подключение к dwh', start_date=pendulum.datetime(2026, 7, 31, tz=TZ), schedule=None, catchup=False, max_active_runs=1, is_paused_upon_creation=True, params={'load_date': None}, default_args={'retries': 2, 'retry_delay': timedelta(seconds=30), 'execution_timeout': timedelta(minutes=10)}, tags=['bankflow', 'day7']) as dag:
    batch = resolve_date()
    files = check_files(batch)
    stg = check_stg(batch)
    summary(batch, files, stg)
