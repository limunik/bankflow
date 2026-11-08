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
from bankflow_lib.config import STG_LOAD_ORDER, TZ
from bankflow_lib.tasks import guard_period, load_dds, load_ods, load_stg, ods_summary, quality_check, resolve_date, stg_summary, wait_for_files
with DAG(dag_id='bankflow_pipeline', description='Загрузка источников за дату ds в слой stg (дальше ods, dds, витрины)', start_date=pendulum.datetime(2026, 7, 31, tz=TZ), schedule='@daily', catchup=False, max_active_runs=1, is_paused_upon_creation=True, params={'load_date': None}, default_args={'retries': 2, 'retry_delay': timedelta(seconds=30), 'execution_timeout': timedelta(minutes=10)}, tags=['bankflow', 'core']) as dag:
    batch = resolve_date()
    guard = guard_period(batch)
    ready = wait_for_files(batch)
    loads = load_stg.partial(batch=batch).expand(source=STG_LOAD_ORDER)
    summary = stg_summary(batch, loads)
    batch >> guard >> ready >> loads
    ods_customers = load_ods.override(task_id='ods_customers')(batch, 'customers')
    ods_merchants = load_ods.override(task_id='ods_merchants')(batch, 'merchants')
    ods_fx_rates = load_ods.override(task_id='ods_fx_rates')(batch, 'fx_rates')
    ods_cards = load_ods.override(task_id='ods_cards')(batch, 'cards')
    ods_transactions = load_ods.override(task_id='ods_transactions')(batch, 'transactions')
    ods_check = ods_summary(batch, [ods_customers, ods_merchants, ods_fx_rates, ods_cards, ods_transactions])
    summary >> [ods_customers, ods_merchants, ods_fx_rates]
    ods_customers >> ods_cards
    [ods_cards, ods_merchants] >> ods_transactions
    dds_customer = load_dds.override(task_id='dds_customer')(batch, 'customer')
    dds_merchant = load_dds.override(task_id='dds_merchant')(batch, 'merchant')
    dds_card = load_dds.override(task_id='dds_card')(batch, 'card')
    dds_account = load_dds.override(task_id='dds_account')(batch, 'account')
    dds_transaction = load_dds.override(task_id='dds_transaction')(batch, 'transaction')
    checks = quality_check(batch, [dds_customer, dds_merchant, dds_card, dds_account, dds_transaction])
    ods_check >> [dds_customer, dds_merchant, dds_card, dds_account]
    [dds_customer, dds_merchant, dds_card] >> dds_transaction
