CREATE SCHEMA IF NOT EXISTS dq;

CREATE TABLE IF NOT EXISTS dq.check_def (
    id           serial  PRIMARY KEY,
    check_name   text    NOT NULL UNIQUE,
    layer        text    NOT NULL CHECK (layer IN ('ods', 'dds', 'datamart')),
    severity     text    NOT NULL CHECK (severity IN ('error', 'warn')),
    description  text    NOT NULL,
    check_sql    text    NOT NULL,
    enabled      boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS dq.check_result (
    id           bigserial   PRIMARY KEY,
    run_ts       timestamptz NOT NULL DEFAULT now(),
    ds           date        NOT NULL,
    layer        text        NOT NULL,
    check_name   text        NOT NULL,
    severity     text        NOT NULL,
    status       text        NOT NULL CHECK (status IN ('passed', 'failed')),
    failed_rows  bigint      NOT NULL,
    details      text
);
CREATE INDEX IF NOT EXISTS ix_check_result_ds ON dq.check_result (ds, run_ts);

INSERT INTO dq.check_def (check_name, layer, severity, description, check_sql) VALUES
('ods_transactions_key_filled', 'ods', 'error', 'У операции за дату заполнен transaction_id',
 $q$SELECT count(*) FROM ods.ods_transactions WHERE ds = $1 AND (transaction_id IS NULL OR btrim(transaction_id) = '')$q$),
('ods_transactions_key_unique', 'ods', 'error', 'transaction_id уникален в ods_transactions',
 $q$SELECT coalesce(sum(c - 1), 0) FROM (SELECT count(*) AS c FROM ods.ods_transactions WHERE ds = $1 GROUP BY transaction_id HAVING count(*) > 1) x$q$),
('ods_customers_key_unique', 'ods', 'error', 'customer_id уникален и заполнен в ods_customers',
 $q$SELECT (SELECT count(*) FROM ods.ods_customers) - (SELECT count(DISTINCT customer_id) FROM ods.ods_customers WHERE customer_id <> '')$q$),
('ods_merchants_key_unique', 'ods', 'error', 'merchant_id уникален и заполнен в ods_merchants',
 $q$SELECT (SELECT count(*) FROM ods.ods_merchants) - (SELECT count(DISTINCT merchant_id) FROM ods.ods_merchants WHERE merchant_id <> '')$q$),
('ods_cards_key_unique', 'ods', 'error', 'card_id уникален и заполнен в ods_cards',
 $q$SELECT (SELECT count(*) FROM ods.ods_cards) - (SELECT count(DISTINCT card_id) FROM ods.ods_cards WHERE card_id <> '')$q$),
('ods_fx_rates_key_unique', 'ods', 'error', 'Пара (rate_date, currency) уникальна в ods_fx_rates',
 $q$SELECT coalesce(sum(c - 1), 0) FROM (SELECT count(*) AS c FROM ods.ods_fx_rates WHERE rate_date = $1 GROUP BY rate_date, currency HAVING count(*) > 1) x$q$),
('ods_fx_rates_present', 'ods', 'error', 'За дату есть курсы USD и EUR',
 $q$SELECT count(*) FROM (VALUES ('USD'), ('EUR')) v(cur) WHERE NOT EXISTS (SELECT 1 FROM ods.ods_fx_rates r WHERE r.rate_date = $1 AND r.currency = v.cur)$q$),
('ods_transactions_amount_positive', 'ods', 'error', 'Сумма операции больше нуля',
 $q$SELECT count(*) FROM ods.ods_transactions WHERE ds = $1 AND (amount IS NULL OR amount <= 0)$q$),
('ods_transactions_allowed_values', 'ods', 'error', 'Валюта, канал, способ оплаты и тип операции допустимы',
 $q$SELECT count(*) FROM ods.ods_transactions WHERE ds = $1 AND NOT (currency IN ('KGS', 'USD', 'EUR') AND channel IN ('POS', 'ONLINE') AND payment_method IN ('CARD', 'QR', 'APPLE_PAY', 'BANK_APP') AND transaction_type IN ('PURCHASE', 'TRANSFER'))$q$),
('ods_transactions_type_fields', 'ods', 'error', 'У покупки есть мерчант и нет получателя, у перевода наоборот',
 $q$SELECT count(*) FROM ods.ods_transactions WHERE ds = $1 AND NOT ((transaction_type = 'PURCHASE' AND merchant_id IS NOT NULL AND recipient_account_id IS NULL) OR (transaction_type = 'TRANSFER' AND recipient_account_id IS NOT NULL AND merchant_id IS NULL))$q$),
('ods_transactions_orphans', 'ods', 'error', 'Операции без карты, клиента или мерчанта в справочниках',
 $q$SELECT count(*) FROM ods.ods_transactions t WHERE t.ds = $1 AND (NOT EXISTS (SELECT 1 FROM ods.ods_cards c WHERE c.card_id = t.card_id) OR NOT EXISTS (SELECT 1 FROM ods.ods_customers c WHERE c.customer_id = t.customer_id) OR (t.merchant_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM ods.ods_merchants m WHERE m.merchant_id = t.merchant_id)))$q$),
('ods_transactions_balance', 'ods', 'error', 'Строки stg = дубли + отбракованные + строки ods',
 $q$SELECT abs(s.total - (s.total - s.uniq) - r.rejected - o.in_ods) FROM (SELECT count(*) AS total, count(DISTINCT btrim(transaction_id)) AS uniq FROM stg.stg_transactions WHERE _ds = $1) s, (SELECT count(*) AS rejected FROM ods.ods_reject WHERE source = 'transactions' AND ds = $1) r, (SELECT count(*) AS in_ods FROM ods.ods_transactions WHERE ds = $1) o$q$),
('ods_transactions_reject_share', 'ods', 'warn', 'Отбраковано не больше 2% строк за дату',
 $q$SELECT CASE WHEN s.total > 0 AND r.rejected::numeric / s.total > 0.02 THEN r.rejected ELSE 0 END FROM (SELECT count(*) AS total FROM stg.stg_transactions WHERE _ds = $1) s, (SELECT count(*) AS rejected FROM ods.ods_reject WHERE source = 'transactions' AND ds = $1) r$q$),
('dds_fact_key_unique', 'dds', 'error', 'transaction_id уникален и заполнен в факте',
 $q$SELECT (SELECT count(*) FROM dds.dds_fact_transaction WHERE ds = $1) - (SELECT count(DISTINCT transaction_id) FROM dds.dds_fact_transaction WHERE ds = $1 AND transaction_id <> '')$q$),
('dds_fact_rowcount', 'dds', 'error', 'Строк в факте за дату столько же, сколько в ods',
 $q$SELECT abs((SELECT count(*) FROM dds.dds_fact_transaction WHERE ds = $1) - (SELECT count(*) FROM ods.ods_transactions WHERE ds = $1))$q$),
('dds_fact_amount_sum', 'dds', 'error', 'Сумма в исходной валюте совпадает между ods и фактом (по валютам)',
 $q$SELECT count(*) FROM (SELECT coalesce(o.currency, f.currency) AS currency FROM (SELECT currency, sum(amount) AS s FROM ods.ods_transactions WHERE ds = $1 GROUP BY currency) o FULL JOIN (SELECT currency, sum(amount) AS s FROM dds.dds_fact_transaction WHERE ds = $1 GROUP BY currency) f ON f.currency = o.currency WHERE o.s IS DISTINCT FROM f.s) x$q$),
('dds_fact_amount_kgs', 'dds', 'error', 'amount_kgs = amount × fx_rate, курс сома равен 1',
 $q$SELECT count(*) FROM dds.dds_fact_transaction WHERE ds = $1 AND (amount_kgs <> round(amount * fx_rate, 2) OR (currency = 'KGS' AND fx_rate <> 1))$q$),
('dds_fact_fx_rate_matches_ods', 'dds', 'error', 'Курс в факте совпадает с курсом в ods_fx_rates на дату',
 $q$SELECT count(*) FROM dds.dds_fact_transaction f LEFT JOIN ods.ods_fx_rates r ON r.rate_date = f.ds AND r.currency = f.currency WHERE f.ds = $1 AND f.currency <> 'KGS' AND f.fx_rate IS DISTINCT FROM r.rate$q$),
('dds_fact_orphans', 'dds', 'error', 'Ссылки факта на измерения клиента, карты, мерчанта и даты существуют',
 $q$SELECT count(*) FROM dds.dds_fact_transaction f WHERE f.ds = $1 AND (NOT EXISTS (SELECT 1 FROM dds.dds_dim_customer c WHERE c.customer_sk = f.customer_sk) OR NOT EXISTS (SELECT 1 FROM dds.dds_dim_card k WHERE k.card_sk = f.card_sk) OR (f.merchant_sk IS NOT NULL AND NOT EXISTS (SELECT 1 FROM dds.dds_dim_merchant m WHERE m.merchant_sk = f.merchant_sk)) OR NOT EXISTS (SELECT 1 FROM dds.dds_dim_date d WHERE d.date_key = f.date_key))$q$),
('dds_fact_customer_version', 'dds', 'error', 'Версия клиента в факте действовала на дату операции',
 $q$SELECT count(*) FROM dds.dds_fact_transaction f JOIN dds.dds_dim_customer c ON c.customer_sk = f.customer_sk WHERE f.ds = $1 AND NOT (f.ds >= c.valid_from AND f.ds < c.valid_to)$q$),
('dds_fact_account_matches_card', 'dds', 'error', 'Счёт операции совпадает со счётом её карты',
 $q$SELECT count(*) FROM dds.dds_fact_transaction f JOIN dds.dds_dim_card k ON k.card_sk = f.card_sk WHERE f.ds = $1 AND f.account_id <> k.account_id$q$),
('dds_transfer_not_to_self', 'dds', 'warn', 'Перевод не на собственный счёт',
 $q$SELECT count(*) FROM dds.dds_fact_transaction WHERE ds = $1 AND transaction_type = 'TRANSFER' AND recipient_account_id = account_id$q$),
('dds_dim_customer_one_current', 'dds', 'error', 'У каждого клиента ровно одна текущая версия',
 $q$SELECT (SELECT count(*) FROM (SELECT customer_id FROM dds.dds_dim_customer WHERE is_current GROUP BY customer_id HAVING count(*) > 1) d) + (SELECT count(*) FROM ods.ods_customers o WHERE NOT EXISTS (SELECT 1 FROM dds.dds_dim_customer d WHERE d.customer_id = o.customer_id AND d.is_current))$q$),
('dds_dim_account_one_current', 'dds', 'error', 'У каждого счёта не больше одной текущей версии',
 $q$SELECT (SELECT count(*) FROM (SELECT account_id FROM dds.dds_dim_account WHERE is_current GROUP BY account_id HAVING count(*) > 1) d) + (SELECT count(*) FROM ods.ods_accounts o WHERE NOT EXISTS (SELECT 1 FROM dds.dds_dim_account d WHERE d.account_id = o.account_id AND d.is_current))$q$),
('dds_dim_keys_unique', 'dds', 'error', 'Ключи измерений мерчанта и карты уникальны',
 $q$SELECT (SELECT count(*) - count(DISTINCT merchant_id) FROM dds.dds_dim_merchant) + (SELECT count(*) - count(DISTINCT card_id) FROM dds.dds_dim_card)$q$)
ON CONFLICT (check_name) DO UPDATE
    SET layer = EXCLUDED.layer, severity = EXCLUDED.severity,
        description = EXCLUDED.description, check_sql = EXCLUDED.check_sql;

CREATE OR REPLACE FUNCTION dq.run_checks(p_ds date, p_layers text[] DEFAULT NULL)
RETURNS TABLE (layer text, check_name text, severity text, status text, failed_rows bigint, details text)
LANGUAGE plpgsql AS $$
#variable_conflict use_variable
DECLARE
    r record;
    v_failed bigint;
BEGIN
    FOR r IN
        SELECT d.check_name AS cname, d.layer AS clayer, d.severity AS cseverity,
               d.description AS cdescription, d.check_sql AS csql
        FROM dq.check_def d
        WHERE d.enabled AND (p_layers IS NULL OR d.layer = ANY (p_layers))
        ORDER BY d.id
    LOOP
        EXECUTE r.csql INTO v_failed USING p_ds;
        layer := r.clayer;
        check_name := r.cname;
        severity := r.cseverity;
        failed_rows := coalesce(v_failed, 0);
        status := CASE WHEN failed_rows = 0 THEN 'passed' ELSE 'failed' END;
        details := CASE WHEN failed_rows = 0 THEN NULL
                        ELSE r.cdescription || ': нарушений ' || failed_rows END;
        INSERT INTO dq.check_result (ds, layer, check_name, severity, status, failed_rows, details)
        VALUES (p_ds, layer, check_name, severity, status, failed_rows, details);
        RETURN NEXT;
    END LOOP;
END $$;

CREATE OR REPLACE VIEW dq.last_run AS
SELECT DISTINCT ON (ds, check_name) ds, run_ts, layer, check_name, severity, status, failed_rows, details
FROM dq.check_result
ORDER BY ds, check_name, run_ts DESC;
