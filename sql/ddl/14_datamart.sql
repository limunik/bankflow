CREATE SCHEMA IF NOT EXISTS datamart;

CREATE TABLE IF NOT EXISTS datamart.dm_transactions_daily (
    ds                  date          PRIMARY KEY,
    operations          integer       NOT NULL,
    purchases           integer       NOT NULL,
    transfers           integer       NOT NULL,
    active_cards        integer       NOT NULL,
    amount_kgs          numeric(18,2) NOT NULL,
    amount_usd          numeric(18,2) NOT NULL,
    confirm_operations  integer       NOT NULL,
    suspicious_operations integer     NOT NULL,
    suspicious_share    numeric(7,4)  NOT NULL CHECK (suspicious_share BETWEEN 0 AND 1),
    _loaded_at          timestamptz   NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS datamart.dm_category_monthly (
    month_start            date          NOT NULL,
    category               text          NOT NULL,
    operations             integer       NOT NULL,
    unique_cards           integer       NOT NULL,
    amount_kgs             numeric(18,2) NOT NULL,
    confirm_operations     integer       NOT NULL,
    suspicious_operations  integer       NOT NULL,
    suspicious_share       numeric(7,4)  NOT NULL CHECK (suspicious_share BETWEEN 0 AND 1),
    _loaded_at             timestamptz   NOT NULL DEFAULT now(),
    PRIMARY KEY (month_start, category)
);

CREATE OR REPLACE FUNCTION datamart.load_dm_transactions_daily(p_ds date)
RETURNS TABLE (src_rows integer, inserted integer, updated integer)
LANGUAGE plpgsql AS $$
DECLARE v_src integer; v_ins integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('datamart.dm_transactions_daily:' || p_ds::text));
    SELECT count(*) INTO v_src FROM dds.dds_fact_transaction WHERE ds = p_ds;
    DELETE FROM datamart.dm_transactions_daily WHERE ds = p_ds;
    INSERT INTO datamart.dm_transactions_daily
           (ds, operations, purchases, transfers, active_cards, amount_kgs, amount_usd,
            confirm_operations, suspicious_operations, suspicious_share)
    SELECT p_ds, count(*),
           count(*) FILTER (WHERE f.transaction_type = 'PURCHASE'),
           count(*) FILTER (WHERE f.transaction_type = 'TRANSFER'),
           count(DISTINCT f.card_sk),
           sum(f.amount_kgs),
           round(sum(f.amount_kgs) / u.rate, 2),
           count(*) FILTER (WHERE s.decision = 'confirm'),
           count(*) FILTER (WHERE s.decision = 'suspicious'),
           round(count(*) FILTER (WHERE s.decision = 'suspicious')::numeric / count(*), 4)
    FROM dds.dds_fact_transaction f
    LEFT JOIN dds.dds_transaction_score s ON s.transaction_id = f.transaction_id
    CROSS JOIN (SELECT rate FROM ods.ods_fx_rates WHERE rate_date = p_ds AND currency = 'USD') u
    WHERE f.ds = p_ds
    GROUP BY u.rate;
    GET DIAGNOSTICS v_ins = ROW_COUNT;
    RETURN QUERY SELECT v_src, v_ins, 0;
END $$;

CREATE OR REPLACE FUNCTION datamart.load_dm_category_monthly(p_ds date)
RETURNS TABLE (src_rows integer, inserted integer, updated integer)
LANGUAGE plpgsql AS $$
DECLARE v_src integer; v_ins integer; v_month date := date_trunc('month', p_ds)::date;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('datamart.dm_category_monthly:' || v_month::text));
    SELECT count(*) INTO v_src FROM dds.dds_fact_transaction
    WHERE ds >= v_month AND ds < v_month + interval '1 month';
    DELETE FROM datamart.dm_category_monthly WHERE month_start = v_month;
    INSERT INTO datamart.dm_category_monthly
           (month_start, category, operations, unique_cards, amount_kgs,
            confirm_operations, suspicious_operations, suspicious_share)
    SELECT v_month, coalesce(m.category, 'Переводы'), count(*), count(DISTINCT f.card_sk), sum(f.amount_kgs),
           count(*) FILTER (WHERE s.decision = 'confirm'),
           count(*) FILTER (WHERE s.decision = 'suspicious'),
           round(count(*) FILTER (WHERE s.decision = 'suspicious')::numeric / count(*), 4)
    FROM dds.dds_fact_transaction f
    LEFT JOIN dds.dds_dim_merchant m ON m.merchant_sk = f.merchant_sk
    LEFT JOIN dds.dds_transaction_score s ON s.transaction_id = f.transaction_id
    WHERE f.ds >= v_month AND f.ds < v_month + interval '1 month'
    GROUP BY coalesce(m.category, 'Переводы');
    GET DIAGNOSTICS v_ins = ROW_COUNT;
    RETURN QUERY SELECT v_src, v_ins, 0;
END $$;

INSERT INTO dq.check_def (check_name, layer, severity, description, check_sql) VALUES
('dm_daily_key_filled', 'datamart', 'error', 'В дневной витрине есть строка за дату и ключ ds заполнен',
 $q$SELECT CASE WHEN EXISTS (SELECT 1 FROM datamart.dm_transactions_daily WHERE ds = $1) THEN 0 ELSE 1 END$q$),
('dm_daily_matches_fact', 'datamart', 'error', 'Число операций и сумма в сомах дневной витрины равны данным факта',
 $q$SELECT count(*) FROM datamart.dm_transactions_daily d JOIN (SELECT ds, count(*) AS n, sum(amount_kgs) AS s FROM dds.dds_fact_transaction WHERE ds = $1 GROUP BY ds) f USING (ds) WHERE d.operations <> f.n OR d.amount_kgs <> f.s$q$),
('dm_daily_suspicious_matches_score', 'datamart', 'error', 'Подозрительные в витрине равны операциям с решением suspicious',
 $q$SELECT count(*) FROM datamart.dm_transactions_daily d WHERE d.ds = $1 AND d.suspicious_operations <> (SELECT count(*) FROM dds.dds_transaction_score WHERE ds = $1 AND decision = 'suspicious')$q$),
('dm_category_key_unique', 'datamart', 'error', 'Пара (месяц, категория) уникальна и заполнена',
 $q$SELECT coalesce(sum(c - 1), 0) + (SELECT count(*) FROM datamart.dm_category_monthly WHERE category IS NULL OR category = '') FROM (SELECT count(*) AS c FROM datamart.dm_category_monthly GROUP BY month_start, category HAVING count(*) > 1) x$q$),
('dm_category_matches_fact', 'datamart', 'error', 'Операции и сумма в сомах месячной витрины равны данным факта за месяц',
 $q$SELECT count(*) FROM (SELECT date_trunc('month', $1::timestamp)::date AS m) x WHERE (SELECT coalesce(sum(operations), 0) FROM datamart.dm_category_monthly WHERE month_start = x.m) <> (SELECT count(*) FROM dds.dds_fact_transaction WHERE ds >= x.m AND ds < x.m + interval '1 month') OR (SELECT coalesce(sum(amount_kgs), 0) FROM datamart.dm_category_monthly WHERE month_start = x.m) <> (SELECT coalesce(sum(amount_kgs), 0) FROM dds.dds_fact_transaction WHERE ds >= x.m AND ds < x.m + interval '1 month')$q$),
('dm_kgs_daily_equals_monthly', 'datamart', 'error', 'Сумма KGS дневной витрины за месяц равна сумме месячной витрины',
 $q$SELECT count(*) FROM (SELECT date_trunc('month', $1::timestamp)::date AS m) x WHERE (SELECT coalesce(sum(amount_kgs), 0) FROM datamart.dm_transactions_daily WHERE ds >= x.m AND ds < x.m + interval '1 month') <> (SELECT coalesce(sum(amount_kgs), 0) FROM datamart.dm_category_monthly WHERE month_start = x.m)$q$)
ON CONFLICT (check_name) DO UPDATE
    SET layer = EXCLUDED.layer, severity = EXCLUDED.severity,
        description = EXCLUDED.description, check_sql = EXCLUDED.check_sql;
