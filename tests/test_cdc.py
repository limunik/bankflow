import json
import os
import sys

import psycopg2

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cdc"))
import cdc_lib

OFFSET = [0]


def event(op, lsn, status="active", account="TST001", ts_ms=1_700_000_000_000, partition=0, offset=None, balance="100.50"):
    row = {"account_id": account, "customer_id": "C1", "status": status, "balance": balance,
           "limit_amount": "5000.00", "opened_at": 19000, "updated_at": "2026-11-09T10:00:00.123456Z"}
    value = {"before": row if op in ("u", "d") else None, "after": None if op == "d" else row,
             "source": {"lsn": lsn, "ts_ms": ts_ms}, "op": op, "ts_ms": ts_ms + 5}
    if offset is None:
        OFFSET[0] += 1
        offset = OFFSET[0]
    return cdc_lib.parse_message(b"{}", json.dumps(value).encode(), cdc_lib.TOPIC, partition, offset)


def state(cur, account="TST001"):
    cur.execute("SELECT status, is_deleted, deleted_at IS NOT NULL, source_lsn, balance, opened_at FROM ods.ods_accounts WHERE account_id=%s", (account,))
    return cur.fetchone()


conn = psycopg2.connect()
with conn, conn.cursor() as cur:
    cur.execute("DELETE FROM ods.ods_accounts WHERE account_id LIKE 'TST%'")
    cur.execute("DELETE FROM stg.stg_accounts_cdc WHERE account_id LIKE 'TST%'")
    cur.execute("INSERT INTO ods.ods_accounts (account_id, customer_id, status, balance, limit_amount, opened_at, source_lsn, updated_at) VALUES ('TST002','C1','active',1,1,'2026-01-01',0,now())")


def run(events):
    return cdc_lib.process_batch(conn, events)


def get(account="TST001"):
    with conn, conn.cursor() as cur:
        return state(cur, account)


r = run([event("c", 100)]); assert r["accounts"] == 1, r
s = get(); assert s[0] == "active" and not s[1] and s[3] == 100 and str(s[4]) == "100.50", s
print("1 создание ok", s)

r = run([event("u", 110, "blocked")]); s = get(); assert s[0] == "blocked" and s[3] == 110, s
print("2 обновление ok")

dup = event("u", 110, "blocked", offset=OFFSET[0])
r = run([dup]); assert r["stored"] == 0 and r["applied"] == 0, r
print("3 повторная доставка не дублируется ok")

r = run([event("u", 105, "closed")]); s = get(); assert s[0] == "blocked" and s[3] == 110, s
print("4 старое событие не откатывает состояние ok")

r = run([event("u", 150, "active"), event("u", 140, "closed")]); s = get(); assert s[0] == "active" and s[3] == 150, s
print("5 два события в одной пачке в обратном порядке ok")

r = run([event("d", 160)]); s = get(); assert s[1] and s[2] and s[3] == 160, s
print("6 мягкое удаление ok")

r = run([event("c", 170, "active")]); s = get(); assert not s[1] and not s[2] and s[3] == 170, s
print("7 повторное создание после удаления ok")

r = run([event("r", 90, account="TST002", balance="77.00")]); s = get("TST002"); assert s[3] == 90 and str(s[4]) == "77.00", s
print("8 снимок перезаписывает загрузку из файла (lsn 0) ok")

with conn, conn.cursor() as cur:
    cur.execute("SELECT count(*) FROM stg.stg_accounts_cdc WHERE account_id LIKE 'TST%' AND applied_at IS NULL")
    assert cur.fetchone()[0] == 0
    cur.execute("DELETE FROM ods.ods_accounts WHERE account_id LIKE 'TST%'")
    cur.execute("DELETE FROM stg.stg_accounts_cdc WHERE account_id LIKE 'TST%'")
print("все проверки прошли")
