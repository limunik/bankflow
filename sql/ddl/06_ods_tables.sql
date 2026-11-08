-- Layer ODS: typed, keyed, deduplicated data (FT-4).
-- Keys: PK on every table; real FOREIGN KEYs where the parent is loaded in this layer.
-- Bad rows never stop a load: they go to ods.ods_reject with a reason.
-- Idempotent: safe to run repeatedly.

CREATE SCHEMA IF NOT EXISTS ods;

-- Customers (individual / legal)
CREATE TABLE IF NOT EXISTS ods.ods_customers (
    customer_id    text        PRIMARY KEY,
    customer_name  text        NOT NULL,
    customer_type  text        NOT NULL CHECK (customer_type IN ('individual', 'legal')),
    _ds            date        NOT NULL,                     -- load date that inserted or last changed the row
    _loaded_at     timestamptz NOT NULL DEFAULT now(),
    _updated_at    timestamptz NOT NULL DEFAULT now()
);

-- Merchants
CREATE TABLE IF NOT EXISTS ods.ods_merchants (
    merchant_id    text        PRIMARY KEY,
    merchant_name  text        NOT NULL,
    category       text        NOT NULL,
    country        char(2)     NOT NULL CHECK (country ~ '^[A-Z]{2}$'),
    _ds            date        NOT NULL,
    _loaded_at     timestamptz NOT NULL DEFAULT now(),
    _updated_at    timestamptz NOT NULL DEFAULT now()
);

-- Cards. account_id has no FK: accounts arrive through CDC later (days 21-23).
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

-- Transactions: purchases (merchant_id) and transfers (recipient_account_id)
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
    ds                    date          NOT NULL,            -- transaction date = file date
    _loaded_at            timestamptz   NOT NULL DEFAULT now(),
    _updated_at           timestamptz   NOT NULL DEFAULT now(),
    -- a purchase has a merchant and no recipient; a transfer is the opposite
    CONSTRAINT ck_ods_tx_type CHECK (
        (transaction_type = 'PURCHASE' AND merchant_id IS NOT NULL AND recipient_account_id IS NULL)
     OR (transaction_type = 'TRANSFER' AND recipient_account_id IS NOT NULL AND merchant_id IS NULL))
);
CREATE INDEX IF NOT EXISTS ix_ods_tx_ds       ON ods.ods_transactions (ds);
CREATE INDEX IF NOT EXISTS ix_ods_tx_card_ts  ON ods.ods_transactions (card_id, transaction_ts);

-- FX rates (loaded in day 10)
CREATE TABLE IF NOT EXISTS ods.ods_fx_rates (
    rate_date      date          NOT NULL,
    currency       text          NOT NULL CHECK (currency IN ('USD', 'EUR')),
    rate           numeric(12,4) NOT NULL CHECK (rate > 0),
    _ds            date          NOT NULL,
    _loaded_at     timestamptz   NOT NULL DEFAULT now(),
    _updated_at    timestamptz   NOT NULL DEFAULT now(),
    PRIMARY KEY (rate_date, currency)
);

-- Accounts: current state from CDC (filled in days 22-23). Delete in the source = soft delete here.
CREATE TABLE IF NOT EXISTS ods.ods_accounts (
    account_id     text          PRIMARY KEY,
    customer_id    text          NOT NULL,
    status         text          NOT NULL CHECK (status IN ('active', 'blocked', 'closed')),
    balance        numeric(14,2) NOT NULL,
    limit_amount   numeric(14,2) NOT NULL,
    opened_at      date,
    is_deleted     boolean       NOT NULL DEFAULT false,
    deleted_at     timestamptz,
    source_lsn     bigint        NOT NULL,                   -- position in the source log: newer wins
    updated_at     timestamptz   NOT NULL,                   -- last change time in the source
    _loaded_at     timestamptz   NOT NULL DEFAULT now()
);

-- Rejected rows: what was dropped from the load and why (data quality, FT-12)
CREATE TABLE IF NOT EXISTS ods.ods_reject (
    id           bigserial   PRIMARY KEY,
    source       text        NOT NULL,                       -- customers, merchants, cards, transactions, ...
    ds           date        NOT NULL,
    record_key   text,
    reason       text        NOT NULL,
    raw          jsonb,                                      -- the row exactly as it came from stg
    rejected_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_ods_reject_source_ds ON ods.ods_reject (source, ds);
