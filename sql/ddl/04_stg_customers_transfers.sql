-- Customers (individual / legal) and transfers: new STG table and two new columns.
-- Idempotent: safe to run repeatedly.

CREATE TABLE IF NOT EXISTS stg.stg_customers (
    customer_id    text,
    customer_name  text,
    customer_type  text,
    _ds            date        NOT NULL,
    _source        text        NOT NULL,
    _loaded_at     timestamptz NOT NULL DEFAULT now(),
    is_active      boolean     NOT NULL DEFAULT true,
    is_deleted     boolean     NOT NULL DEFAULT false
);

-- TRANSFER operations have recipient_account_id instead of merchant_id
ALTER TABLE stg.stg_transactions ADD COLUMN IF NOT EXISTS transaction_type      text;
ALTER TABLE stg.stg_transactions ADD COLUMN IF NOT EXISTS recipient_account_id  text;
