\pset border 2
\echo
\echo '=== 1. Дневная витрина за дату ==='
SELECT * FROM datamart.dm_transactions_daily WHERE ds = :'ds';

\echo
\echo '=== 2. Месячная витрина: топ категорий месяца ==='
SELECT * FROM datamart.dm_category_monthly WHERE month_start = date_trunc('month', :'ds'::date)::date
ORDER BY operations DESC LIMIT 5;

\echo
\echo '=== 3. Сверка с Core: операции и сумма за дату ==='
SELECT d.operations AS mart_ops, f.n AS fact_ops, d.amount_kgs AS mart_kgs, f.s AS fact_kgs,
       CASE WHEN d.operations = f.n AND d.amount_kgs = f.s THEN 'OK' ELSE 'РАСХОЖДЕНИЕ' END AS result
FROM datamart.dm_transactions_daily d
JOIN (SELECT ds, count(*) AS n, sum(amount_kgs) AS s FROM dds.dds_fact_transaction WHERE ds = :'ds' GROUP BY ds) f USING (ds);

\echo
\echo '=== 4. Сумма KGS за месяц: Core = дневная витрина = месячная витрина ==='
SELECT (SELECT sum(amount_kgs) FROM dds.dds_fact_transaction WHERE ds >= date_trunc('month', :'ds'::date) AND ds < date_trunc('month', :'ds'::date) + interval '1 month') AS fact_kgs,
       (SELECT sum(amount_kgs) FROM datamart.dm_transactions_daily WHERE ds >= date_trunc('month', :'ds'::date) AND ds < date_trunc('month', :'ds'::date) + interval '1 month') AS daily_kgs,
       (SELECT sum(amount_kgs) FROM datamart.dm_category_monthly WHERE month_start = date_trunc('month', :'ds'::date)::date) AS monthly_kgs;

\echo
\echo '=== 5. Подозрительные операции за дату: правила и баллы ==='
SELECT s.transaction_id, s.total_points, s.decision, s.rules, f.amount_kgs, f.transaction_type
FROM dds.dds_transaction_score s JOIN dds.dds_fact_transaction f USING (transaction_id)
WHERE s.ds = :'ds' ORDER BY s.total_points DESC, s.transaction_id LIMIT 8;
