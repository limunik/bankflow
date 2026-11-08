CREATE EXTENSION IF NOT EXISTS btree_gist;
CREATE SCHEMA IF NOT EXISTS dds;

CREATE TABLE IF NOT EXISTS dds.dds_dim_date (
    date_key     integer     PRIMARY KEY,
    full_date    date        NOT NULL UNIQUE,
    year         smallint    NOT NULL,
    quarter      smallint    NOT NULL,
    month        smallint    NOT NULL,
    day          smallint    NOT NULL,
    day_of_week  smallint    NOT NULL,
    is_weekend   boolean     NOT NULL,
    is_payday    boolean     NOT NULL
);

INSERT INTO dds.dds_dim_date
SELECT to_char(d, 'YYYYMMDD')::integer, d::date,
       extract(year FROM d), extract(quarter FROM d), extract(month FROM d), extract(day FROM d),
       extract(isodow FROM d), extract(isodow FROM d) IN (6, 7), extract(day FROM d) IN (5, 20)
FROM generate_series('2026-01-01'::date, '2027-12-31'::date, interval '1 day') AS d
ON CONFLICT (date_key) DO NOTHING;

CREATE TABLE IF NOT EXISTS dds.dds_dim_customer (
    customer_sk    bigserial   PRIMARY KEY,
    customer_id    text        NOT NULL,
    customer_name  text        NOT NULL,
    customer_type  text        NOT NULL CHECK (customer_type IN ('individual', 'legal')),
    valid_from     date        NOT NULL,
    valid_to       date        NOT NULL,
    is_current     boolean     NOT NULL,
    _loaded_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_dim_customer_period CHECK (valid_from < valid_to),
    CONSTRAINT ex_dim_customer_no_overlap EXCLUDE USING gist
        (customer_id WITH =, daterange(valid_from, valid_to) WITH &&)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_customer_current ON dds.dds_dim_customer (customer_id) WHERE is_current;

CREATE TABLE IF NOT EXISTS dds.dds_dim_merchant (
    merchant_sk    bigserial   PRIMARY KEY,
    merchant_id    text        NOT NULL UNIQUE,
    merchant_name  text        NOT NULL,
    category       text        NOT NULL,
    country        text        NOT NULL,
    _loaded_at     timestamptz NOT NULL DEFAULT now(),
    _updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS dds.dds_dim_card (
    card_sk      bigserial   PRIMARY KEY,
    card_id      text        NOT NULL UNIQUE,
    account_id   text        NOT NULL,
    customer_id  text        NOT NULL,
    card_scheme  text        NOT NULL CHECK (card_scheme IN ('VISA', 'MASTERCARD')),
    _loaded_at   timestamptz NOT NULL DEFAULT now(),
    _updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_dim_card_account ON dds.dds_dim_card (account_id);

CREATE TABLE IF NOT EXISTS dds.dds_dim_account (
    account_sk    bigserial     PRIMARY KEY,
    account_id    text          NOT NULL,
    customer_id   text          NOT NULL,
    status        text          NOT NULL CHECK (status IN ('active', 'blocked', 'closed')),
    limit_amount  numeric(14,2) NOT NULL,
    is_deleted    boolean       NOT NULL,
    opened_at     date,
    valid_from    timestamptz   NOT NULL,
    valid_to      timestamptz   NOT NULL,
    is_current    boolean       NOT NULL,
    _loaded_at    timestamptz   NOT NULL DEFAULT now(),
    CONSTRAINT ck_dim_account_period CHECK (valid_from < valid_to),
    CONSTRAINT ex_dim_account_no_overlap EXCLUDE USING gist
        (account_id WITH =, tstzrange(valid_from, valid_to) WITH &&)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_dim_account_current ON dds.dds_dim_account (account_id) WHERE is_current;

CREATE TABLE IF NOT EXISTS dds.dds_fact_transaction (
    transaction_id        text          PRIMARY KEY,
    ds                    date          NOT NULL,
    date_key              integer       NOT NULL REFERENCES dds.dds_dim_date (date_key),
    customer_sk           bigint        NOT NULL REFERENCES dds.dds_dim_customer (customer_sk),
    card_sk               bigint        NOT NULL REFERENCES dds.dds_dim_card (card_sk),
    merchant_sk           bigint        REFERENCES dds.dds_dim_merchant (merchant_sk),
    account_id            text          NOT NULL,
    recipient_account_id  text,
    transaction_ts        timestamp     NOT NULL,
    amount                numeric(14,2) NOT NULL CHECK (amount > 0),
    currency              text          NOT NULL CHECK (currency IN ('KGS', 'USD', 'EUR')),
    fx_rate               numeric(12,4) NOT NULL CHECK (fx_rate > 0),
    amount_kgs            numeric(16,2) NOT NULL CHECK (amount_kgs > 0),
    channel               text          NOT NULL,
    payment_method        text          NOT NULL,
    transaction_type      text          NOT NULL CHECK (transaction_type IN ('PURCHASE', 'TRANSFER')),
    _loaded_at            timestamptz   NOT NULL DEFAULT now(),
    CONSTRAINT ck_fact_type CHECK (
        (transaction_type = 'PURCHASE' AND merchant_sk IS NOT NULL AND recipient_account_id IS NULL)
     OR (transaction_type = 'TRANSFER' AND recipient_account_id IS NOT NULL AND merchant_sk IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_fact_ds ON dds.dds_fact_transaction (ds);
CREATE INDEX IF NOT EXISTS ix_fact_card_ts ON dds.dds_fact_transaction (card_sk, transaction_ts);
CREATE INDEX IF NOT EXISTS ix_fact_customer ON dds.dds_fact_transaction (customer_sk);
CREATE INDEX IF NOT EXISTS ix_fact_recipient ON dds.dds_fact_transaction (recipient_account_id) WHERE recipient_account_id IS NOT NULL;
