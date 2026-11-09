import json
import logging
import os
import traceback
import urllib.error
import urllib.parse
import urllib.request
from decimal import Decimal

from bankflow_lib import repository

LOG = logging.getLogger(__name__)

COLUMNS = ["ds", "operations", "purchases", "transfers", "active_cards", "amount_kgs", "amount_usd",
           "confirm_operations", "suspicious_operations", "suspicious_share"]
TABLE = "bankflow.dm_transactions_daily"


class ClickHouseError(RuntimeError):
    pass


class ClickHouse:
    def __init__(self, url, user, password, database="bankflow", timeout=30):
        self.url = url.rstrip("/")
        self.user = user
        self.password = password
        self.database = database
        self.timeout = timeout

    def execute(self, query, data=None):
        params = {"query": query, "database": self.database}
        request = urllib.request.Request(
            f"{self.url}/?{urllib.parse.urlencode(params)}",
            data=data,
            method="POST",
            headers={"X-ClickHouse-User": self.user, "X-ClickHouse-Key": self.password},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            raise ClickHouseError(f"{error.code}: {error.read().decode('utf-8', 'replace')[:500]}") from error
        except urllib.error.URLError as error:
            raise ClickHouseError(f"ClickHouse недоступен: {error.reason}") from error


def client_from_env():
    return ClickHouse(
        os.environ.get("CLICKHOUSE_URL", "http://localhost:8123"),
        os.environ["CLICKHOUSE_USER"],
        os.environ["CLICKHOUSE_PASSWORD"],
        os.environ.get("CLICKHOUSE_DB", "bankflow"),
    )


def read_mart_row(get_connection, ds):
    with repository.transaction(get_connection) as cursor:
        cursor.execute(f"SELECT {', '.join(COLUMNS)} FROM datamart.dm_transactions_daily WHERE ds = %s", (ds,))
        row = cursor.fetchone()
    if row is None:
        raise ValueError(f"В витрине datamart.dm_transactions_daily нет строки за {ds}")
    return dict(zip(COLUMNS, row))


def to_json_row(row):
    result = {}
    for key, value in row.items():
        if isinstance(value, Decimal):
            result[key] = str(value)
        elif hasattr(value, "isoformat"):
            result[key] = value.isoformat()
        else:
            result[key] = value
    return json.dumps(result)


def copy_day(get_connection, client, ds):
    row = read_mart_row(get_connection, ds)
    partition = row["ds"].strftime("%Y%m")
    client.execute(f"ALTER TABLE {TABLE} DELETE WHERE ds = '{ds}' SETTINGS mutations_sync = 2")
    columns = ", ".join(COLUMNS)
    client.execute(f"INSERT INTO {TABLE} ({columns}) FORMAT JSONEachRow", to_json_row(row).encode("utf-8"))
    answer = client.execute(
        f"SELECT count(), sum(operations), sum(amount_kgs), sum(suspicious_operations) FROM {TABLE} WHERE ds = '{ds}' FORMAT JSONCompact"
    )
    count, operations, amount, suspicious = json.loads(answer)["data"][0]
    problems = []
    if int(count) != 1:
        problems.append(f"строк за {ds} в ClickHouse {count}, ожидалась 1")
    if int(operations) != row["operations"]:
        problems.append(f"операций {operations}, в Postgres {row['operations']}")
    if Decimal(str(amount)) != row["amount_kgs"]:
        problems.append(f"сумма {amount}, в Postgres {row['amount_kgs']}")
    if int(suspicious) != row["suspicious_operations"]:
        problems.append(f"подозрительных {suspicious}, в Postgres {row['suspicious_operations']}")
    if problems:
        raise ValueError("Расхождение Postgres и ClickHouse: " + "; ".join(problems))
    return {"partition": partition, "operations": row["operations"], "amount_kgs": str(row["amount_kgs"])}


def load_day(get_connection, client, ds, run_id, attempt):
    log_id = repository.log_start(get_connection, "ch_dm_transactions_daily", ds, "clickhouse", run_id, attempt)
    try:
        result = copy_day(get_connection, client, ds)
    except Exception as error:
        repository.log_finish(get_connection, log_id, "failed", 0, f"{error}\n{traceback.format_exc()}"[:2000])
        raise
    repository.log_finish(get_connection, log_id, "success", 1, None)
    LOG.info("ClickHouse: за %s загружена 1 строка, операций %s", ds, result["operations"])
    return result
