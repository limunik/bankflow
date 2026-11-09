CREATE TABLE IF NOT EXISTS stg.stg_accounts_cdc (
    id            bigserial   PRIMARY KEY,
    topic         text        NOT NULL,
    kafka_partition integer   NOT NULL,
    kafka_offset  bigint      NOT NULL,
    account_id    text        NOT NULL,
    op            text        NOT NULL CHECK (op IN ('c', 'u', 'd', 'r')),
    source_lsn    bigint      NOT NULL,
    source_ts     timestamptz NOT NULL,
    payload       jsonb       NOT NULL,
    received_at   timestamptz NOT NULL DEFAULT now(),
    applied_at    timestamptz,
    UNIQUE (topic, kafka_partition, kafka_offset)
);

CREATE INDEX IF NOT EXISTS stg_accounts_cdc_pending_idx
    ON stg.stg_accounts_cdc (id) WHERE applied_at IS NULL;

CREATE OR REPLACE FUNCTION ods.apply_accounts_cdc()
RETURNS TABLE (events integer, accounts integer, soft_deleted integer)
LANGUAGE plpgsql AS $$
DECLARE v_events integer; v_accounts integer; v_deleted integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('ods.apply_accounts_cdc'));

    CREATE TEMP TABLE tmp_cdc_pending ON COMMIT DROP AS
    SELECT id, account_id, op, source_lsn, source_ts,
           CASE WHEN op = 'd' THEN payload -> 'before' ELSE payload -> 'after' END AS r
    FROM stg.stg_accounts_cdc
    WHERE applied_at IS NULL;

    SELECT count(*) INTO v_events FROM tmp_cdc_pending;

    CREATE TEMP TABLE tmp_cdc_latest ON COMMIT DROP AS
    SELECT DISTINCT ON (account_id) *
    FROM tmp_cdc_pending
    ORDER BY account_id, source_lsn DESC, id DESC;

    INSERT INTO ods.ods_accounts
           (account_id, customer_id, status, balance, limit_amount, opened_at,
            is_deleted, deleted_at, source_lsn, updated_at)
    SELECT l.account_id,
           l.r ->> 'customer_id',
           l.r ->> 'status',
           (l.r ->> 'balance')::numeric,
           (l.r ->> 'limit_amount')::numeric,
           DATE '1970-01-01' + (l.r ->> 'opened_at')::integer,
           l.op = 'd',
           CASE WHEN l.op = 'd' THEN l.source_ts END,
           l.source_lsn,
           (l.r ->> 'updated_at')::timestamptz
    FROM tmp_cdc_latest l
    ON CONFLICT (account_id) DO UPDATE
    SET customer_id  = EXCLUDED.customer_id,
        status       = EXCLUDED.status,
        balance      = EXCLUDED.balance,
        limit_amount = EXCLUDED.limit_amount,
        opened_at    = EXCLUDED.opened_at,
        is_deleted   = EXCLUDED.is_deleted,
        deleted_at   = EXCLUDED.deleted_at,
        source_lsn   = EXCLUDED.source_lsn,
        updated_at   = EXCLUDED.updated_at,
        _loaded_at   = now()
    WHERE ods.ods_accounts.source_lsn < EXCLUDED.source_lsn;
    GET DIAGNOSTICS v_accounts = ROW_COUNT;

    SELECT count(*) INTO v_deleted FROM tmp_cdc_latest WHERE op = 'd';

    UPDATE stg.stg_accounts_cdc s
    SET applied_at = clock_timestamp()
    FROM tmp_cdc_pending p
    WHERE s.id = p.id;

    RETURN QUERY SELECT v_events, v_accounts, v_deleted;
END $$;
