import argparse
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "dags"))
from bankflow_lib import clickhouse_copy


def connect():
    return psycopg2.connect(
        host=os.environ.get("PGHOST", "localhost"),
        port=os.environ.get("PGPORT", "5432"),
        dbname=os.environ.get("PGDATABASE", "dwh"),
        user=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("date_from")
    parser.add_argument("date_to")
    args = parser.parse_args()
    day = date.fromisoformat(args.date_from)
    last = date.fromisoformat(args.date_to)
    client = clickhouse_copy.client_from_env()
    done = 0
    while day <= last:
        result = clickhouse_copy.copy_day(connect, client, day.isoformat())
        done += 1
        print(day.isoformat(), result["operations"], result["amount_kgs"])
        day += timedelta(days=1)
    print("дней загружено", done)


if __name__ == "__main__":
    main()
