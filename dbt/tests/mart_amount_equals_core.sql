select m.ds
from {{ ref('dm_transactions_daily_dbt') }} as m
join (
    select ds, sum(amount_kgs) as total
    from {{ source('dds', 'dds_fact_transaction') }}
    group by ds
) as f on f.ds = m.ds
where f.total <> m.amount_kgs
