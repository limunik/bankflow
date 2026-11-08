CREATE SCHEMA IF NOT EXISTS ods;

CREATE TABLE IF NOT EXISTS ods.ods_customers (
    customer_id    text        PRIMARY KEY,
    customer_name  text        NOT NULL,
    customer_type  text        NOT NULL CHECK (customer_type IN ('individual', 'legal')),
    _ds            date        NOT NULL,
    _loaded_at     timestamptz NOT NULL DEFAULT now(),
    _updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ods.ods_merchants (
    merchant_id    text        PRIMARY KEY,
    merchant_name  text        NOT NULL,
    category       text        NOT NULL,
    country        char(2)     NOT NULL CHECK (country ~ '^[A-Z]{2}$'),
    _ds            date        NOT NULL,
    _loaded_at     timestamptz NOT NULL DEFAULT now(),
    _updated_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ods.ods_cards (
    card_id        text        PRIMARY KEY,
    account_id     text        NOT NULL,
    customer_id    text        NOT NULL REFERENCES ods.ods_customers (customer_id),
    card_scheme    text        NOT NULL CHECK (card_scheme IN ('VISA', 'MASTERCARD')),
    _ds            date        NOT NULL,
    _loaded_at     timestamptz NOT NULL DEFAULT now(),
    _updated_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ods_cards_account  ON ods.ods_cards (account_id);
CREATE INDEX IF NOT EXISTS ix_ods_cards_customer ON ods.ods_cards (customer_id);

CREATE TABLE IF NOT EXISTS ods.ods_transactions (
    transaction_id        text          PRIMARY KEY,
    card_id               text          NOT NULL REFERENCES ods.ods_cards (card_id),
    account_id            text          NOT NULL,
    customer_id           text          NOT NULL REFERENCES ods.ods_customers (customer_id),
    merchant_id           text          REFERENCES ods.ods_merchants (merchant_id),
    recipient_account_id  text,
    transaction_ts        timestamp     NOT NULL,
    amount                numeric(14,2) NOT NULL CHECK (amount > 0),
    currency              text          NOT NULL CHECK (currency IN ('KGS', 'USD', 'EUR')),
    channel               text          NOT NULL CHECK (channel IN ('POS', 'ONLINE')),
    payment_method        text          NOT NULL CHECK (payment_method IN ('CARD', 'QR', 'APPLE_PAY', 'BANK_APP')),
    transaction_type      text          NOT NULL CHECK (transaction_type IN ('PURCHASE', 'TRANSFER')),
    ds                    date          NOT NULL,
    _loaded_at            timestamptz   NOT NULL DEFAULT now(),
    _updated_at           timestamptz   NOT NULL DEFAULT now(),
    CONSTRAINT ck_ods_tx_type CHECK (
        (transaction_type = 'PURCHASE' AND merchant_id IS NOT NULL AND recipient_account_id IS NULL)
     OR (transaction_type = 'TRANSFER' AND recipient_account_id IS NOT NULL AND merchant_id IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_ods_tx_ds       ON ods.ods_transactions (ds);
CREATE INDEX IF NOT EXISTS ix_ods_tx_card_ts  ON ods.ods_transactions (card_id, transaction_ts);

CREATE TABLE IF NOT EXISTS ods.ods_fx_rates (
    rate_date      date          NOT NULL,
    currency       text          NOT NULL CHECK (currency IN ('USD', 'EUR')),
    rate           numeric(12,4) NOT NULL CHECK (rate > 0),
    _ds            date          NOT NULL,
    _loaded_at     timestamptz   NOT NULL DEFAULT now(),
    _updated_at    timestamptz   NOT NULL DEFAULT now(),
    PRIMARY KEY (rate_date, currency)
);

CREATE TABLE IF NOT EXISTS ods.ods_accounts (
    account_id     text          PRIMARY KEY,
    customer_id    text          NOT NULL,
    status         text          NOT NULL CHECK (status IN ('active', 'blocked', 'closed')),
    balance        numeric(14,2) NOT NULL,
    limit_amount   numeric(14,2) NOT NULL,
    opened_at      date,
    is_deleted     boolean       NOT NULL DEFAULT false,
    deleted_at     timestamptz,
    source_lsn     bigint        NOT NULL,
    updated_at     timestamptz   NOT NULL,
    _loaded_at     timestamptz   NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ods.ods_reject (
    id           bigserial   PRIMARY KEY,
    source       text        NOT NULL,
    ds           date        NOT NULL,
    record_key   text,
    reason       text        NOT NULL,
    raw          jsonb,
    rejected_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ods_reject_source_ds ON ods.ods_reject (source, ds);
