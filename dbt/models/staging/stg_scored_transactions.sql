select
    f.transaction_id,
    f.ds,
    f.card_sk,
    f.transaction_type,
    f.amount_kgs,
    coalesce(s.decision, 'allow') as decision
from {{ source('dds', 'dds_fact_transaction') }} as f
left join {{ source('dds', 'dds_transaction_score') }} as s
    on s.transaction_id = f.transaction_id
