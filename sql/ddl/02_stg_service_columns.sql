DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['stg_transactions', 'stg_merchants', 'stg_cards'] LOOP

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'stg' AND table_name = t and column_name = '_source_file'
    ) THEN
        execute format('alter table stg.%I RENAME COLUMN _source_file to _source', t);
    end if;

    execute format('alter table stg.%I ADD COLUMN IF NOT EXISTS is_active boolean not null default true', t);
    execute format('alter table stg.%I add column if not exists is_deleted boolean not null default false', t);

    end loop;
end $$;