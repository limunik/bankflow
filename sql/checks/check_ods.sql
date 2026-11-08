-- Проверка слоя ods за одну дату.
-- Запуск: docker compose exec dwh sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -v ds=2026-10-05 -f /sql/checks/check_ods.sql'
\pset border 2
\pset null '(пусто)'

\echo
\echo '=== 1. Баланс строк за дату: из stg в ods ничего не потерялось ==='
SELECT s.stg_rows,
       s.stg_rows - s.distinct_ids                      AS duplicates,
       r.rejected,
       o.in_ods,
       CASE WHEN s.stg_rows = (s.stg_rows - s.distinct_ids) + r.rejected + o.in_ods
            THEN 'OK' ELSE 'РАСХОЖДЕНИЕ' END            AS balance
FROM (SELECT count(*) AS stg_rows, count(DISTINCT btrim(transaction_id)) AS distinct_ids
        FROM stg.stg_transactions WHERE _ds = :'ds') s,
     (SELECT count(*) AS rejected FROM ods.ods_reject WHERE source = 'transactions' AND ds = :'ds') r,
     (SELECT count(*) AS in_ods FROM ods.ods_transactions WHERE ds = :'ds') o;

\echo
\echo '=== 2. Что отбраковано и почему (за дату) ==='
SELECT reason, count(*) AS rows FROM ods.ods_reject
WHERE source = 'transactions' AND ds = :'ds' GROUP BY 1 ORDER BY 2 DESC;

\echo
\echo '=== 3. Примеры отбракованных строк ==='
SELECT reason, record_key, raw->>'amount' AS amount, raw->>'merchant_id' AS merchant_id,
       raw->>'recipient_account_id' AS recipient
FROM ods.ods_reject WHERE source = 'transactions' AND ds = :'ds' ORDER BY id LIMIT 5;

\echo
\echo '=== 4. Ключ уникален: строк и разных transaction_id поровну ==='
SELECT count(*) AS rows, count(DISTINCT transaction_id) AS distinct_keys
FROM ods.ods_transactions WHERE ds = :'ds';

\echo
\echo '=== 5. Согласованность: счёт операции совпадает со счётом её карты (ожидаем 0) ==='
SELECT count(*) AS mismatched
FROM ods.ods_transactions t JOIN ods.ods_cards c USING (card_id)
WHERE t.ds = :'ds' AND t.account_id <> c.account_id;

\echo
\echo '=== 6. Типы колонок ods_transactions ==='
SELECT column_name, data_type, is_nullable
FROM information_schema.columns
WHERE table_schema = 'ods' AND table_name = 'ods_transactions' ORDER BY ordinal_position;

\echo
\echo '=== 7. Суммы и время за дату по валютам и типам ==='
SELECT currency, transaction_type, count(*) AS rows, min(amount) AS min_amount, max(amount) AS max_amount,
       min(transaction_ts)::time AS first_ts, max(transaction_ts)::time AS last_ts
FROM ods.ods_transactions WHERE ds = :'ds' GROUP BY 1, 2 ORDER BY 1, 2;

\echo
\echo '=== 8. Строк во всех таблицах ods ==='
SELECT 'ods_customers' AS table_name, count(*) AS rows FROM ods.ods_customers
UNION ALL SELECT 'ods_merchants', count(*) FROM ods.ods_merchants
UNION ALL SELECT 'ods_cards', count(*) FROM ods.ods_cards
UNION ALL SELECT 'ods_transactions', count(*) FROM ods.ods_transactions
UNION ALL SELECT 'ods_reject', count(*) FROM ods.ods_reject;
