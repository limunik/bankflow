CREATE SCHEMA IF NOT EXISTS eval;

CREATE TABLE IF NOT EXISTS eval.ground_truth (
    transaction_id     text      PRIMARY KEY,
    is_fraud           smallint  NOT NULL CHECK (is_fraud IN (0, 1)),
    scenario           text      NOT NULL,
    scenario_id        text      NOT NULL,
    scenario_start_ts  timestamp NOT NULL
);

CREATE OR REPLACE FUNCTION eval.threshold_metrics(p_from date, p_to date)
RETURNS TABLE (threshold integer, tp bigint, fp bigint, fn bigint,
               precision_pct numeric, recall_pct numeric, f1_pct numeric,
               affected_cards bigint, cards_in_period bigint, affected_cards_pct numeric)
LANGUAGE sql STABLE AS $$
    WITH ops AS (
        SELECT f.transaction_id, f.card_sk, coalesce(s.total_points, 0) AS pts,
               coalesce(g.is_fraud, 0) AS is_fraud
        FROM dds.dds_fact_transaction f
        LEFT JOIN dds.dds_transaction_score s USING (transaction_id)
        LEFT JOIN eval.ground_truth g USING (transaction_id)
        WHERE f.ds BETWEEN p_from AND p_to
    ), cards AS (
        SELECT count(DISTINCT card_sk) AS n FROM ops
    ), m AS (
        SELECT t.thr,
               count(*) FILTER (WHERE o.pts >= t.thr AND o.is_fraud = 1) AS tp,
               count(*) FILTER (WHERE o.pts >= t.thr AND o.is_fraud = 0) AS fp,
               count(*) FILTER (WHERE o.pts < t.thr AND o.is_fraud = 1) AS fn,
               count(DISTINCT o.card_sk) FILTER (WHERE o.pts >= t.thr AND o.is_fraud = 0) AS bad_cards
        FROM generate_series(30, 70, 10) AS t(thr) CROSS JOIN ops o
        GROUP BY t.thr
    )
    SELECT m.thr, m.tp, m.fp, m.fn,
           round(100.0 * m.tp / nullif(m.tp + m.fp, 0), 1),
           round(100.0 * m.tp / nullif(m.tp + m.fn, 0), 1),
           round(200.0 * m.tp / nullif(2 * m.tp + m.fp + m.fn, 0), 1),
           m.bad_cards, c.n, round(100.0 * m.bad_cards / nullif(c.n, 0), 2)
    FROM m CROSS JOIN cards c
    ORDER BY m.thr
$$;

CREATE OR REPLACE FUNCTION eval.rule_metrics(p_from date, p_to date)
RETURNS TABLE (rule_code text, flagged bigint, tp bigint, fp bigint,
               precision_pct numeric, share_of_all_fraud_pct numeric)
LANGUAGE sql STABLE AS $$
    WITH fraud_total AS (
        SELECT count(*) AS n FROM dds.dds_fact_transaction f
        JOIN eval.ground_truth g USING (transaction_id)
        WHERE f.ds BETWEEN p_from AND p_to AND g.is_fraud = 1
    )
    SELECT r.rule_code,
           count(fl.transaction_id),
           count(*) FILTER (WHERE g.is_fraud = 1),
           count(*) FILTER (WHERE fl.transaction_id IS NOT NULL AND coalesce(g.is_fraud, 0) = 0),
           round(100.0 * count(*) FILTER (WHERE g.is_fraud = 1) / nullif(count(fl.transaction_id), 0), 1),
           round(100.0 * count(*) FILTER (WHERE g.is_fraud = 1) / nullif(max(t.n), 0), 1)
    FROM dds.dds_rule r
    CROSS JOIN fraud_total t
    LEFT JOIN dds.dds_transaction_flag fl ON fl.rule_code = r.rule_code AND fl.ds BETWEEN p_from AND p_to
    LEFT JOIN eval.ground_truth g ON g.transaction_id = fl.transaction_id
    GROUP BY r.rule_code
    ORDER BY r.rule_code
$$;

CREATE OR REPLACE FUNCTION eval.scenario_metrics(p_from date, p_to date, p_threshold integer DEFAULT 50)
RETURNS TABLE (scenario text, is_fraud smallint, operations bigint, caught bigint, caught_pct numeric)
LANGUAGE sql STABLE AS $$
    SELECT g.scenario, g.is_fraud, count(*),
           count(*) FILTER (WHERE coalesce(s.total_points, 0) >= p_threshold),
           round(100.0 * count(*) FILTER (WHERE coalesce(s.total_points, 0) >= p_threshold) / count(*), 1)
    FROM eval.ground_truth g
    JOIN dds.dds_fact_transaction f USING (transaction_id)
    LEFT JOIN dds.dds_transaction_score s USING (transaction_id)
    WHERE f.ds BETWEEN p_from AND p_to
    GROUP BY g.scenario, g.is_fraud
    ORDER BY g.is_fraud DESC, g.scenario
$$;

CREATE OR REPLACE FUNCTION eval.payday_metrics(p_from date, p_to date, p_rule text DEFAULT 'anomalous_amount')
RETURNS TABLE (day_type text, days bigint, operations bigint, false_flags bigint, false_flags_per_1000 numeric)
LANGUAGE sql STABLE AS $$
    SELECT CASE WHEN d.is_payday THEN 'зарплатный день' ELSE 'обычный день' END,
           count(DISTINCT f.ds), count(*),
           count(*) FILTER (WHERE fl.transaction_id IS NOT NULL AND coalesce(g.is_fraud, 0) = 0),
           round(1000.0 * count(*) FILTER (WHERE fl.transaction_id IS NOT NULL AND coalesce(g.is_fraud, 0) = 0) / count(*), 2)
    FROM dds.dds_fact_transaction f
    JOIN dds.dds_dim_date d ON d.date_key = f.date_key
    LEFT JOIN dds.dds_transaction_flag fl ON fl.transaction_id = f.transaction_id AND fl.rule_code = p_rule
    LEFT JOIN eval.ground_truth g ON g.transaction_id = f.transaction_id
    WHERE f.ds BETWEEN p_from AND p_to
    GROUP BY d.is_payday
    ORDER BY d.is_payday DESC
$$;
