-- BankFlow: показ боевой базы oltp (таблица счетов, источник CDC).
-- Запуск: docker compose exec oltp sh -c 'psql -U $POSTGRES_USER -d $POSTGRES_DB -f /sql/checks/showcase_oltp.sql'
\pset border 2

\echo
\echo '=== 1. Таблица bank.accounts: счета по статусам ==='
SELECT status, count(*) AS accounts, round(100.0 * count(*) / sum(count(*)) OVER (), 1) AS percent
FROM bank.accounts GROUP BY 1 ORDER BY 2 DESC;

\echo
\echo '=== 2. Пример строк ==='
SELECT account_id, customer_id, status, balance, limit_amount, opened_at, updated_at::timestamp(0) AS updated_at
FROM bank.accounts ORDER BY account_id LIMIT 5;

\echo
\echo '=== 3. Настройки для CDC (логическая репликация) ==='
SHOW wal_level;
SELECT relname AS table_name,
       CASE relreplident WHEN 'f' THEN 'FULL (полная старая строка в событии)' ELSE relreplident::text END AS replica_identity
FROM pg_class WHERE relname = 'accounts';
