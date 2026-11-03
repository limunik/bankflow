-- BankFlow: показ хранилища dwh (таблицы, объём, примеры данных, качество).
-- Запуск: docker compose exec dwh sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -f /sql/checks/showcase_dwh.sql'
\pset border 2
\pset null '(пусто)'

\echo
\echo '=== 1. Схемы и таблицы хранилища ==='
SELECT table_schema AS schema, table_name AS table
FROM information_schema.tables
WHERE table_schema IN ('stg', 'ods', 'dds', 'datamart')
ORDER BY 1, 2;

\echo
\echo '=== 2. Сколько строк в таблицах слоя stg ==='
SELECT 'stg_transactions' AS table_name, count(*) AS row_count FROM stg.stg_transactions
UNION ALL SELECT 'stg_merchants', count(*) FROM stg.stg_merchants
UNION ALL SELECT 'stg_cards',     count(*) FROM stg.stg_cards
UNION ALL SELECT 'stg_customers', count(*) FROM stg.stg_customers
UNION ALL SELECT 'stg_fx_rates',  count(*) FROM stg.stg_fx_rates
UNION ALL SELECT 'etl_load_log',  count(*) FROM stg.etl_load_log;

\echo
\echo '=== 3. Период и объём операций ==='
SELECT min(_ds) AS first_day, max(_ds) AS last_day,
       count(DISTINCT _ds) AS days, count(*) AS operations,
       round(count(*)::numeric / count(DISTINCT _ds)) AS avg_per_day
FROM stg.stg_transactions;

\echo
\echo '=== 4. Размер таблиц на диске ==='
SELECT c.relname AS table_name, pg_size_pretty(pg_total_relation_size(c.oid)) AS total_size
FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'stg' AND c.relkind = 'r'
ORDER BY pg_total_relation_size(c.oid) DESC;

\echo
\echo '=== 5. Пример: операции (stg_transactions) ==='
SELECT transaction_id, transaction_type, card_id, merchant_id, recipient_account_id, transaction_ts, amount, currency, payment_method
FROM stg.stg_transactions WHERE _ds = (SELECT max(_ds) FROM stg.stg_transactions)
ORDER BY transaction_id LIMIT 5;

\echo
\echo '=== 5а. Пример: переводы между счетами ==='
SELECT transaction_id, account_id AS from_account, recipient_account_id AS to_account, transaction_ts, amount, currency
FROM stg.stg_transactions WHERE transaction_type = 'TRANSFER' AND _ds = (SELECT max(_ds) FROM stg.stg_transactions)
ORDER BY transaction_id LIMIT 5;

\echo
\echo '=== 5б. Клиенты: физические и юридические лица (stg_customers) ==='
SELECT customer_type, count(*) AS customers FROM stg.stg_customers GROUP BY 1 ORDER BY 2 DESC;
SELECT customer_id, customer_name, customer_type FROM stg.stg_customers ORDER BY customer_id LIMIT 5;

\echo
\echo '=== 5в. Покупки и переводы ==='
SELECT transaction_type, count(*) AS operations, round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS percent
FROM stg.stg_transactions GROUP BY 1 ORDER BY 2 DESC;

\echo
\echo '=== 6. Пример: карты (stg_cards) ==='
SELECT card_id, account_id, customer_id, card_scheme FROM stg.stg_cards ORDER BY card_id LIMIT 5;

\echo
\echo '=== 7. Пример: мерчанты (stg_merchants) ==='
SELECT merchant_id, merchant_name, category, country FROM stg.stg_merchants ORDER BY merchant_id LIMIT 5;

\echo
\echo '=== 8. Пример: курсы валют (stg_fx_rates) ==='
SELECT rate_date, currency, rate FROM stg.stg_fx_rates ORDER BY rate_date DESC, currency LIMIT 6;

\echo
\echo '=== 9. Служебные колонки слоя stg (ФТ-3) ==='
SELECT _ds, _source, _loaded_at::timestamp(0) AS loaded_at, is_active, is_deleted
FROM stg.stg_transactions WHERE _ds = (SELECT max(_ds) FROM stg.stg_transactions) LIMIT 3;

\echo
\echo '=== 10. «Грязные» данные как они пришли (за последний день) ==='
SELECT count(*) AS total_rows,
       count(*) - count(DISTINCT transaction_id) AS duplicates,
       count(*) FILTER (WHERE amount IS NULL)      AS empty_amount,
       count(*) FILTER (WHERE merchant_id IS NULL AND transaction_type = 'PURCHASE') AS empty_merchant_in_purchase,
       count(*) FILTER (WHERE recipient_account_id IS NULL AND transaction_type = 'TRANSFER') AS empty_recipient_in_transfer
FROM stg.stg_transactions WHERE _ds = (SELECT max(_ds) FROM stg.stg_transactions);

\echo
\echo '=== 11. Дни с наибольшим числом операций (зарплаты 5-го и 20-го) ==='
SELECT _ds AS day, count(*) AS operations FROM stg.stg_transactions
GROUP BY 1 ORDER BY 2 DESC LIMIT 6;

\echo
\echo '=== 12. Операции по часам суток (вечерний пик, мало ночных) ==='
SELECT substr(transaction_ts, 12, 2) AS hour, count(*) AS operations
FROM stg.stg_transactions GROUP BY 1 ORDER BY 1;

\echo
\echo '=== 13. Способы оплаты и платёжные системы карт ==='
SELECT payment_method, count(*) AS operations,
       round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS percent
FROM stg.stg_transactions GROUP BY 1 ORDER BY 2 DESC;
SELECT card_scheme, count(*) AS cards FROM stg.stg_cards GROUP BY 1 ORDER BY 2 DESC;

\echo
\echo '=== 14. Журнал загрузок etl_load_log (ФТ-6) ==='
SELECT source, status, count(*) AS runs, sum(rows_loaded) AS rows_loaded
FROM stg.etl_load_log GROUP BY 1, 2 ORDER BY 1, 2;
SELECT id, source, ds, status, rows_loaded, error_message
FROM stg.etl_load_log WHERE status = 'failed' ORDER BY id DESC LIMIT 3;
