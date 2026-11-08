import os
POSTGRES_CONN_ID = os.environ.get('BANKFLOW_CONN_ID', 'bankflow_dwh')
DATA_DIR = os.environ.get('DATA_DIR', '/data')
TZ = 'UTC'
SOURCE_FILES = {'transactions': 'transactions/transactions_{ds}.csv', 'fx_rates': 'fx_rates/fx_rates_{ds}.csv', 'merchants': 'merchants/merchants.csv', 'cards': 'cards/cards.csv', 'customers': 'customers/customers.csv'}
STG_TABLES = {'transactions': {'table': 'stg.stg_transactions', 'by_ds': True}, 'fx_rates': {'table': 'stg.stg_fx_rates', 'by_ds': True}, 'merchants': {'table': 'stg.stg_merchants', 'by_ds': False}, 'cards': {'table': 'stg.stg_cards', 'by_ds': False}, 'customers': {'table': 'stg.stg_customers', 'by_ds': False}}
SOURCE_COLUMNS = {'transactions': ['transaction_id', 'card_id', 'account_id', 'customer_id', 'merchant_id', 'transaction_ts', 'amount', 'currency', 'channel', 'payment_method', 'transaction_type', 'recipient_account_id'], 'fx_rates': ['rate_date', 'currency', 'rate'], 'merchants': ['merchant_id', 'merchant_name', 'category', 'country'], 'cards': ['card_id', 'account_id', 'customer_id', 'card_scheme'], 'customers': ['customer_id', 'customer_name', 'customer_type']}
STG_LOAD_ORDER = ['merchants', 'cards', 'customers', 'fx_rates', 'transactions']
SENSOR_POKE_SECONDS = int(os.environ.get('BANKFLOW_SENSOR_POKE', '15'))
SENSOR_TIMEOUT_SECONDS = int(os.environ.get('BANKFLOW_SENSOR_TIMEOUT', '120'))
DATA_FIRST_DATE = os.environ.get('BANKFLOW_DATA_FIRST', '2026-07-31')
DATA_LAST_DATE = os.environ.get('BANKFLOW_DATA_LAST', '2026-10-29')
ODS_FUNCTIONS = {'customers': 'ods.load_customers', 'merchants': 'ods.load_merchants', 'fx_rates': 'ods.load_fx_rates', 'cards': 'ods.load_cards', 'transactions': 'ods.load_transactions'}
ODS_TABLES = {'customers': {'table': 'ods.ods_customers', 'date_column': None}, 'merchants': {'table': 'ods.ods_merchants', 'date_column': None}, 'cards': {'table': 'ods.ods_cards', 'date_column': None}, 'fx_rates': {'table': 'ods.ods_fx_rates', 'date_column': 'rate_date'}, 'transactions': {'table': 'ods.ods_transactions', 'date_column': 'ds'}}
ODS_MAX_REJECT_SHARE = float(os.environ.get('BANKFLOW_ODS_MAX_REJECT_SHARE', '0.05'))
DDS_FUNCTIONS = {'customer': 'dds.load_dim_customer', 'merchant': 'dds.load_dim_merchant', 'card': 'dds.load_dim_card', 'account': 'dds.load_dim_account', 'transaction': 'dds.load_fact_transaction'}
DQ_FAIL_SEVERITY = 'error'
