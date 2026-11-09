with dbt_mart as (
    select ds, operations, purchases, transfers, active_cards, amount_kgs, amount_usd,
           confirm_operations, suspicious_operations, suspicious_share
    from {{ ref('dm_transactions_daily_dbt') }}
),
airflow_mart as (
    select ds, operations, purchases, transfers, active_cards, amount_kgs, amount_usd,
           confirm_operations, suspicious_operations, suspicious_share
    from datamart.dm_transactions_daily
),
only_dbt as (select * from dbt_mart except select * from airflow_mart),
only_airflow as (select * from airflow_mart except select * from dbt_mart)
select * from only_dbt
union all
select * from only_airflow
