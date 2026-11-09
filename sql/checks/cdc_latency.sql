\echo === события CDC по типам
SELECT op, count(*) AS events, count(*) FILTER (WHERE applied_at IS NULL) AS pending
FROM stg.stg_accounts_cdc GROUP BY op ORDER BY op;

\echo === задержка CDC: от изменения в oltp до строки в ods, секунды
SELECT count(*) AS events,
       round(percentile_cont(0.5)  WITHIN GROUP (ORDER BY lag)::numeric, 2) AS p50,
       round(percentile_cont(0.95) WITHIN GROUP (ORDER BY lag)::numeric, 2) AS p95,
       round(max(lag)::numeric, 2) AS max,
       round((100.0 * count(*) FILTER (WHERE lag <= 30) / count(*))::numeric, 1) AS pct_within_30s
FROM (SELECT extract(epoch FROM applied_at - source_ts) AS lag
      FROM stg.stg_accounts_cdc
      WHERE op IN ('c', 'u', 'd') AND applied_at IS NOT NULL) t;

\echo === то же для ночной загрузки (модель: пакет в 02:00 UTC следующих суток), часы
SELECT round((avg(extract(epoch FROM (date_trunc('day', source_ts) + interval '26 hours') - source_ts)) / 3600)::numeric, 1) AS avg_hours_nightly,
       round((min(extract(epoch FROM (date_trunc('day', source_ts) + interval '26 hours') - source_ts)) / 3600)::numeric, 1) AS min_hours_nightly
FROM stg.stg_accounts_cdc
WHERE op IN ('c', 'u', 'd');
