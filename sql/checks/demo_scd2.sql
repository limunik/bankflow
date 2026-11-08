\pset border 2
BEGIN;
\echo
\echo '=== 1. Клиент C1 до изменения ==='
SELECT customer_id, customer_name, customer_type, valid_from, valid_to, is_current
FROM dds.dds_dim_customer WHERE customer_id = 'C1' ORDER BY valid_from;

\echo
\echo '=== 2. Меняем имя клиента в источнике и прогоняем ods и Core ==='
UPDATE stg.stg_customers SET customer_name = 'Новое имя' WHERE customer_id = 'C1';
SELECT * FROM ods.load_customers(:'ds');
SELECT * FROM dds.load_dim_customer(:'ds');

\echo
\echo '=== 3. SCD2: старая версия закрыта, новая действует ==='
SELECT customer_id, customer_name, customer_type, valid_from, valid_to, is_current
FROM dds.dds_dim_customer WHERE customer_id = 'C1' ORDER BY valid_from;

\echo
\echo '=== 4. Повтор того же дня ничего не меняет ==='
SELECT * FROM dds.load_dim_customer(:'ds');
ROLLBACK;
