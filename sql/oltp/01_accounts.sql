-- OLTP (source system, CDC source): table bank.accounts.
-- Safe to run repeatedly.

CREATE SCHEMA IF NOT EXISTS bank;

CREATE TABLE IF NOT EXISTS bank.accounts (
    account_id    text          PRIMARY KEY,
    customer_id   text          NOT NULL,
    status        text          NOT NULL CHECK (status IN ('active', 'blocked', 'closed')),
    balance       numeric(14,2) NOT NULL,
    limit_amount  numeric(14,2) NOT NULL,
    opened_at     date          NOT NULL,
    updated_at    timestamptz   NOT NULL DEFAULT now()
);

-- Debezium will see the full old row on UPDATE and DELETE (needed for CDC, days 20-22)
ALTER TABLE bank.accounts REPLICA IDENTITY FULL;
