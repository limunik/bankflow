import csv
import os
import sys
from pathlib import Path

import psycopg2

COLUMNS = ["transaction_id", "is_fraud", "scenario", "scenario_id", "scenario_start_ts"]


def main():
    data_dir = Path(os.environ.get("DATA_DIR", "/data")) / "ground_truth"
    files = sorted(data_dir.glob("ground_truth_*.csv"))
    if not files:
        sys.exit(f"Нет файлов ground_truth_*.csv в {data_dir}")
    for file in files:
        with open(file, newline="", encoding="utf-8") as handle:
            header = next(csv.reader(handle))
        if header != COLUMNS:
            sys.exit(f"Заголовок {file.name} не совпадает: {header}")

    connection = psycopg2.connect()
    try:
        with connection, connection.cursor() as cursor:
            cursor.execute("TRUNCATE eval.ground_truth")
            cursor.execute("CREATE TEMP TABLE tmp_gt (LIKE eval.ground_truth) ON COMMIT DROP")
            for file in files:
                with open(file, encoding="utf-8", newline="") as handle:
                    cursor.copy_expert(
                        f"COPY tmp_gt ({', '.join(COLUMNS)}) FROM STDIN WITH (FORMAT csv, HEADER true)", handle)
            cursor.execute(
                "INSERT INTO eval.ground_truth SELECT DISTINCT ON (transaction_id) * FROM tmp_gt "
                "ORDER BY transaction_id")
            loaded = cursor.rowcount
            cursor.execute("SELECT count(*) FILTER (WHERE is_fraud = 1) FROM eval.ground_truth")
            fraud = cursor.fetchone()[0]
        print(f"ground_truth: файлов {len(files)}, строк {loaded}, из них фрод {fraud}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
