-- etl_load_log for Airflow: every attempt of every task writes a row (FT-6).
-- New columns: layer (stg, ods, dds, datamart), run_id (Airflow DAG run), attempt (retry number).
-- Idempotent: safe to run repeatedly. The CLI loader from day 4 keeps working (defaults).

ALTER TABLE stg.etl_load_log ADD COLUMN IF NOT EXISTS layer   text NOT NULL DEFAULT 'stg';
ALTER TABLE stg.etl_load_log ADD COLUMN IF NOT EXISTS run_id  text;
ALTER TABLE stg.etl_load_log ADD COLUMN IF NOT EXISTS attempt integer;
