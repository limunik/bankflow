select ds
from {{ ref('dm_transactions_daily_dbt') }}
where suspicious_share < 0 or suspicious_share > 1
   or confirm_operations + suspicious_operations > operations
