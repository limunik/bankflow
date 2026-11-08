CREATE OR REPLACE FUNCTION dds.load_dim_merchant(p_ds date)
RETURNS TABLE (src_rows integer, inserted integer, updated integer)
LANGUAGE plpgsql AS $$
DECLARE v_src integer; v_ins integer; v_upd integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('dds.dds_dim_merchant'));
    SELECT count(*) INTO v_src FROM ods.ods_merchants;
    WITH up AS (
        INSERT INTO dds.dds_dim_merchant AS d (merchant_id, merchant_name, category, country)
        SELECT merchant_id, merchant_name, category, country::text FROM ods.ods_merchants ORDER BY merchant_id
        ON CONFLICT (merchant_id) DO UPDATE
            SET merchant_name = EXCLUDED.merchant_name, category = EXCLUDED.category,
                country = EXCLUDED.country, _updated_at = now()
            WHERE (d.merchant_name, d.category, d.country)
                  IS DISTINCT FROM (EXCLUDED.merchant_name, EXCLUDED.category, EXCLUDED.country)
        RETURNING (xmax = 0) AS is_insert
    )
    SELECT count(*) FILTER (WHERE is_insert), count(*) FILTER (WHERE NOT is_insert) INTO v_ins, v_upd FROM up;
    RETURN QUERY SELECT v_src, v_ins, v_upd;
END $$;

CREATE OR REPLACE FUNCTION dds.load_dim_card(p_ds date)
RETURNS TABLE (src_rows integer, inserted integer, updated integer)
LANGUAGE plpgsql AS $$
DECLARE v_src integer; v_ins integer; v_upd integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('dds.dds_dim_card'));
    SELECT count(*) INTO v_src FROM ods.ods_cards;
    WITH up AS (
        INSERT INTO dds.dds_dim_card AS d (card_id, account_id, customer_id, card_scheme)
        SELECT card_id, account_id, customer_id, card_scheme FROM ods.ods_cards ORDER BY card_id
        ON CONFLICT (card_id) DO UPDATE
            SET account_id = EXCLUDED.account_id, customer_id = EXCLUDED.customer_id,
                card_scheme = EXCLUDED.card_scheme, _updated_at = now()
            WHERE (d.account_id, d.customer_id, d.card_scheme)
                  IS DISTINCT FROM (EXCLUDED.account_id, EXCLUDED.customer_id, EXCLUDED.card_scheme)
        RETURNING (xmax = 0) AS is_insert
    )
    SELECT count(*) FILTER (WHERE is_insert), count(*) FILTER (WHERE NOT is_insert) INTO v_ins, v_upd FROM up;
    RETURN QUERY SELECT v_src, v_ins, v_upd;
END $$;

CREATE OR REPLACE FUNCTION dds.load_dim_customer(p_ds date)
RETURNS TABLE (src_rows integer, inserted integer, updated integer)
LANGUAGE plpgsql AS $$
DECLARE v_src integer; v_fix integer; v_close integer; v_ins integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('dds.dds_dim_customer'));
    SELECT count(*) INTO v_src FROM ods.ods_customers;

    WITH fix AS (
        UPDATE dds.dds_dim_customer d
        SET customer_name = o.customer_name, customer_type = o.customer_type
        FROM ods.ods_customers o
        WHERE d.customer_id = o.customer_id AND d.is_current AND d.valid_from >= p_ds
          AND (d.customer_name, d.customer_type) IS DISTINCT FROM (o.customer_name, o.customer_type)
        RETURNING 1
    )
    SELECT count(*) INTO v_fix FROM fix;

    WITH closed AS (
        UPDATE dds.dds_dim_customer d
        SET valid_to = p_ds, is_current = false
        FROM ods.ods_customers o
        WHERE d.customer_id = o.customer_id AND d.is_current AND d.valid_from < p_ds
          AND (d.customer_name, d.customer_type) IS DISTINCT FROM (o.customer_name, o.customer_type)
        RETURNING 1
    )
    SELECT count(*) INTO v_close FROM closed;

    WITH new_versions AS (
        INSERT INTO dds.dds_dim_customer (customer_id, customer_name, customer_type, valid_from, valid_to, is_current)
        SELECT o.customer_id, o.customer_name, o.customer_type,
               CASE WHEN EXISTS (SELECT 1 FROM dds.dds_dim_customer x WHERE x.customer_id = o.customer_id)
                    THEN p_ds ELSE DATE '1900-01-01' END,
               DATE '9999-12-31', true
        FROM ods.ods_customers o
        WHERE NOT EXISTS (SELECT 1 FROM dds.dds_dim_customer d WHERE d.customer_id = o.customer_id AND d.is_current)
        ORDER BY o.customer_id
        RETURNING 1
    )
    SELECT count(*) INTO v_ins FROM new_versions;

    RETURN QUERY SELECT v_src, v_ins, v_fix + v_close;
END $$;

CREATE OR REPLACE FUNCTION dds.load_dim_account(p_ds date)
RETURNS TABLE (src_rows integer, inserted integer, updated integer)
LANGUAGE plpgsql AS $$
DECLARE v_src integer; v_fix integer; v_close integer; v_ins integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('dds.dds_dim_account'));
    SELECT count(*) INTO v_src FROM ods.ods_accounts;

    WITH fix AS (
        UPDATE dds.dds_dim_account d
        SET customer_id = o.customer_id, status = o.status, limit_amount = o.limit_amount, is_deleted = o.is_deleted
        FROM ods.ods_accounts o
        WHERE d.account_id = o.account_id AND d.is_current AND o.updated_at <= d.valid_from
          AND (d.customer_id, d.status, d.limit_amount, d.is_deleted)
              IS DISTINCT FROM (o.customer_id, o.status, o.limit_amount, o.is_deleted)
        RETURNING 1
    )
    SELECT count(*) INTO v_fix FROM fix;

    WITH closed AS (
        UPDATE dds.dds_dim_account d
        SET valid_to = o.updated_at, is_current = false
        FROM ods.ods_accounts o
        WHERE d.account_id = o.account_id AND d.is_current AND o.updated_at > d.valid_from
          AND (d.customer_id, d.status, d.limit_amount, d.is_deleted)
              IS DISTINCT FROM (o.customer_id, o.status, o.limit_amount, o.is_deleted)
        RETURNING 1
    )
    SELECT count(*) INTO v_close FROM closed;

    WITH new_versions AS (
        INSERT INTO dds.dds_dim_account
               (account_id, customer_id, status, limit_amount, is_deleted, opened_at, valid_from, valid_to, is_current)
        SELECT o.account_id, o.customer_id, o.status, o.limit_amount, o.is_deleted, o.opened_at,
               o.updated_at, TIMESTAMPTZ '9999-12-31 00:00:00+00', true
        FROM ods.ods_accounts o
        WHERE NOT EXISTS (SELECT 1 FROM dds.dds_dim_account d WHERE d.account_id = o.account_id AND d.is_current)
        ORDER BY o.account_id
        RETURNING 1
    )
    SELECT count(*) INTO v_ins FROM new_versions;

    RETURN QUERY SELECT v_src, v_ins, v_fix + v_close;
END $$;

CREATE OR REPLACE FUNCTION dds.load_fact_transaction(p_ds date)
RETURNS TABLE (src_rows integer, inserted integer, updated integer)
LANGUAGE plpgsql AS $$
DECLARE v_src integer; v_ins integer; v_missing text;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('dds.dds_fact_transaction:' || p_ds::text));
    SELECT count(*) INTO v_src FROM ods.ods_transactions WHERE ds = p_ds;

    SELECT string_agg(DISTINCT t.currency, ', ') INTO v_missing
    FROM ods.ods_transactions t
    WHERE t.ds = p_ds AND t.currency <> 'KGS'
      AND NOT EXISTS (SELECT 1 FROM ods.ods_fx_rates r WHERE r.rate_date = p_ds AND r.currency = t.currency);
    IF v_missing IS NOT NULL THEN
        RAISE EXCEPTION 'Нет курса за %: %', p_ds, v_missing;
    END IF;

    DELETE FROM dds.dds_fact_transaction WHERE ds = p_ds;

    INSERT INTO dds.dds_fact_transaction
           (transaction_id, ds, date_key, customer_sk, card_sk, merchant_sk, account_id, recipient_account_id,
            transaction_ts, amount, currency, fx_rate, amount_kgs, channel, payment_method, transaction_type)
    SELECT t.transaction_id, t.ds, dd.date_key, c.customer_sk, k.card_sk, m.merchant_sk, t.account_id,
           t.recipient_account_id, t.transaction_ts, t.amount, t.currency,
           coalesce(r.rate, 1), round(t.amount * coalesce(r.rate, 1), 2),
           t.channel, t.payment_method, t.transaction_type
    FROM ods.ods_transactions t
    JOIN dds.dds_dim_date dd ON dd.full_date = t.ds
    JOIN dds.dds_dim_customer c ON c.customer_id = t.customer_id
                               AND t.ds >= c.valid_from AND t.ds < c.valid_to
    JOIN dds.dds_dim_card k ON k.card_id = t.card_id
    LEFT JOIN dds.dds_dim_merchant m ON m.merchant_id = t.merchant_id
    LEFT JOIN ods.ods_fx_rates r ON r.rate_date = t.ds AND r.currency = t.currency
    WHERE t.ds = p_ds
    ORDER BY t.transaction_id;
    GET DIAGNOSTICS v_ins = ROW_COUNT;

    IF v_ins <> v_src THEN
        RAISE EXCEPTION 'В Core попало % из % строк за %: не найдены измерения', v_ins, v_src, p_ds;
    END IF;

    RETURN QUERY SELECT v_src, v_ins, 0;
END $$;
