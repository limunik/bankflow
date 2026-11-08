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
from bankflow_lib.tasks import load_datamart, quality_check, resolve_date

with DAG(
    dag_id="bankflow_datamart",
    description="Витрины dm_transactions_daily и dm_category_monthly за дату ds",
    start_date=pendulum.datetime(2026, 7, 31, tz=TZ),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    is_paused_upon_creation=False,
    params={"load_date": None},
    default_args={"retries": 2, "retry_delay": timedelta(seconds=30), "execution_timeout": timedelta(minutes=10)},
    tags=["bankflow", "datamart"],
) as dag:
    batch = resolve_date()
    daily = load_datamart.override(task_id="dm_transactions_daily")(batch, "daily")
    category = load_datamart.override(task_id="dm_category_monthly")(batch, "category")
    checks = quality_check.override(task_id="quality_datamart")(batch, [daily, category], ["datamart"])
    batch >> [daily, category]
