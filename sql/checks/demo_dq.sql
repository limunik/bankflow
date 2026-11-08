\pset border 2
\echo
\echo '=== 1. До порчи: все проверки за дату проходят ==='
SELECT status, count(*) AS checks FROM dq.run_checks(:'ds') GROUP BY status;

BEGIN;
\echo
\echo '=== 2. Портим Core в транзакции: дубль ключа, потерянная строка, неверная сумма в сомах ==='
ALTER TABLE dds.dds_fact_transaction DROP CONSTRAINT dds_fact_transaction_pkey;
INSERT INTO dds.dds_fact_transaction
SELECT * FROM dds.dds_fact_transaction
WHERE transaction_id = (SELECT min(transaction_id) FROM dds.dds_fact_transaction WHERE ds = :'ds');
DELETE FROM dds.dds_fact_transaction
WHERE transaction_id = (SELECT max(transaction_id) FROM dds.dds_fact_transaction WHERE ds = :'ds');
UPDATE dds.dds_fact_transaction SET amount_kgs = amount_kgs + 1
WHERE transaction_id = (SELECT min(transaction_id) FROM dds.dds_fact_transaction WHERE ds = :'ds' AND currency = 'USD');

\echo
\echo '=== 3. Проверки находят ошибки и называют причину ==='
SELECT check_name, severity, failed_rows, details FROM dq.run_checks(:'ds') WHERE status = 'failed';
ROLLBACK;

\echo
\echo '=== 4. После отката (исправления) все проверки снова проходят ==='
SELECT status, count(*) AS checks FROM dq.run_checks(:'ds') GROUP BY status;
