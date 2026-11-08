\set ON_ERROR_STOP on
BEGIN;
CREATE TEMP TABLE tmp_accounts (
    account_id text, customer_id text, status text, balance numeric(14,2),
    limit_amount numeric(14,2), opened_at date, updated_at timestamptz
) ON COMMIT DROP;
\copy tmp_accounts FROM pstdin WITH CSV
INSERT INTO ods.ods_accounts (account_id, customer_id, status, balance, limit_amount, opened_at, source_lsn, updated_at)
SELECT account_id, customer_id, status, balance, limit_amount, opened_at, 0, updated_at FROM tmp_accounts
ON CONFLICT (account_id) DO UPDATE
    SET customer_id = EXCLUDED.customer_id, status = EXCLUDED.status, balance = EXCLUDED.balance,
        limit_amount = EXCLUDED.limit_amount, opened_at = EXCLUDED.opened_at, updated_at = EXCLUDED.updated_at,
        _loaded_at = now()
    WHERE ods.ods_accounts.source_lsn = 0 AND EXCLUDED.updated_at >= ods.ods_accounts.updated_at;
COMMIT;
SELECT count(*) AS accounts_in_ods, count(*) FILTER (WHERE status <> 'active') AS inactive FROM ods.ods_accounts;
