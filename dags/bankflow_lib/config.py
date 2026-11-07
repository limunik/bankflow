"""Настройки BankFlow для Airflow.

Здесь нет секретов и нет обращений к сети. Всё, что может отличаться на другом ноутбуке
или стенде, читается из переменных окружения: код DAG не нужно править (никакого hardcode).
Пароль к базе тут тоже не нужен: его хранит Airflow Connection (см. docker-compose.airflow.yml).
"""
import os

# ID подключения к хранилищу dwh в Airflow Connections
POSTGRES_CONN_ID = os.environ.get("BANKFLOW_CONN_ID", "bankflow_dwh")

# Папка с данными внутри контейнера Airflow (монтируется из ./data)
DATA_DIR = os.environ.get("DATA_DIR", "/data")

# Часовой пояс расписания. UTC, чтобы граница суток совпадала с датой в файлах.
TZ = "UTC"

# Какие файлы ожидаются за дату ds: источник -> путь относительно DATA_DIR.
# События (transactions, fx_rates) лежат отдельным файлом на каждую дату,
# справочники (merchants, cards, customers) один файл на все даты.
SOURCE_FILES = {
    "transactions": "transactions/transactions_{ds}.csv",
    "fx_rates": "fx_rates/fx_rates_{ds}.csv",
    "merchants": "merchants/merchants.csv",
    "cards": "cards/cards.csv",
    "customers": "customers/customers.csv",
}

# В какую таблицу stg попадает источник, и грузится ли он по датам.
# by_ds=True: строки за дату можно посчитать по колонке _ds.
STG_TABLES = {
    "transactions": {"table": "stg.stg_transactions", "by_ds": True},
    "fx_rates": {"table": "stg.stg_fx_rates", "by_ds": True},
    "merchants": {"table": "stg.stg_merchants", "by_ds": False},
    "cards": {"table": "stg.stg_cards", "by_ds": False},
    "customers": {"table": "stg.stg_customers", "by_ds": False},
}

# Колонки файлов В ТОМ ЖЕ ПОРЯДКЕ, что в заголовке CSV (загрузчик сверяет заголовок).
SOURCE_COLUMNS = {
    "transactions": [
        "transaction_id", "card_id", "account_id", "customer_id", "merchant_id",
        "transaction_ts", "amount", "currency", "channel", "payment_method",
        "transaction_type", "recipient_account_id",
    ],
    "fx_rates": ["rate_date", "currency", "rate"],
    "merchants": ["merchant_id", "merchant_name", "category", "country"],
    "cards": ["card_id", "account_id", "customer_id", "card_scheme"],
    "customers": ["customer_id", "customer_name", "customer_type"],
}

# Источники, которые грузятся в stg параллельными задачами
STG_LOAD_ORDER = ["merchants", "cards", "customers", "fx_rates", "transactions"]

# Сенсор ожидания файлов: как часто проверять и сколько ждать, секунд.
# Если файлов нет после ожидания, задача падает (повторять дальше бессмысленно).
SENSOR_POKE_SECONDS = int(os.environ.get("BANKFLOW_SENSOR_POKE", "15"))
SENSOR_TIMEOUT_SECONDS = int(os.environ.get("BANKFLOW_SENSOR_TIMEOUT", "120"))

# Период, за который у нас есть данные. Запуск ПО РАСПИСАНИЮ за дату вне периода
# пропускается (а не падает): после 29 октября 2026 новых файлов просто нет.
# Ручные запуски и Backfill этим правилом не ограничены.
DATA_FIRST_DATE = os.environ.get("BANKFLOW_DATA_FIRST", "2026-07-31")
DATA_LAST_DATE = os.environ.get("BANKFLOW_DATA_LAST", "2026-10-29")
