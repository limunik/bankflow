CREATE OR REPLACE FUNCTION ods.load_customers(p_ds date)
RETURNS TABLE (stg_rows integer, duplicates integer, rejected integer, inserted integer, updated integer)
LANGUAGE plpgsql AS $$
DECLARE
    v_stg integer; v_dist integer; v_rej integer; v_ins integer; v_upd integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('ods.ods_customers'));
    DELETE FROM ods.ods_reject WHERE source = 'customers' AND ds = p_ds;
    SELECT count(*) INTO v_stg FROM stg.stg_customers;

    DROP TABLE IF EXISTS tmp_ods_load;
    CREATE TEMP TABLE tmp_ods_load ON COMMIT DROP AS
    SELECT t.*, CASE
            WHEN t.customer_id   IS NULL THEN 'empty_key'
            WHEN t.customer_name IS NULL THEN 'empty_name'
            WHEN t.customer_type IS NULL OR t.customer_type NOT IN ('individual', 'legal') THEN 'bad_type'
        END AS reject_reason
    FROM (
        SELECT DISTINCT ON (nullif(btrim(s.customer_id), ''))
               nullif(btrim(s.customer_id), '')          AS customer_id,
               nullif(btrim(s.customer_name), '')        AS customer_name,
               lower(nullif(btrim(s.customer_type), '')) AS customer_type,
               to_jsonb(s) - '_loaded_at'                AS raw
        FROM stg.stg_customers s
        ORDER BY nullif(btrim(s.customer_id), ''), s._loaded_at DESC
    ) t;
    SELECT count(*) INTO v_dist FROM tmp_ods_load;

    INSERT INTO ods.ods_reject (source, ds, record_key, reason, raw)
    SELECT 'customers', p_ds, customer_id, reject_reason, raw FROM tmp_ods_load WHERE reject_reason IS NOT NULL;
    GET DIAGNOSTICS v_rej = ROW_COUNT;

    WITH up AS (
        INSERT INTO ods.ods_customers AS o (customer_id, customer_name, customer_type, _ds)
        SELECT customer_id, customer_name, customer_type, p_ds
        FROM tmp_ods_load WHERE reject_reason IS NULL ORDER BY customer_id
        ON CONFLICT (customer_id) DO UPDATE
            SET customer_name = EXCLUDED.customer_name, customer_type = EXCLUDED.customer_type,
                _ds = EXCLUDED._ds, _updated_at = now()
            WHERE (o.customer_name, o.customer_type) IS DISTINCT FROM (EXCLUDED.customer_name, EXCLUDED.customer_type)
        RETURNING (xmax = 0) AS is_insert
    )
    SELECT count(*) FILTER (WHERE is_insert), count(*) FILTER (WHERE NOT is_insert) INTO v_ins, v_upd FROM up;

    RETURN QUERY SELECT v_stg, v_stg - v_dist, v_rej, v_ins, v_upd;
END $$;

CREATE OR REPLACE FUNCTION ods.load_merchants(p_ds date)
RETURNS TABLE (stg_rows integer, duplicates integer, rejected integer, inserted integer, updated integer)
LANGUAGE plpgsql AS $$
DECLARE
    v_stg integer; v_dist integer; v_rej integer; v_ins integer; v_upd integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('ods.ods_merchants'));
    DELETE FROM ods.ods_reject WHERE source = 'merchants' AND ds = p_ds;
    SELECT count(*) INTO v_stg FROM stg.stg_merchants;

    DROP TABLE IF EXISTS tmp_ods_load;
    CREATE TEMP TABLE tmp_ods_load ON COMMIT DROP AS
    SELECT t.*, CASE
            WHEN t.merchant_id   IS NULL THEN 'empty_key'
            WHEN t.merchant_name IS NULL THEN 'empty_name'
            WHEN t.category      IS NULL THEN 'empty_category'
            WHEN t.country IS NULL OR t.country !~ '^[A-Z]{2}$' THEN 'bad_country'
        END AS reject_reason
    FROM (
        SELECT DISTINCT ON (nullif(btrim(s.merchant_id), ''))
               nullif(btrim(s.merchant_id), '')    AS merchant_id,
               nullif(btrim(s.merchant_name), '')  AS merchant_name,
               nullif(btrim(s.category), '')       AS category,
               upper(nullif(btrim(s.country), '')) AS country,
               to_jsonb(s) - '_loaded_at'          AS raw
        FROM stg.stg_merchants s
        ORDER BY nullif(btrim(s.merchant_id), ''), s._loaded_at DESC
    ) t;
    SELECT count(*) INTO v_dist FROM tmp_ods_load;

    INSERT INTO ods.ods_reject (source, ds, record_key, reason, raw)
    SELECT 'merchants', p_ds, merchant_id, reject_reason, raw FROM tmp_ods_load WHERE reject_reason IS NOT NULL;
    GET DIAGNOSTICS v_rej = ROW_COUNT;

    WITH up AS (
        INSERT INTO ods.ods_merchants AS o (merchant_id, merchant_name, category, country, _ds)
        SELECT merchant_id, merchant_name, category, country, p_ds
        FROM tmp_ods_load WHERE reject_reason IS NULL ORDER BY merchant_id
        ON CONFLICT (merchant_id) DO UPDATE
            SET merchant_name = EXCLUDED.merchant_name, category = EXCLUDED.category,
                country = EXCLUDED.country, _ds = EXCLUDED._ds, _updated_at = now()
            WHERE (o.merchant_name, o.category, o.country)
                  IS DISTINCT FROM (EXCLUDED.merchant_name, EXCLUDED.category, EXCLUDED.country)
        RETURNING (xmax = 0) AS is_insert
    )
    SELECT count(*) FILTER (WHERE is_insert), count(*) FILTER (WHERE NOT is_insert) INTO v_ins, v_upd FROM up;

    RETURN QUERY SELECT v_stg, v_stg - v_dist, v_rej, v_ins, v_upd;
END $$;

CREATE OR REPLACE FUNCTION ods.load_cards(p_ds date)
RETURNS TABLE (stg_rows integer, duplicates integer, rejected integer, inserted integer, updated integer)
LANGUAGE plpgsql AS $$
DECLARE
    v_stg integer; v_dist integer; v_rej integer; v_ins integer; v_upd integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('ods.ods_cards'));
    DELETE FROM ods.ods_reject WHERE source = 'cards' AND ds = p_ds;
    SELECT count(*) INTO v_stg FROM stg.stg_cards;

    DROP TABLE IF EXISTS tmp_ods_load;
    CREATE TEMP TABLE tmp_ods_load ON COMMIT DROP AS
    SELECT t.*, CASE
            WHEN t.card_id     IS NULL THEN 'empty_key'
            WHEN t.account_id  IS NULL THEN 'empty_account'
            WHEN t.customer_id IS NULL THEN 'empty_customer'
            WHEN t.card_scheme IS NULL OR t.card_scheme NOT IN ('VISA', 'MASTERCARD') THEN 'bad_scheme'
            WHEN NOT EXISTS (SELECT 1 FROM ods.ods_customers c WHERE c.customer_id = t.customer_id)
                THEN 'unknown_customer'
        END AS reject_reason
    FROM (
        SELECT DISTINCT ON (nullif(btrim(s.card_id), ''))
               nullif(btrim(s.card_id), '')          AS card_id,
               nullif(btrim(s.account_id), '')       AS account_id,
               nullif(btrim(s.customer_id), '')      AS customer_id,
               upper(nullif(btrim(s.card_scheme), '')) AS card_scheme,
               to_jsonb(s) - '_loaded_at'            AS raw
        FROM stg.stg_cards s
        ORDER BY nullif(btrim(s.card_id), ''), s._loaded_at DESC
    ) t;
    SELECT count(*) INTO v_dist FROM tmp_ods_load;

    INSERT INTO ods.ods_reject (source, ds, record_key, reason, raw)
    SELECT 'cards', p_ds, card_id, reject_reason, raw FROM tmp_ods_load WHERE reject_reason IS NOT NULL;
    GET DIAGNOSTICS v_rej = ROW_COUNT;

    WITH up AS (
        INSERT INTO ods.ods_cards AS o (card_id, account_id, customer_id, card_scheme, _ds)
        SELECT card_id, account_id, customer_id, card_scheme, p_ds
        FROM tmp_ods_load WHERE reject_reason IS NULL ORDER BY card_id
        ON CONFLICT (card_id) DO UPDATE
            SET account_id = EXCLUDED.account_id, customer_id = EXCLUDED.customer_id,
                card_scheme = EXCLUDED.card_scheme, _ds = EXCLUDED._ds, _updated_at = now()
            WHERE (o.account_id, o.customer_id, o.card_scheme)
                  IS DISTINCT FROM (EXCLUDED.account_id, EXCLUDED.customer_id, EXCLUDED.card_scheme)
        RETURNING (xmax = 0) AS is_insert
    )
    SELECT count(*) FILTER (WHERE is_insert), count(*) FILTER (WHERE NOT is_insert) INTO v_ins, v_upd FROM up;

    RETURN QUERY SELECT v_stg, v_stg - v_dist, v_rej, v_ins, v_upd;
END $$;

CREATE OR REPLACE FUNCTION ods.load_transactions(p_ds date)
RETURNS TABLE (stg_rows integer, duplicates integer, rejected integer, inserted integer, updated integer)
LANGUAGE plpgsql AS $$
DECLARE
    v_stg integer; v_dist integer; v_rej integer; v_ins integer; v_upd integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('ods.ods_transactions:' || p_ds::text));
    DELETE FROM ods.ods_reject WHERE source = 'transactions' AND ds = p_ds;
    SELECT count(*) INTO v_stg FROM stg.stg_transactions WHERE _ds = p_ds;

    DROP TABLE IF EXISTS tmp_ods_tx;
    CREATE TEMP TABLE tmp_ods_tx ON COMMIT DROP AS
    WITH src AS (
        SELECT DISTINCT ON (nullif(btrim(s.transaction_id), '')) s.*
        FROM stg.stg_transactions s
        WHERE s._ds = p_ds
        ORDER BY nullif(btrim(s.transaction_id), ''), s._loaded_at DESC
    ), typed AS (
        SELECT nullif(btrim(transaction_id), '')            AS transaction_id,
               nullif(btrim(card_id), '')                   AS card_id,
               nullif(btrim(account_id), '')                AS account_id,
               nullif(btrim(customer_id), '')               AS customer_id,
               nullif(btrim(merchant_id), '')               AS merchant_id,
               nullif(btrim(recipient_account_id), '')      AS recipient_account_id,
               CASE WHEN btrim(transaction_ts) ~ '^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$'
                         AND pg_input_is_valid(btrim(transaction_ts), 'timestamp')
                    THEN btrim(transaction_ts)::timestamp END AS transaction_ts,
               nullif(btrim(amount), '')                    AS amount_raw,
               CASE WHEN btrim(amount) ~ '^\d{1,12}(\.\d{1,2})?$'
                    THEN btrim(amount)::numeric(14,2) END   AS amount,
               upper(nullif(btrim(currency), ''))           AS currency,
               upper(nullif(btrim(channel), ''))            AS channel,
               upper(nullif(btrim(payment_method), ''))     AS payment_method,
               upper(nullif(btrim(transaction_type), ''))   AS transaction_type,
               to_jsonb(src) - '_loaded_at'                 AS raw
        FROM src
    )
    SELECT t.*, CASE
            WHEN t.transaction_id IS NULL                                  THEN 'empty_key'
            WHEN t.card_id IS NULL                                         THEN 'empty_card'
            WHEN t.account_id IS NULL                                      THEN 'empty_account'
            WHEN t.customer_id IS NULL                                     THEN 'empty_customer'
            WHEN t.amount_raw IS NULL                                      THEN 'empty_amount'
            WHEN t.amount IS NULL                                          THEN 'bad_amount_format'
            WHEN t.amount <= 0                                             THEN 'bad_amount'
            WHEN t.transaction_ts IS NULL                                  THEN 'bad_timestamp'
            WHEN t.transaction_ts::date <> p_ds                            THEN 'date_mismatch'
            WHEN t.currency IS NULL OR t.currency NOT IN ('KGS', 'USD', 'EUR') THEN 'bad_currency'
            WHEN t.channel IS NULL OR t.channel NOT IN ('POS', 'ONLINE')   THEN 'bad_channel'
            WHEN t.payment_method IS NULL
                 OR t.payment_method NOT IN ('CARD', 'QR', 'APPLE_PAY', 'BANK_APP') THEN 'bad_payment_method'
            WHEN t.transaction_type IS NULL
                 OR t.transaction_type NOT IN ('PURCHASE', 'TRANSFER')     THEN 'bad_type'
            WHEN t.transaction_type = 'PURCHASE' AND t.merchant_id IS NULL THEN 'empty_merchant'
            WHEN t.transaction_type = 'PURCHASE' AND t.recipient_account_id IS NOT NULL THEN 'type_mismatch'
            WHEN t.transaction_type = 'TRANSFER' AND t.recipient_account_id IS NULL THEN 'empty_recipient'
            WHEN t.transaction_type = 'TRANSFER' AND t.merchant_id IS NOT NULL THEN 'type_mismatch'
            WHEN NOT EXISTS (SELECT 1 FROM ods.ods_cards c WHERE c.card_id = t.card_id)             THEN 'unknown_card'
            WHEN NOT EXISTS (SELECT 1 FROM ods.ods_customers c WHERE c.customer_id = t.customer_id) THEN 'unknown_customer'
            WHEN t.merchant_id IS NOT NULL
                 AND NOT EXISTS (SELECT 1 FROM ods.ods_merchants m WHERE m.merchant_id = t.merchant_id) THEN 'unknown_merchant'
        END AS reject_reason
    FROM typed t;
    SELECT count(*) INTO v_dist FROM tmp_ods_tx;

    INSERT INTO ods.ods_reject (source, ds, record_key, reason, raw)
    SELECT 'transactions', p_ds, transaction_id, reject_reason, raw FROM tmp_ods_tx WHERE reject_reason IS NOT NULL;
    GET DIAGNOSTICS v_rej = ROW_COUNT;

    WITH up AS (
        INSERT INTO ods.ods_transactions AS o
               (transaction_id, card_id, account_id, customer_id, merchant_id, recipient_account_id,
                transaction_ts, amount, currency, channel, payment_method, transaction_type, ds)
        SELECT transaction_id, card_id, account_id, customer_id, merchant_id, recipient_account_id,
               transaction_ts, amount, currency, channel, payment_method, transaction_type, p_ds
        FROM tmp_ods_tx WHERE reject_reason IS NULL ORDER BY transaction_id
        ON CONFLICT (transaction_id) DO UPDATE
            SET card_id = EXCLUDED.card_id, account_id = EXCLUDED.account_id,
                customer_id = EXCLUDED.customer_id, merchant_id = EXCLUDED.merchant_id,
                recipient_account_id = EXCLUDED.recipient_account_id,
                transaction_ts = EXCLUDED.transaction_ts, amount = EXCLUDED.amount,
                currency = EXCLUDED.currency, channel = EXCLUDED.channel,
                payment_method = EXCLUDED.payment_method, transaction_type = EXCLUDED.transaction_type,
                ds = EXCLUDED.ds, _updated_at = now()
            WHERE (o.card_id, o.account_id, o.customer_id, o.merchant_id, o.recipient_account_id,
                   o.transaction_ts, o.amount, o.currency, o.channel, o.payment_method, o.transaction_type)
                  IS DISTINCT FROM
                  (EXCLUDED.card_id, EXCLUDED.account_id, EXCLUDED.customer_id, EXCLUDED.merchant_id,
                   EXCLUDED.recipient_account_id, EXCLUDED.transaction_ts, EXCLUDED.amount,
                   EXCLUDED.currency, EXCLUDED.channel, EXCLUDED.payment_method, EXCLUDED.transaction_type)
        RETURNING (xmax = 0) AS is_insert
    )
    SELECT count(*) FILTER (WHERE is_insert), count(*) FILTER (WHERE NOT is_insert) INTO v_ins, v_upd FROM up;

    RETURN QUERY SELECT v_stg, v_stg - v_dist, v_rej, v_ins, v_upd;
END $$;
