-- STG for generated FX rates (USD, EUR to KGS). Same service columns as other STG tables (FT-3).

CREATE TABLE IF NOT EXISTS stg.stg_fx_rates (
    rate_date     text,
    currency      text,
    rate          text,
    _ds           date        NOT NULL,
    _source       text        NOT NULL,
    _loaded_at    timestamptz NOT NULL DEFAULT now(),
    is_active     boolean     NOT NULL DEFAULT true,
    is_deleted    boolean     NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS ix_stg_fx_rates_ds ON stg.stg_fx_rates (_ds);
