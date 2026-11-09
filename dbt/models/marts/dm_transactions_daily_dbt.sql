select
    t.ds,
    count(*)::integer as operations,
    (count(*) filter (where t.transaction_type = 'PURCHASE'))::integer as purchases,
    (count(*) filter (where t.transaction_type = 'TRANSFER'))::integer as transfers,
    count(distinct t.card_sk)::integer as active_cards,
    sum(t.amount_kgs)::numeric(18, 2) as amount_kgs,
    round(sum(t.amount_kgs) / u.rate, 2)::numeric(18, 2) as amount_usd,
    (count(*) filter (where t.decision = 'confirm'))::integer as confirm_operations,
    (count(*) filter (where t.decision = 'suspicious'))::integer as suspicious_operations,
    round(count(*) filter (where t.decision = 'suspicious')::numeric / count(*), 4)::numeric(7, 4) as suspicious_share
from {{ ref('stg_scored_transactions') }} as t
join {{ ref('stg_usd_rate') }} as u on u.ds = t.ds
group by t.ds, u.rate
