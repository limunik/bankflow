"""Загрузчик CSV в слой stg хранилища BankFlow.

Что делает:
    1. Находит файл источника за дату ds.
    2. В ОДНОЙ транзакции удаляет из stg строки за эту дату и вставляет файл заново.
    3. Пишет результат в журнал stg.etl_load_log (успех или ошибка).

Запуск (из корня проекта):
    docker compose run --rm etl python load_stg.py --ds 2026-10-01
    docker compose run --rm etl python load_stg.py --ds 2026-10-01 --days 10
    docker compose run --rm etl python load_stg.py --ds 2026-10-01 --sources transactions
"""
import argparse             # разбор параметров командной строки
import csv                  # чтобы прочитать заголовок файла
import os                   # переменные окружения
import sys                  # sys.exit: код завершения программы
from datetime import date, timedelta
from pathlib import Path

import psycopg2             # драйвер Postgres

# Куда смонтирована папка с данными (см. docker-compose.yml)
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))

# ---------------------------------------------------------------------------
# Описание источников.
# mode:
#   "by_ds" событие с датой: удаляем и вставляем только строки за эту дату
#   "full"  справочник: заменяем таблицу целиком (так сказано в ТЗ, ФТ-2)
# path: функция, которая по дате возвращает путь к файлу.
# columns: колонки файла В ТОМ ЖЕ ПОРЯДКЕ, что в заголовке CSV.
# ---------------------------------------------------------------------------
SOURCES = {
    "transactions": {
        "table": "stg.stg_transactions",
        "mode": "by_ds",
        "path": lambda ds: DATA_DIR / "transactions" / f"transactions_{ds.isoformat()}.csv",
        "columns": [
            "transaction_id", "card_id", "account_id", "customer_id",
            "merchant_id", "transaction_ts", "amount", "currency", "channel",
            "payment_method",
        ],
    },
    "merchants": {
        "table": "stg.stg_merchants",
        "mode": "full",
        "path": lambda ds: DATA_DIR / "merchants" / "merchants.csv",
        "columns": ["merchant_id", "merchant_name", "category", "country"],
    },
    "cards": {
        "table": "stg.stg_cards",
        "mode": "full",
        "path": lambda ds: DATA_DIR / "cards" / "cards.csv",
        "columns": ["card_id", "account_id", "customer_id", "card_scheme"],
    },
}


def connect():
    """Открывает соединение с базой dwh.

    Параметры не указаны в коде: psycopg2 сам берёт их из переменных окружения
    PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD, которые docker-compose
    заполняет из файла .env. Так пароль не попадает в код (НФТ-2).
    """
    return psycopg2.connect()


def log_start(source, ds):
    """Добавляет в журнал строку «running» и возвращает её id.

    Отдельное соединение с autocommit: запись попадает в журнал СРАЗУ и не
    откатывается, даже если основная загрузка упадёт и откатит свою транзакцию.
    """
    conn = connect()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO stg.etl_load_log (source, ds, started_at, status) "
                "VALUES (%s, %s, now(), 'running') RETURNING id",
                (source, ds),
            )
            return cur.fetchone()[0]
    finally:
        conn.close()


def log_finish(log_id, status, rows, error):
    """Дописывает в журнал итог: статус, число строк, время конца, текст ошибки."""
    conn = connect()
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE stg.etl_load_log "
                "SET finished_at = now(), status = %s, rows_loaded = %s, error_message = %s "
                "WHERE id = %s",
                (status, rows, error, log_id),
            )
    finally:
        conn.close()


def read_header(path):
    """Возвращает названия колонок из первой строки CSV."""
    with open(path, newline="", encoding="utf-8") as f:
        return next(csv.reader(f))


def copy_file(cfg, path, ds):
    """Загружает файл в stg и возвращает число загруженных строк."""
    columns = cfg["columns"]

    # Проверяем заголовок ДО обращения к базе: если файл не тот, данные не трогаем
    header = read_header(path)
    if header != columns:
        raise ValueError(f"Заголовок файла {path.name} не совпадает с ожидаемым: {header}")

    col_list = ", ".join(columns)                       # "a, b, c"
    col_defs = ", ".join(f"{c} text" for c in columns)  # "a text, b text, c text"

    conn = connect()
    try:
        # "with conn": без ошибок транзакция фиксируется (commit), при ошибке
        # откатывается (rollback). Это и есть «всё или ничего».
        with conn:
            with conn.cursor() as cur:
                # 1. Удаляем старое. Именно это делает загрузку идемпотентной.
                if cfg["mode"] == "by_ds":
                    cur.execute(f"DELETE FROM {cfg['table']} WHERE _ds = %s", (ds,))
                else:
                    cur.execute(f"DELETE FROM {cfg['table']}")

                # 2. Временная таблица, исчезает сама при завершении транзакции
                cur.execute(f"CREATE TEMP TABLE tmp_load ({col_defs}) ON COMMIT DROP")

                # 3. COPY: быстрая загрузка файла. HEADER true пропускает первую строку.
                with open(path, encoding="utf-8", newline="") as f:
                    cur.copy_expert(
                        f"COPY tmp_load ({col_list}) FROM STDIN WITH (FORMAT csv, HEADER true)",
                        f,
                    )

                # 4. Переносим в stg и добавляем служебные колонки
                #    (_loaded_at заполняется сам: DEFAULT now() в DDL)
                cur.execute(
                    f"INSERT INTO {cfg['table']} ({col_list}, _ds, _source_file) "
                    f"SELECT {col_list}, %s, %s FROM tmp_load",
                    (ds, path.name),
                )
                return cur.rowcount   # сколько строк вставлено
    finally:
        conn.close()


def load_source(source, ds):
    """Одна загрузка: источник + дата. Пишет журнал и возвращает число строк."""
    cfg = SOURCES[source]
    path = cfg["path"](ds)

    log_id = log_start(source, ds)
    try:
        if not path.exists():
            raise FileNotFoundError(f"Файл не найден: {path}")
        rows = copy_file(cfg, path, ds)
        log_finish(log_id, "success", rows, None)
        return rows
    except Exception as exc:
        # Ограничиваем длину текста ошибки, чтобы не раздувать журнал
        log_finish(log_id, "failed", 0, str(exc)[:2000])
        raise   # передаём ошибку выше: main() её покажет


def main():
    parser = argparse.ArgumentParser(description="Загрузка CSV в stg")
    parser.add_argument("--ds", required=True, help="дата загрузки, YYYY-MM-DD")
    parser.add_argument("--days", type=int, default=1, help="сколько дат подряд")
    parser.add_argument("--sources", default="merchants,cards,transactions",
                        help="через запятую: merchants, cards, transactions")
    args = parser.parse_args()

    start = date.fromisoformat(args.ds)
    sources = [s.strip() for s in args.sources.split(",")]
    for s in sources:
        if s not in SOURCES:
            parser.error(f"неизвестный источник: {s}")

    failed = False
    for k in range(args.days):
        d = start + timedelta(days=k)
        for source in sources:
            try:
                rows = load_source(source, d)
                print(f"[{d}] {source}: OK, {rows} строк")
            except Exception as exc:
                print(f"[{d}] {source}: ОШИБКА: {exc}")
                failed = True

    # Код 1 значит «были ошибки». Airflow позже по нему поймёт, что задача упала.
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()