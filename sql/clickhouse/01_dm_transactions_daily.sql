CREATE DATABASE IF NOT EXISTS bankflow;

CREATE TABLE IF NOT EXISTS bankflow.dm_transactions_daily
(
    ds                    Date,
    operations            UInt32,
    purchases             UInt32,
    transfers             UInt32,
    active_cards          UInt32,
    amount_kgs            Decimal(18, 2),
    amount_usd            Decimal(18, 2),
    confirm_operations    UInt32,
    suspicious_operations UInt32,
    suspicious_share      Decimal(7, 4),
    loaded_at             DateTime DEFAULT now()
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ds)
ORDER BY ds;
