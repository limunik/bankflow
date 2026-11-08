\pset border 2
\pset null '(пусто)'

\echo
\echo '=== 0. Период оценки и объём эталона ==='
SELECT :'from'::date AS from_date, :'to'::date AS to_date,
       (SELECT count(*) FROM dds.dds_fact_transaction WHERE ds BETWEEN :'from' AND :'to') AS operations,
       (SELECT count(*) FROM dds.dds_fact_transaction f JOIN eval.ground_truth g USING (transaction_id)
        WHERE f.ds BETWEEN :'from' AND :'to' AND g.is_fraud = 1) AS fraud_operations;

\echo
\echo '=== 1. Качество каждого правила (H1: у какого правила больше всего ложных срабатываний) ==='
SELECT * FROM eval.rule_metrics(:'from', :'to') ORDER BY fp DESC;

\echo
\echo '=== 1а. Правило «две страны» в наивном виде (любой канал) для сравнения ==='
WITH naive AS (
    SELECT t.transaction_id
    FROM dds.dds_fact_transaction t
    JOIN dds.dds_dim_merchant mt ON mt.merchant_sk = t.merchant_sk
    WHERE t.ds BETWEEN :'from' AND :'to' AND EXISTS (
        SELECT 1 FROM dds.dds_fact_transaction p
        JOIN dds.dds_dim_merchant mp ON mp.merchant_sk = p.merchant_sk
        WHERE p.card_sk = t.card_sk AND p.transaction_ts < t.transaction_ts
          AND p.transaction_ts > t.transaction_ts - interval '1 hour' AND mp.country <> mt.country)
)
SELECT count(*) AS flagged,
       count(*) FILTER (WHERE g.is_fraud = 1) AS tp,
       count(*) FILTER (WHERE coalesce(g.is_fraud, 0) = 0) AS fp,
       round(100.0 * count(*) FILTER (WHERE g.is_fraud = 1) / count(*), 1) AS precision_pct
FROM naive n LEFT JOIN eval.ground_truth g USING (transaction_id);

\echo
\echo '=== 2. Правило «аномальная сумма»: зарплатные дни и обычные (H2) ==='
SELECT * FROM eval.payday_metrics(:'from', :'to', 'anomalous_amount');

\echo
\echo '=== 3. Пороги баллов: precision, recall, доля задетых карт (H3) ==='
SELECT * FROM eval.threshold_metrics(:'from', :'to');

\echo
\echo '=== 4. Что ловится при пороге 50: по сценариям генератора ==='
SELECT * FROM eval.scenario_metrics(:'from', :'to', 50);

\echo
\echo '=== 5. То же при пороге 40 ==='
SELECT * FROM eval.scenario_metrics(:'from', :'to', 40);

\echo
\echo '=== 6. Решения системы по дням (allow / confirm / suspicious) ==='
SELECT ds, operations, confirm_operations, suspicious_operations, suspicious_share
FROM datamart.dm_transactions_daily WHERE ds BETWEEN :'from' AND :'to' ORDER BY ds DESC LIMIT 7;
