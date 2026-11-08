ALTER TABLE stg.etl_load_log ADD COLUMN IF NOT EXISTS rows_rejected integer;

CREATE OR REPLACE FUNCTION ods.load_fx_rates(p_ds date)
RETURNS TABLE (stg_rows integer, duplicates integer, rejected integer, inserted integer, updated integer)
LANGUAGE plpgsql AS $$
DECLARE
    v_stg integer; v_dist integer; v_rej integer; v_ins integer; v_upd integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('ods.ods_fx_rates:' || p_ds::text));
    DELETE FROM ods.ods_reject WHERE source = 'fx_rates' AND ds = p_ds;
    SELECT count(*) INTO v_stg FROM stg.stg_fx_rates WHERE _ds = p_ds;

    DROP TABLE IF EXISTS tmp_ods_fx;
    CREATE TEMP TABLE tmp_ods_fx ON COMMIT DROP AS
    WITH src AS (
        SELECT DISTINCT ON (nullif(btrim(s.rate_date), ''), upper(nullif(btrim(s.currency), ''))) s.*
        FROM stg.stg_fx_rates s
        WHERE s._ds = p_ds
        ORDER BY nullif(btrim(s.rate_date), ''), upper(nullif(btrim(s.currency), '')), s._loaded_at DESC
    ), typed AS (
        SELECT CASE WHEN btrim(rate_date) ~ '^\d{4}-\d{2}-\d{2}$'
                         AND pg_input_is_valid(btrim(rate_date), 'date')
                    THEN btrim(rate_date)::date END          AS rate_date,
               nullif(btrim(rate_date), '')                  AS rate_date_raw,
               upper(nullif(btrim(currency), ''))            AS currency,
               nullif(btrim(rate), '')                       AS rate_raw,
               CASE WHEN btrim(rate) ~ '^\d{1,8}(\.\d{1,4})?$'
                    THEN btrim(rate)::numeric(12,4) END      AS rate,
               to_jsonb(src) - '_loaded_at'                  AS raw
        FROM src
    )
    SELECT t.*, CASE
            WHEN t.rate_date_raw IS NULL OR t.currency IS NULL THEN 'empty_key'
            WHEN t.rate_date IS NULL                           THEN 'bad_date'
            WHEN t.rate_date <> p_ds                           THEN 'date_mismatch'
            WHEN t.currency NOT IN ('USD', 'EUR')              THEN 'bad_currency'
            WHEN t.rate_raw IS NULL                            THEN 'empty_rate'
            WHEN t.rate IS NULL                                THEN 'bad_rate_format'
            WHEN t.rate <= 0                                   THEN 'bad_rate'
        END AS reject_reason
    FROM typed t;
    SELECT count(*) INTO v_dist FROM tmp_ods_fx;

    INSERT INTO ods.ods_reject (source, ds, record_key, reason, raw)
    SELECT 'fx_rates', p_ds, concat_ws('|', rate_date_raw, currency), reject_reason, raw
    FROM tmp_ods_fx WHERE reject_reason IS NOT NULL;
    GET DIAGNOSTICS v_rej = ROW_COUNT;

    WITH up AS (
        INSERT INTO ods.ods_fx_rates AS o (rate_date, currency, rate, _ds)
        SELECT rate_date, currency, rate, p_ds
        FROM tmp_ods_fx WHERE reject_reason IS NULL ORDER BY rate_date, currency
        ON CONFLICT (rate_date, currency) DO UPDATE
            SET rate = EXCLUDED.rate, _ds = EXCLUDED._ds, _updated_at = now()
            WHERE o.rate IS DISTINCT FROM EXCLUDED.rate
        RETURNING (xmax = 0) AS is_insert
    )
    SELECT count(*) FILTER (WHERE is_insert), count(*) FILTER (WHERE NOT is_insert) INTO v_ins, v_upd FROM up;

    RETURN QUERY SELECT v_stg, v_stg - v_dist, v_rej, v_ins, v_upd;
END $$;
