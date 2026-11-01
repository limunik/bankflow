"""Генератор таблицы accounts в oltp: начальная выгрузка и живой поток изменений (источник CDC).

Команды (из корня проекта):
    docker compose run --rm stream python stream_accounts.py init
        Один раз: очищает таблицу и загружает все счета (статусы те же, что в данных операций).
    docker compose run --rm stream python stream_accounts.py run --rate 5 --duration 60
        Поток изменений: ~5 событий в секунду в течение 60 секунд (--duration 0 = пока не остановишь).
    docker compose run --rm stream python stream_accounts.py set-status --account AC000001 --status blocked
        Одно точечное изменение статуса (для демо на защите).

Подключение берётся из переменных окружения PGHOST, PGPORT, PGDATABASE, PGUSER, PGPASSWORD
(их задаёт docker-compose из файла .env): пароля в коде нет.

Виды событий потока и их доли:
    обновление баланса 65%, смена статуса 12%, смена лимита 8%, новый счёт 10%, удаление закрытого счёта 5%.
"""
import argparse
import random
import time
from collections import Counter
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import execute_values

import config
from pool import build_accounts, build_card_pool

TABLE = "bank.accounts"
EVENT_WEIGHTS = {"balance": 65, "status": 12, "limit": 8, "insert": 10, "delete": 5}


def connect():
    """Соединение с oltp. autocommit: каждое изменение фиксируется сразу (так выглядит боевая база)."""
    conn = psycopg2.connect()
    conn.autocommit = True
    return conn


def cmd_init(_args):
    """Начальная выгрузка: все счета из пула (около 30 тысяч строк)."""
    accounts = build_accounts(build_card_pool())
    rows = [(a["account_id"], a["customer_id"], a["status"], a["balance"],
             a["limit_amount"], a["opened_at"], a["updated_at"]) for a in accounts]
    conn = connect()
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {TABLE}")
        execute_values(
            cur,
            f"INSERT INTO {TABLE} (account_id, customer_id, status, balance, limit_amount, "
            f"opened_at, updated_at) VALUES %s",
            rows, page_size=5000,
        )
        cur.execute(f"SELECT status, count(*) FROM {TABLE} GROUP BY 1 ORDER BY 1")
        print(f"Загружено счетов: {len(rows)}; по статусам: {dict(cur.fetchall())}")
    conn.close()


def one_event(cur, rng, ids, state):
    """Выполняет одно случайное изменение. Возвращает название события или None, если не вышло.

    Все UPDATE и DELETE условные (WHERE status = ...): они безопасны, даже если строка
    успела измениться или исчезнуть, поэтому программе не нужно помнить состояние базы.
    """
    kind = rng.choices(list(EVENT_WEIGHTS), list(EVENT_WEIGHTS.values()))[0]

    if kind == "balance":
        delta = round(rng.gauss(0, 3000), 2)
        cur.execute(
            f"UPDATE {TABLE} SET balance = GREATEST(balance + %s, 0), updated_at = now() "
            f"WHERE account_id = %s AND status = 'active'", (delta, rng.choice(ids)))

    elif kind == "status":
        acc = rng.choice(ids)
        # active -> blocked (80%) или closed (20%); blocked -> active (70%) или closed (30%)
        if rng.random() < 0.6:
            new = "blocked" if rng.random() < 0.8 else "closed"
            cur.execute(f"UPDATE {TABLE} SET status = %s, updated_at = now() "
                        f"WHERE account_id = %s AND status = 'active'", (new, acc))
        else:
            new = "active" if rng.random() < 0.7 else "closed"
            cur.execute(f"UPDATE {TABLE} SET status = %s, updated_at = now() "
                        f"WHERE account_id = %s AND status = 'blocked'", (new, acc))

    elif kind == "limit":
        cur.execute(f"UPDATE {TABLE} SET limit_amount = %s, updated_at = now() "
                    f"WHERE account_id = %s AND status = 'active'",
                    (rng.choice([50000, 100000, 200000, 500000]), rng.choice(ids)))

    elif kind == "insert":
        state["next_id"] += 1
        new_id = f"AC{state['next_id']:06d}"
        limit_amount = rng.choice([50000, 100000, 200000, 500000])
        cur.execute(
            f"INSERT INTO {TABLE} (account_id, customer_id, status, balance, limit_amount, "
            f"opened_at, updated_at) VALUES (%s, %s, 'active', %s, %s, current_date, now())",
            (new_id, f"CL{rng.randint(1, config.N_CUSTOMERS):05d}",
             round(limit_amount * rng.uniform(0.01, 0.3), 2), limit_amount))
        ids.append(new_id)

    elif kind == "delete":
        # Удаляем только закрытые счета: так бывает в жизни. В ods это станет мягким удалением.
        cur.execute(f"DELETE FROM {TABLE} WHERE account_id = ("
                    f"SELECT account_id FROM {TABLE} WHERE status = 'closed' "
                    f"ORDER BY random() LIMIT 1)")

    return kind if cur.rowcount > 0 else None


def cmd_run(args):
    """Поток изменений с заданной скоростью."""
    rng = random.Random()    # здесь seed не нужен: поток «живой», каждый запуск разный
    conn = connect()
    with conn.cursor() as cur:
        cur.execute(f"SELECT account_id FROM {TABLE}")
        ids = [r[0] for r in cur.fetchall()]
        if not ids:
            raise SystemExit("Таблица пуста. Сначала выполните: stream_accounts.py init")
        cur.execute(f"SELECT max(substr(account_id, 3)::int) FROM {TABLE}")
        state = {"next_id": cur.fetchone()[0]}

        stats = Counter()
        started = last_print = time.time()
        print(f"Поток запущен: {args.rate} событий в секунду, "
              f"{'без ограничения по времени' if args.duration == 0 else f'{args.duration} с'}. "
              f"Остановить: Ctrl+C")
        try:
            while args.duration == 0 or time.time() - started < args.duration:
                kind = one_event(cur, rng, ids, state)
                if kind:
                    stats[kind] += 1
                time.sleep(1.0 / args.rate)
                if time.time() - last_print >= 10:
                    print(f"{datetime.now():%H:%M:%S} | событий: {sum(stats.values())} | {dict(stats)}")
                    last_print = time.time()
        except KeyboardInterrupt:
            pass
        print(f"Остановлено. Итого событий: {sum(stats.values())} | {dict(stats)}")
    conn.close()


def cmd_set_status(args):
    """Точечная смена статуса одного счёта (демо: показать, как изменение доходит до хранилища)."""
    conn = connect()
    with conn.cursor() as cur:
        cur.execute(f"SELECT status FROM {TABLE} WHERE account_id = %s", (args.account,))
        before = cur.fetchone()
        if not before:
            raise SystemExit(f"Счёт {args.account} не найден")
        cur.execute(f"UPDATE {TABLE} SET status = %s, updated_at = now() WHERE account_id = %s",
                    (args.status, args.account))
        print(f"{args.account}: {before[0]} -> {args.status} в {datetime.now(timezone.utc):%H:%M:%S} UTC")
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Генератор таблицы accounts (источник CDC)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="начальная выгрузка всех счетов")

    run = sub.add_parser("run", help="поток INSERT, UPDATE, DELETE")
    run.add_argument("--rate", type=float, default=5, help="событий в секунду")
    run.add_argument("--duration", type=int, default=60, help="секунд (0 = бесконечно)")

    st = sub.add_parser("set-status", help="сменить статус одного счёта")
    st.add_argument("--account", required=True)
    st.add_argument("--status", required=True, choices=["active", "blocked", "closed"])

    args = parser.parse_args()
    {"init": cmd_init, "run": cmd_run, "set-status": cmd_set_status}[args.cmd](args)


if __name__ == "__main__":
    main()
