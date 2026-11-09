import json
from datetime import datetime, timezone

import psycopg2.extras

TOPIC = "bankflow.bank.accounts"


def parse_message(key, value, topic, partition, offset):
    if value is None:
        return None
    event = json.loads(value)
    payload = event.get("payload", event)
    op = payload.get("op")
    if op not in ("c", "u", "d", "r"):
        return None
    row = payload["before"] if op == "d" else payload["after"]
    source = payload["source"]
    return {
        "topic": topic,
        "kafka_partition": partition,
        "kafka_offset": offset,
        "account_id": row["account_id"],
        "op": op,
        "source_lsn": int(source["lsn"]),
        "source_ts": datetime.fromtimestamp(int(source["ts_ms"]) / 1000, tz=timezone.utc),
        "payload": json.dumps(payload),
    }


def store_events(cursor, events):
    if not events:
        return 0
    psycopg2.extras.execute_values(
        cursor,
        "INSERT INTO stg.stg_accounts_cdc "
        "(topic, kafka_partition, kafka_offset, account_id, op, source_lsn, source_ts, payload) "
        "VALUES %s ON CONFLICT (topic, kafka_partition, kafka_offset) DO NOTHING",
        [(e["topic"], e["kafka_partition"], e["kafka_offset"], e["account_id"], e["op"],
          e["source_lsn"], e["source_ts"], e["payload"]) for e in events],
    )
    return cursor.rowcount


def apply_events(cursor):
    cursor.execute("SELECT events, accounts, soft_deleted FROM ods.apply_accounts_cdc()")
    return cursor.fetchone()


def process_batch(connection, events):
    with connection:
        with connection.cursor() as cursor:
            stored = store_events(cursor, events)
            events_applied, accounts, deleted = apply_events(cursor)
    return {"stored": stored, "applied": events_applied, "accounts": accounts, "deleted": deleted}
