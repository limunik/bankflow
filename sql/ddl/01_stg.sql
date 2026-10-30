-- Layer STG: raw data exactly as it arrived.
-- Data columns are text (nothing is rejected at this layer).
-- Service columns: _ds (load date), _source_file, _loaded_at.
-- No primary keys on purpose: duplicates from the source must stay visible here.

CREATE TABLE IF NOT EXISTS stg.stg_transactions (
    transaction_id  text,
    card_id         text,
    account_id      text,
    customer_id     text,
    merchant_id     text,
    transaction_ts  text,
    amount          text,
    currency        text,
    channel         text,
    payment_method  text,
    _ds             date        NOT NULL,
    _source_file    text        NOT NULL,
    _loaded_at      timestamptz NOT NULL DEFAULT now()
);

-- Speeds up "DELETE ... WHERE _ds = ..." used by the idempotent reload
CREATE INDEX IF NOT EXISTS ix_stg_transactions_ds
    ON stg.stg_transactions (_ds);

CREATE TABLE IF NOT EXISTS stg.stg_merchants (
    merchant_id     text,
    merchant_name   text,
    category        text,
    country         text,
    _ds             date        NOT NULL,
    _source_file    text        NOT NULL,
    _loaded_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS stg.stg_cards (
    card_id         text,
    account_id      text,
    customer_id     text,
    card_scheme     text,
    _ds             date        NOT NULL,
    _source_file    text        NOT NULL,
    _loaded_at      timestamptz NOT NULL DEFAULT now()
);

-- Load journal: one row per run of every load task (requirement FT-4)
CREATE TABLE IF NOT EXISTS stg.etl_load_log (
    id             bigserial   PRIMARY KEY,
    source         text        NOT NULL,
    ds             date        NOT NULL,
    started_at     timestamptz NOT NULL DEFAULT now(),
    finished_at    timestamptz,
    status         text        NOT NULL CHECK (status IN ('running', 'success', 'failed')),
    rows_loaded    integer,
    error_message  text
);