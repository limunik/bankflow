\pset border 2
\pset null '(пусто)'

\echo
\echo '=== 1. Строк в таблицах Core ==='
SELECT 'dds_dim_date' AS table_name, count(*) AS rows FROM dds.dds_dim_date
UNION ALL SELECT 'dds_dim_customer', count(*) FROM dds.dds_dim_customer
UNION ALL SELECT 'dds_dim_merchant', count(*) FROM dds.dds_dim_merchant
UNION ALL SELECT 'dds_dim_card', count(*) FROM dds.dds_dim_card
UNION ALL SELECT 'dds_dim_account', count(*) FROM dds.dds_dim_account
UNION ALL SELECT 'dds_fact_transaction', count(*) FROM dds.dds_fact_transaction;

\echo
\echo '=== 2. Путь одной операции: ods -> Core (за дату) ==='
SELECT o.transaction_id, o.customer_id, o.card_id, o.merchant_id, o.amount, o.currency,
       f.customer_sk, f.card_sk, f.merchant_sk, f.fx_rate, f.amount_kgs
FROM ods.ods_transactions o
JOIN dds.dds_fact_transaction f USING (transaction_id)
WHERE o.ds = :'ds' AND o.currency <> 'KGS'
ORDER BY o.transaction_id LIMIT 3;

\echo
\echo '=== 3. Строк за дату: ods и Core поровну ==='
SELECT (SELECT count(*) FROM ods.ods_transactions WHERE ds = :'ds') AS ods_rows,
       (SELECT count(*) FROM dds.dds_fact_transaction WHERE ds = :'ds') AS fact_rows;

\echo
\echo '=== 4. Суммы по валютам: исходная и в сомах ==='
SELECT currency, count(*) AS operations, sum(amount) AS amount, max(fx_rate) AS fx_rate, sum(amount_kgs) AS amount_kgs
FROM dds.dds_fact_transaction WHERE ds = :'ds' GROUP BY currency ORDER BY currency;

\echo
\echo '=== 5. SCD2: клиенты с несколькими версиями ==='
SELECT customer_id, customer_name, customer_type, valid_from, valid_to, is_current
FROM dds.dds_dim_customer
WHERE customer_id IN (SELECT customer_id FROM dds.dds_dim_customer GROUP BY customer_id HAVING count(*) > 1)
ORDER BY customer_id, valid_from LIMIT 10;

\echo
\echo '=== 6. SCD1: мерчанты хранят только текущее значение ==='
SELECT merchant_id, merchant_name, category, country FROM dds.dds_dim_merchant ORDER BY merchant_id LIMIT 3;

\echo
\echo '=== 7. Результат последних проверок качества за дату ==='
SELECT layer, status, count(*) AS checks FROM dq.last_run WHERE ds = :'ds' GROUP BY 1, 2 ORDER BY 1, 2;

\echo
\echo '=== 8. Журнал загрузок по слоям за дату ==='
SELECT layer, status, count(*) AS runs, sum(rows_loaded) AS rows_loaded
FROM stg.etl_load_log WHERE ds = :'ds' GROUP BY 1, 2 ORDER BY 1, 2;
