CREATE TABLE IF NOT EXISTS dds.dds_rule (
    rule_code    text    PRIMARY KEY,
    description  text    NOT NULL,
    points       integer NOT NULL,
    enabled      boolean NOT NULL DEFAULT true
);

INSERT INTO dds.dds_rule (rule_code, description, points) VALUES
('inactive_account', 'Операция по счёту со статусом blocked, closed или удалённому', 60),
('two_countries', 'Две покупки по карте на терминале (POS) в разных странах с разницей менее часа', 50),
('series', 'Пять и более операций по карте в окне 60 секунд', 40),
('anomalous_amount', 'Сумма больше 5 медиан клиента за последние 30 дней (не менее 5 операций) для того же типа', 30),
('new_recipient_big', 'Крупный перевод получателю, которому клиент раньше не переводил', 40),
('trusted_recipient', 'Получатель, которому клиент уже переводил не менее двух раз в прошлые дни', -20)
ON CONFLICT (rule_code) DO UPDATE SET description = EXCLUDED.description, points = EXCLUDED.points;

CREATE TABLE IF NOT EXISTS dds.dds_decision_level (
    decision    text    PRIMARY KEY,
    min_points  integer NOT NULL
);

INSERT INTO dds.dds_decision_level (decision, min_points) VALUES
('allow', 0), ('confirm', 30), ('suspicious', 50)
ON CONFLICT (decision) DO UPDATE SET min_points = EXCLUDED.min_points;

CREATE TABLE IF NOT EXISTS dds.dds_transaction_flag (
    transaction_id  text    NOT NULL,
    rule_code       text    NOT NULL REFERENCES dds.dds_rule (rule_code),
    points          integer NOT NULL,
    ds              date    NOT NULL,
    _loaded_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (transaction_id, rule_code)
);
CREATE INDEX IF NOT EXISTS ix_flag_ds ON dds.dds_transaction_flag (ds);

CREATE TABLE IF NOT EXISTS dds.dds_transaction_score (
    transaction_id  text    PRIMARY KEY,
    ds              date    NOT NULL,
    total_points    integer NOT NULL CHECK (total_points >= 0),
    decision        text    NOT NULL REFERENCES dds.dds_decision_level (decision),
    rules           text    NOT NULL,
    _loaded_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_score_ds ON dds.dds_transaction_score (ds);
CREATE INDEX IF NOT EXISTS ix_fact_account_recipient ON dds.dds_fact_transaction (account_id, recipient_account_id)
    WHERE recipient_account_id IS NOT NULL;

CREATE OR REPLACE FUNCTION dds.load_flags(p_ds date)
RETURNS TABLE (src_rows integer, inserted integer, updated integer)
LANGUAGE plpgsql AS $$
DECLARE
    v_src integer; v_flags integer;
BEGIN
    PERFORM pg_advisory_xact_lock(hashtext('dds.dds_transaction_flag:' || p_ds::text));
    SELECT count(*) INTO v_src FROM dds.dds_fact_transaction WHERE ds = p_ds;

    DELETE FROM dds.dds_transaction_score WHERE ds = p_ds;
    DELETE FROM dds.dds_transaction_flag WHERE ds = p_ds;

    CREATE TEMP TABLE tmp_flag (transaction_id text, rule_code text) ON COMMIT DROP;

    INSERT INTO tmp_flag
    SELECT f.transaction_id, 'inactive_account'
    FROM dds.dds_fact_transaction f
    JOIN dds.dds_dim_account a ON a.account_id = f.account_id
         AND (f.transaction_ts AT TIME ZONE 'UTC') >= a.valid_from
         AND (f.transaction_ts AT TIME ZONE 'UTC') < a.valid_to
    WHERE f.ds = p_ds AND (a.status IN ('blocked', 'closed') OR a.is_deleted);

    INSERT INTO tmp_flag
    SELECT t.transaction_id, 'two_countries'
    FROM dds.dds_fact_transaction t
    JOIN dds.dds_dim_merchant mt ON mt.merchant_sk = t.merchant_sk
    WHERE t.ds = p_ds AND t.channel = 'POS' AND EXISTS (
        SELECT 1 FROM dds.dds_fact_transaction p
        JOIN dds.dds_dim_merchant mp ON mp.merchant_sk = p.merchant_sk
        WHERE p.card_sk = t.card_sk
          AND p.channel = 'POS'
          AND p.transaction_ts < t.transaction_ts
          AND p.transaction_ts > t.transaction_ts - interval '1 hour'
          AND mp.country <> mt.country);

    INSERT INTO tmp_flag
    WITH starts AS (
        SELECT card_sk, transaction_ts AS start_ts,
               count(*) OVER (PARTITION BY card_sk ORDER BY transaction_ts
                              RANGE BETWEEN CURRENT ROW AND interval '59 seconds' FOLLOWING) AS cnt
        FROM dds.dds_fact_transaction WHERE ds = p_ds
    ), burst AS (
        SELECT DISTINCT card_sk, start_ts FROM starts WHERE cnt >= 5
    )
    SELECT DISTINCT f.transaction_id, 'series'
    FROM burst b
    JOIN dds.dds_fact_transaction f ON f.card_sk = b.card_sk AND f.ds = p_ds
         AND f.transaction_ts >= b.start_ts AND f.transaction_ts < b.start_ts + interval '60 seconds';

    CREATE TEMP TABLE tmp_baseline ON COMMIT DROP AS
    SELECT c.customer_id, f.transaction_type,
           percentile_cont(0.5) WITHIN GROUP (ORDER BY f.amount_kgs) AS median_kgs
    FROM dds.dds_fact_transaction f
    JOIN dds.dds_dim_customer c ON c.customer_sk = f.customer_sk
    WHERE f.ds >= p_ds - 30 AND f.ds < p_ds
    GROUP BY c.customer_id, f.transaction_type
    HAVING count(*) >= 5;

    CREATE TEMP TABLE tmp_today ON COMMIT DROP AS
    SELECT f.transaction_id, f.transaction_type, f.amount_kgs, f.account_id, f.recipient_account_id,
           c.customer_id, b.median_kgs
    FROM dds.dds_fact_transaction f
    JOIN dds.dds_dim_customer c ON c.customer_sk = f.customer_sk
    LEFT JOIN tmp_baseline b ON b.customer_id = c.customer_id AND b.transaction_type = f.transaction_type
    WHERE f.ds = p_ds;

    INSERT INTO tmp_flag
    SELECT transaction_id, 'anomalous_amount'
    FROM tmp_today WHERE median_kgs IS NOT NULL AND amount_kgs > 5 * median_kgs;

    INSERT INTO tmp_flag
    SELECT t.transaction_id, 'new_recipient_big'
    FROM tmp_today t
    WHERE t.transaction_type = 'TRANSFER' AND t.median_kgs IS NOT NULL AND t.amount_kgs > 5 * t.median_kgs
      AND NOT EXISTS (SELECT 1 FROM dds.dds_fact_transaction p
                      WHERE p.account_id = t.account_id AND p.recipient_account_id = t.recipient_account_id
                        AND p.ds < p_ds);

    INSERT INTO tmp_flag
    SELECT t.transaction_id, 'trusted_recipient'
    FROM tmp_today t
    WHERE t.transaction_type = 'TRANSFER'
      AND (SELECT count(*) FROM dds.dds_fact_transaction p
           WHERE p.account_id = t.account_id AND p.recipient_account_id = t.recipient_account_id
             AND p.ds < p_ds) >= 2;

    INSERT INTO dds.dds_transaction_flag (transaction_id, rule_code, points, ds)
    SELECT g.transaction_id, g.rule_code, r.points, p_ds
    FROM tmp_flag g JOIN dds.dds_rule r ON r.rule_code = g.rule_code AND r.enabled
    ORDER BY g.transaction_id, g.rule_code;
    GET DIAGNOSTICS v_flags = ROW_COUNT;

    INSERT INTO dds.dds_transaction_score (transaction_id, ds, total_points, decision, rules)
    SELECT s.transaction_id, p_ds, s.total,
           (SELECT l.decision FROM dds.dds_decision_level l WHERE l.min_points <= s.total
            ORDER BY l.min_points DESC LIMIT 1),
           s.rules
    FROM (SELECT transaction_id, greatest(sum(points), 0)::integer AS total,
                 string_agg(rule_code, ',' ORDER BY rule_code) AS rules
          FROM dds.dds_transaction_flag WHERE ds = p_ds GROUP BY transaction_id) s
    ORDER BY s.transaction_id;

    RETURN QUERY SELECT v_src, v_flags, 0;
END $$;

INSERT INTO dq.check_def (check_name, layer, severity, description, check_sql) VALUES
('dds_flags_key_unique', 'dds', 'error', 'Пара (transaction_id, rule_code) уникальна в флагах',
 $q$SELECT coalesce(sum(c - 1), 0) FROM (SELECT count(*) AS c FROM dds.dds_transaction_flag WHERE ds = $1 GROUP BY transaction_id, rule_code HAVING count(*) > 1) x$q$),
('dds_flags_orphans', 'dds', 'error', 'Каждый флаг относится к операции из факта',
 $q$SELECT count(*) FROM dds.dds_transaction_flag g WHERE g.ds = $1 AND NOT EXISTS (SELECT 1 FROM dds.dds_fact_transaction f WHERE f.transaction_id = g.transaction_id)$q$),
('dds_score_matches_flags', 'dds', 'error', 'Баллы операции равны сумме баллов её флагов (не меньше нуля)',
 $q$SELECT count(*) FROM dds.dds_transaction_score s JOIN (SELECT transaction_id, greatest(sum(points), 0) AS total FROM dds.dds_transaction_flag WHERE ds = $1 GROUP BY transaction_id) g USING (transaction_id) WHERE s.ds = $1 AND s.total_points <> g.total$q$),
('dds_score_decision_valid', 'dds', 'error', 'Решение соответствует баллам по таблице уровней',
 $q$SELECT count(*) FROM dds.dds_transaction_score s WHERE s.ds = $1 AND s.decision <> (SELECT l.decision FROM dds.dds_decision_level l WHERE l.min_points <= s.total_points ORDER BY l.min_points DESC LIMIT 1)$q$)
ON CONFLICT (check_name) DO UPDATE
    SET layer = EXCLUDED.layer, severity = EXCLUDED.severity,
        description = EXCLUDED.description, check_sql = EXCLUDED.check_sql;
